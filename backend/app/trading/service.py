"""Background paper-trading service: live data -> technical signal -> Decision Engine -> Risk Engine -> PaperBroker.

Paper only (no live adapter exists). The service starts PAUSED; only an admin action turns it ACTIVE.
PAUSED blocks new entries; stop-loss / take-profit / max-hold exits keep running for open positions.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from .. import market_data as md
from .. import settings_service as ss
from ..broker.base import OrderRequest, Quote, Side
from ..broker.paper import PaperBroker
from ..engines.decision import DecisionConfig, EngineSignal, decide
from ..engines.technical import TechnicalParams, analyze
from ..models import (Alert, AuditLog, BrokerAccount, BrokerOrder, EquitySnapshot, Instrument as InstrumentRow, Position,
                      RiskCheck, Strategy, StrategyVersion, SystemSetting, Trade, TradingDecision)
from ..risk.engine import (AccountState, Instrument, OpenPosition, RiskLimits, SystemState, TradeProposal, drawdown_pct,
                           evaluate, evaluate_system_level, positions_to_force_close)

log = logging.getLogger("trading")

TF = "15m"
BAR = timedelta(minutes=15)
MAX_BAR_LAG = timedelta(minutes=10)   # a closed bar older than this is never traded (restart / outage guard)
ATR_SL_MULT, RR = 1.5, 2.0
STEP_SECONDS = 1
SNAPSHOT_EVERY = 60
STATE_KEY = "trading_state"
STRATEGY_NAME = "Technical EMA/RSI/MACD (paper)"
# symbol -> (max spread in price units, min units, unit step). Only symbols with a live FXCM feed are traded.
# XAUUSD is displayed but not traded: 1 oz risks 30-45 ILS vs a ~7 ILS per-trade budget, so it is always risk-rejected
# (it needs ~0.6% risk per trade). Commodities below are USD-quoted CFDs without a 3+3 letter pair name.
SPEC = {"USDILS": (0.01, 1000, 1000), "GBPUSD": (0.0005, 1000, 1000), "EURUSD": (0.0005, 1000, 1000),
        "AUDUSD": (0.0005, 1000, 1000), "NZDUSD": (0.0006, 1000, 1000), "USDCAD": (0.0006, 1000, 1000),
        "USDCHF": (0.0006, 1000, 1000), "USDJPY": (0.05, 1000, 1000),
        "USOIL": (0.08, 1, 1), "UKOIL": (0.08, 1, 1), "COPPER": (0.01, 1, 1)}
# XAGUSD and NGAS are not traded: they lost in all 24 parameter combinations of the backtest grid (spread >> edge).
# Their feed stays on for display; an already open NGAS position is still managed (SL/TP) through the quote feed.
COMMODITIES = {"USOIL", "UKOIL", "NGAS", "COPPER"}   # base = the symbol itself, quote = USD
# Skip an entry when the spread would eat more than this share of the stop distance (cost drag on every trade).
MAX_SPREAD_SL_RATIO = 0.30
# USD-based pairs whose quote currency needs a USD/xxx rate to convert P&L into the account currency.
USD_BASED_QUOTES = {"CAD": "USDCAD", "CHF": "USDCHF", "JPY": "USDJPY"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc(t: datetime | None) -> datetime | None:
    return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)


# ---------------- persisted system state ----------------
def get_state(db: Session) -> str:
    row = db.scalars(select(SystemSetting).where(SystemSetting.key == STATE_KEY, SystemSetting.is_current)).first()
    return row.value["state"] if row else "PAUSED"


def set_state(db: Session, new: str, reason: str, ip: str | None = None) -> str:
    old = get_state(db)
    if old == new:
        return old
    ver = db.scalar(select(func.max(SystemSetting.version)).where(SystemSetting.key == STATE_KEY)) or 0
    db.execute(update(SystemSetting).where(SystemSetting.key == STATE_KEY).values(is_current=False))
    db.add(SystemSetting(key=STATE_KEY, version=ver + 1, value={"state": new, "reason": reason}, is_current=True))
    db.add(AuditLog(action=f"system.state.{new.lower()}", target=STATE_KEY, old_value={"state": old},
                    new_value={"state": new, "reason": reason}, ip=ip))
    db.commit()
    return new


_PERIOD_CACHE: dict = {}   # (account_id, since, initial) -> (monotonic_ts, value); the answer only changes at period boundaries


def period_start_equity(db: Session, account_id, since: datetime, initial: float) -> float:
    """Equity at the last snapshot before `since`; the initial capital when there is none."""
    if account_id is None:
        return initial
    key = (account_id, since, initial)
    hit = _PERIOD_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    r = db.scalars(select(EquitySnapshot.equity).where(EquitySnapshot.account_id == account_id, EquitySnapshot.ts < since)
                   .order_by(EquitySnapshot.ts.desc()).limit(1)).first()
    v = initial if r is None else r
    _PERIOD_CACHE[key] = (time.monotonic(), v)
    return v


def period_starts(now: datetime) -> dict[str, datetime]:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"day": day, "week": day - timedelta(days=day.weekday()), "month": day.replace(day=1)}


class TradingService:
    def __init__(self, sf: sessionmaker):
        self.sf = sf
        self.lock = threading.RLock()
        self.broker: PaperBroker | None = None
        self.account_id = None
        self.version_id = None
        self.currency = "ILS"
        self.initial = 10_000.0
        self.peak = 10_000.0
        self.last_bar: dict[str, datetime] = {}
        self.quote_ts: dict[str, datetime] = {}
        self.last_snapshot = 0.0
        self.last_step_at: datetime | None = None
        self.last_error: str | None = None
        self.instruments: dict[str, uuid.UUID] = {}

    # ---------- startup / restore ----------
    def startup(self) -> None:
        with self.sf() as db:
            g = ss.get_current(db, "general")["value"]
            self.initial, self.currency = float(g["initial_capital"]), g["account_currency"]
            acct = db.scalars(select(BrokerAccount).where(BrokerAccount.broker == "paper")).first()
            if acct is None:
                acct = BrokerAccount(name="Paper", broker="paper", mode="PAPER", currency=self.currency, live_approved=False)
                db.add(acct)
                db.commit()
            self.account_id = acct.id
            self.version_id = self._ensure_strategy(db)
            realized = db.scalar(select(func.coalesce(func.sum(Trade.net_pnl), 0.0))
                                 .where(Trade.exit_time.is_not(None), Trade.mode == "PAPER")) or 0.0
            b = PaperBroker(balance=self.initial + realized, currency=self.currency, leverage=20.0, min_units=1,
                            quote_to_account={self.currency: 1.0}, quote_ccy={c: "USD" for c in COMMODITIES})
            b.connect()
            rows = db.execute(select(Position, InstrumentRow.symbol).join(InstrumentRow, InstrumentRow.id == Position.instrument_id)
                              .where(Position.is_open, Position.account_id == acct.id)).all()
            for p, sym in rows:
                pid = p.id.hex
                b.positions[pid] = {"id": pid, "symbol": sym, "side": p.side, "units": p.units, "entry": p.entry_price,
                                    "stop_loss": p.stop_loss, "take_profit": p.take_profit, "opened_at": _utc(p.opened_at),
                                    "fees": 0.0, "client_order_id": "restored"}
            peak = db.scalar(select(func.max(EquitySnapshot.peak_equity)).where(EquitySnapshot.account_id == acct.id))
            self.peak = max(self.initial, peak or 0.0)
            self.broker = b

    def _ensure_strategy(self, db: Session):
        s = db.scalars(select(Strategy).where(Strategy.name == STRATEGY_NAME)).first()
        if s is None:
            s = Strategy(name=STRATEGY_NAME, status="paper",
                         description="Technical-only until news/macro AI signals are connected")
            db.add(s)
            db.flush()
        v = db.scalars(select(StrategyVersion).where(StrategyVersion.strategy_id == s.id, StrategyVersion.version == 1)).first()
        if v is None:
            v = StrategyVersion(strategy_id=s.id, version=1, published_at=utcnow(),
                                config={"timeframe": TF, "atr_sl_mult": ATR_SL_MULT, "rr": RR, "mode": "technical_only"})
            db.add(v)
        db.commit()
        return v.id

    def _instrument_id(self, db: Session, symbol: str):
        if symbol not in self.instruments:
            self.instruments[symbol] = db.scalar(select(InstrumentRow.id).where(InstrumentRow.symbol == symbol))
        return self.instruments[symbol]

    # ---------- one cycle ----------
    def step(self) -> None:
        with self.lock:
            if self.broker is None:
                self.startup()
            now = utcnow()
            with self.sf() as db:
                risk_s = ss.get_current(db, "risk")["value"]
                lim = RiskLimits(**risk_s, account_currency=self.currency)
                quotes = md.latest_quotes(db, window_seconds=600)
                self._feed(db, quotes)
                self.peak = max(self.peak, self.broker.get_account()["equity"])
                self._risk_exits(db, lim, now)
                if get_state(db) == "ACTIVE":
                    self._entries(db, quotes, lim, now)
                if now.timestamp() - self.last_snapshot >= SNAPSHOT_EVERY:
                    self._snapshot(db, now)
            self.last_step_at = now

    def _feed(self, db: Session, quotes: dict) -> None:
        if self.currency == "ILS" and "USDILS" in quotes:
            self.broker.q2a["USD"] = quotes["USDILS"]["mid"]
            for ccy, pair in USD_BASED_QUOTES.items():
                if pair in quotes and quotes[pair]["mid"] > 0:
                    self.broker.q2a[ccy] = quotes["USDILS"]["mid"] / quotes[pair]["mid"]
        for sym, q in quotes.items():
            t = datetime.fromisoformat(q["ts"])
            if self.quote_ts.get(sym) == t:
                continue
            self.quote_ts[sym] = t
            for rec in self.broker.set_quote(Quote(sym, q["bid"], q["ask"], t)):
                self._persist_close(db, rec)

    def _account_state(self, db: Session, now: datetime) -> AccountState:
        acct = self.broker.get_account()
        st = period_starts(now)
        pos = [OpenPosition(p["symbol"], p["side"], p["units"], p["entry"], p["stop_loss"], self.broker._rate(p["symbol"]),
                            _utc(p["opened_at"])) for p in self.broker.get_positions()]
        return AccountState(acct["equity"], self.peak, period_start_equity(db, self.account_id, st["day"], self.initial),
                            period_start_equity(db, self.account_id, st["week"], self.initial), pos,
                            SystemState(get_state(db)))

    def _risk_exits(self, db: Session, lim: RiskLimits, now: datetime) -> None:
        acc = self._account_state(db, now)
        state, why = evaluate_system_level(acc, lim)
        if state == SystemState.EMERGENCY_STOP and acc.system_state != SystemState.EMERGENCY_STOP:
            set_state(db, "EMERGENCY_STOP", why[0])
            db.add(Alert(severity="critical", kind="emergency_stop", message=why[0]))
            db.commit()
        if state == SystemState.EMERGENCY_STOP:
            for p in self.broker.get_positions():
                self._close(db, p["id"], "EMERGENCY_STOP")
            return
        for pos, reason in positions_to_force_close(acc, lim, now):
            pid = next((p["id"] for p in self.broker.get_positions() if p["symbol"] == pos.symbol), None)
            if pid:
                self._close(db, pid, "MAX_HOLD")

    def _close(self, db: Session, pid: str, reason: str) -> None:
        self._persist_close(db, self.broker.close_position(pid, reason))

    def _persist_close(self, db: Session, rec: dict) -> None:
        pid = uuid.UUID(rec["id"])
        p = db.get(Position, pid)
        if p:
            p.is_open = False
        t = db.scalars(select(Trade).where(Trade.position_id == pid)).first()
        if t:
            t.exit_time, t.exit_price, t.fees = _utc(rec["closed_at"]), rec["exit"], rec["fees"]
            t.net_pnl, t.exit_reason = rec["net_pnl"], rec["exit_reason"]
            t.events = [*t.events, {"t": utcnow().isoformat(), "type": "closed", "reason": rec["exit_reason"], "price": rec["exit"]}]
            db.add(Alert(severity="info" if rec["net_pnl"] >= 0 else "warning", kind="trade_closed", trade_id=t.id,
                         message=f"#{t.number} {rec['symbol']} {rec['side']} closed ({rec['exit_reason']}) net {rec['net_pnl']:+.2f}"))
        db.commit()

    # ---------- decisions ----------
    def _entries(self, db: Session, quotes: dict, lim: RiskLimits, now: datetime) -> None:
        for sym in SPEC:
            q = quotes.get(sym)
            if not q:
                continue
            # Skip the (expensive) candle query until a new 15m bar can exist: keeps each step fast enough for 1s live equity.
            expected_open = datetime.fromtimestamp(now.timestamp() // BAR.total_seconds() * BAR.total_seconds(), timezone.utc) - BAR
            if self.last_bar.get(sym) and _utc(self.last_bar[sym]) >= expected_open:
                continue
            try:
                df = md.live_candles(db, sym, TF, limit=400)
                if df is None or len(df) < 60:
                    continue
                last = df.index[-1].to_pydatetime()
                if self.last_bar.get(sym) == last:
                    continue
                self.last_bar[sym] = last
                if now - (last + BAR) > MAX_BAR_LAG:
                    continue
                self._evaluate(db, sym, df, last + BAR, q, lim, now)
            except Exception:
                db.rollback()
                log.exception("evaluation failed for %s", sym)

    def _decision_cfg(self, db: Session) -> DecisionConfig:
        d = ss.get_current(db, "decision")["value"]
        # News/macro AI signals are not connected yet: technical is the only engine (a single engine must be enough to act).
        return DecisionConfig(w_technical=100, w_news=0, w_macro=0, min_signal=d["min_signal"], min_agreeing_engines=1,
                              cooldown_minutes=d["cooldown_minutes"])

    def _evaluate(self, db: Session, sym: str, df, bar_close: datetime, q: dict, lim: RiskLimits, now: datetime) -> None:
        tr = analyze(df.tail(400), TechnicalParams(compute_levels=False))
        inst_id = self._instrument_id(db, sym)
        pos = next((p for p in self.broker.get_positions() if p["symbol"] == sym), None)
        last_entry = _utc(db.scalar(select(func.max(Trade.entry_time)).where(Trade.instrument_id == inst_id)))
        spread = q["ask"] - q["bid"]
        dec = decide(sym, now, {"technical": EngineSignal("technical", tr.score, bar_close)}, self._decision_cfg(db),
                     open_side=pos["side"] if pos else None, expected_move=tr.atr * ATR_SL_MULT * RR, est_cost=spread,
                     last_entry_at=last_entry, bar_time=bar_close)
        key = dec.idempotency_key or f"{sym}:{dec.action}:{bar_close:%Y%m%d%H%M}"
        if db.scalar(select(TradingDecision.id).where(TradingDecision.idempotency_key == key)):
            return
        row = TradingDecision(id=uuid.uuid4(), instrument_id=inst_id, strategy_version_id=self.version_id, action=dec.action,
                              score=dec.score, idempotency_key=key, execution_status="none",
                              reason={"mode": "technical_only", "reasons": dec.reasons, "blockers": dec.blockers,
                                      "contributions": dec.contributions},
                              market_snapshot={"bid": q["bid"], "ask": q["ask"], "spread": spread, "atr": float(tr.atr),
                                               "bar_close": bar_close.isoformat(), "regime": tr.regime, "direction": tr.direction,
                                               "components": {k: float(v) for k, v in tr.components.items()}})
        db.add(row)
        db.flush()
        if dec.action in ("BUY", "SELL") and pos is None:
            row.execution_status = self._enter(db, row, sym, key, dec.action, dec.reasons, tr.atr, q, lim, now)
        elif dec.action == "CLOSE" and pos:
            self._close(db, pos["id"], "SIGNAL_REVERSAL")
            row.execution_status = "closed"
        db.commit()

    def _enter(self, db: Session, row: TradingDecision, sym: str, key: str, side: str, reasons: list, atr: float, q: dict,
               lim: RiskLimits, now: datetime) -> str:
        max_spread, min_u, step = SPEC[sym]
        base, quote = (sym, "USD") if sym in COMMODITIES else (sym[:3], sym[3:])
        q2a = self.broker.q2a.get(quote)
        if q2a is None:
            return "no_conversion_rate"
        buy = side == "BUY"
        entry = q["ask"] if buy else q["bid"]
        d = atr * ATR_SL_MULT
        if (q["ask"] - q["bid"]) > d * MAX_SPREAD_SL_RATIO:
            return "spread_too_wide"
        sl, tp = (entry - d, entry + d * RR) if buy else (entry + d, entry - d * RR)
        inst = Instrument(sym, base, quote, min_units=min_u, unit_step=step, max_spread=max_spread, max_slippage=max_spread)
        prop = TradeProposal(inst, side, entry, sl, q["bid"], q["ask"], datetime.fromisoformat(q["ts"]), q2a, take_profit=tp)
        rd = evaluate(prop, self._account_state(db, now), lim, now)
        db.add(RiskCheck(decision_id=row.id, allowed=rd.allowed, units=rd.units, risk_amount=rd.risk_amount,
                         reasons=rd.reasons + rd.flags, drawdown_pct=rd.drawdown_pct))
        if not rd.allowed:
            return "risk_rejected"
        res = self.broker.place_order(OrderRequest(key, sym, Side(side), rd.units, sl, tp))
        db.add(BrokerOrder(account_id=self.account_id, decision_id=row.id, client_order_id=key, broker_order_id=res.get("position_id"),
                           instrument_id=row.instrument_id, side=side, units=rd.units, status=res["status"],
                           fill_price=res.get("fill_price"), reject_reason=res.get("reason")))
        if res["status"] != "FILLED":
            db.add(Alert(severity="warning", kind="order_rejected", message=f"{sym} {side}: {res.get('reason')}"))
            return "broker_rejected"
        pid, fill = uuid.UUID(res["position_id"]), res["fill_price"]
        db.add(Position(id=pid, account_id=self.account_id, instrument_id=row.instrument_id, side=side, units=rd.units,
                        entry_price=fill, stop_loss=sl, take_profit=tp, opened_at=now, is_open=True))
        db.flush()
        number = (db.scalar(select(func.max(Trade.number))) or 0) + 1
        tid = uuid.uuid4()
        db.add(Trade(id=tid, number=number, position_id=pid, decision_id=row.id, strategy_version_id=self.version_id,
                     instrument_id=row.instrument_id, mode="PAPER", side=side, units=rd.units, entry_time=now, entry_price=fill,
                     stop_loss=sl, take_profit=tp, spread_cost=(q["ask"] - q["bid"]) * rd.units * q2a,
                     entry_reason="; ".join(reasons), events=[{"t": now.isoformat(), "type": "opened", "price": fill}]))
        db.flush()
        db.add(Alert(severity="info", kind="trade_opened", trade_id=tid,
                     message=f"#{number} {sym} {side} {rd.units:g} @ {fill:.5f} SL {sl:.5f} TP {tp:.5f}"))
        return "filled"

    def _snapshot(self, db: Session, now: datetime) -> None:
        a = self.broker.get_account()
        db.add(EquitySnapshot(account_id=self.account_id, ts=now, balance=a["balance"], equity=a["equity"], peak_equity=self.peak))
        db.commit()
        self.last_snapshot = now.timestamp()

    def open_risk_pct(self) -> float:
        if self.broker is None:
            return 0.0
        eq = self.broker.get_account()["equity"]
        r = sum(abs(p["entry"] - p["stop_loss"]) * p["units"] * self.broker._rate(p["symbol"]) for p in self.broker.get_positions())
        return r / eq * 100 if eq > 0 else 0.0


service: TradingService | None = None


def get_service() -> TradingService | None:
    return service


async def _loop(svc: TradingService) -> None:
    while True:
        try:
            await asyncio.to_thread(svc.step)
            svc.last_error = None
        except Exception as e:  # noqa: BLE001 - keep the loop alive; the error is surfaced via /api/trading/overview
            svc.last_error = f"{type(e).__name__}: {e}"[:300]
            log.exception("trading step failed")
        await asyncio.sleep(STEP_SECONDS)


def start(sf: sessionmaker) -> asyncio.Task:
    global service
    service = TradingService(sf)
    return asyncio.create_task(_loop(service))
