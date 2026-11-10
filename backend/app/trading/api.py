"""Trading API: overview, trades, decisions, alerts and admin-gated system controls (paper only)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import settings_service as ss
from ..db import get_session
from ..models import (Alert, BrokerAccount, EquitySnapshot, Instrument, Position, Strategy, StrategyVersion, Trade,
                      TradingDecision)
from ..risk.engine import drawdown_pct
from ..security import require_admin
from .service import get_service, get_state, period_start_equity, period_starts, set_state, utcnow, _utc

router = APIRouter(prefix="/api")

# action -> (target state, states it may be applied from)
ACTIONS = {"start": ("ACTIVE", {"PAUSED"}), "pause": ("PAUSED", {"ACTIVE"}),
           "emergency-stop": ("EMERGENCY_STOP", {"ACTIVE", "PAUSED"}), "reset": ("PAUSED", {"EMERGENCY_STOP"})}


def _iso(t):
    t = _utc(t)
    return t.isoformat() if t else None


@router.get("/trading/overview")
def overview(db: Session = Depends(get_session)):
    g = ss.get_current(db, "general")["value"]
    initial, ccy = float(g["initial_capital"]), g["account_currency"]
    svc = get_service()
    acct = db.scalars(select(BrokerAccount).where(BrokerAccount.broker == "paper")).first()
    nets = list(db.scalars(select(Trade.net_pnl).where(Trade.exit_time.is_not(None), Trade.mode == "PAPER")))
    realized = sum(nets)
    a = None
    if svc and svc.broker:
        try:
            a = svc.broker.get_account()
        except Exception:  # missing FX conversion quote right after a restart
            a = None
    if a is None:
        a = {"balance": initial + realized, "equity": initial + realized, "unrealized": 0.0, "margin_used": 0.0}
    peak = max(svc.peak if svc else initial, a["equity"])
    pnl = {k: a["equity"] - period_start_equity(db, acct.id if acct else None, v, initial) for k, v in period_starts(utcnow()).items()}
    return {"state": get_state(db), "service_running": bool(svc and svc.broker), "last_step_at": _iso(svc.last_step_at) if svc else None,
            "last_error": svc.last_error if svc else None, "currency": ccy, "initial_capital": initial,
            "balance": a["balance"], "equity": a["equity"], "unrealized": a["unrealized"], "realized": realized,
            "margin_used": a["margin_used"], "peak_equity": peak, "drawdown_pct": drawdown_pct(a["equity"], peak),
            "pnl": pnl | {"total": a["equity"] - initial}, "open_trades": db.scalar(select(func.count()).select_from(Position).where(Position.is_open)),
            "closed_trades": len(nets), "win_rate": (sum(1 for x in nets if x > 0) / len(nets) * 100) if nets else None,
            "open_risk_pct": svc.open_risk_pct() if svc else 0.0, "mode": "PAPER", "engine_mode": "technical_only"}


@router.get("/trading/live")
def live_equity():
    """Cheap in-memory account snapshot for 1-second UI polling (no DB access)."""
    svc = get_service()
    try:
        a = svc.broker.get_account() if svc and svc.broker else None
    except Exception:  # conversion quote not available yet right after a restart
        a = None
    if a is None:
        return {"ts": utcnow().timestamp(), "equity": None, "balance": None, "unrealized": None}
    return {"ts": utcnow().timestamp(), "equity": a["equity"], "balance": a["balance"], "unrealized": a["unrealized"]}


@router.get("/trading/equity")
def equity_curve(limit: int = Query(1500, ge=10, le=5000), db: Session = Depends(get_session)):
    rows = db.execute(select(EquitySnapshot.ts, EquitySnapshot.equity).order_by(EquitySnapshot.ts.desc()).limit(limit)).all()
    pts = {int(_utc(t).timestamp()): e for t, e in reversed(rows)}  # chart needs strictly increasing, unique times
    return {"items": [{"time": t, "value": v} for t, v in pts.items()]}


@router.get("/trades")
def trades(status: str = Query("all", pattern="^(open|closed|all)$"), limit: int = Query(100, ge=1, le=500),
           db: Session = Depends(get_session)):
    q = (select(Trade, Instrument.symbol, Strategy.name).join(Instrument, Instrument.id == Trade.instrument_id)
         .join(StrategyVersion, StrategyVersion.id == Trade.strategy_version_id)
         .join(Strategy, Strategy.id == StrategyVersion.strategy_id).order_by(Trade.number.desc()).limit(limit))
    if status == "open":
        q = q.where(Trade.exit_time.is_(None))
    elif status == "closed":
        q = q.where(Trade.exit_time.is_not(None))
    svc = get_service()
    live, quotes = {}, {}
    if svc and svc.broker:
        try:
            live = {p["id"]: p for p in svc.broker.get_positions()}
            quotes = svc.broker.quotes
        except Exception:
            live, quotes = {}, {}
    out = []
    for t, sym, strat in db.execute(q):
        row = {"number": t.number, "symbol": sym, "strategy": strat, "side": t.side, "units": t.units,
               "entry_time": _iso(t.entry_time), "entry_price": t.entry_price, "stop_loss": t.stop_loss,
               "take_profit": t.take_profit, "exit_time": _iso(t.exit_time), "exit_price": t.exit_price, "fees": t.fees,
               "spread_cost": t.spread_cost, "net_pnl": t.net_pnl, "entry_reason": t.entry_reason, "exit_reason": t.exit_reason,
               "current_price": None, "unrealized": None}
        p = live.get(t.position_id.hex) if t.position_id else None
        if p and t.exit_time is None:
            qt = quotes.get(sym)
            row["current_price"] = (qt.bid if t.side == "BUY" else qt.ask) if qt else None
            row["unrealized"] = p["unrealized"]
        out.append(row)
    return {"items": out}


@router.get("/decisions")
def decisions(limit: int = Query(30, ge=1, le=200), symbol: str | None = None, db: Session = Depends(get_session)):
    q = select(TradingDecision, Instrument.symbol).join(Instrument, Instrument.id == TradingDecision.instrument_id)
    if symbol:
        q = q.where(Instrument.symbol == symbol)
    rows = db.execute(q.order_by(TradingDecision.ts.desc()).limit(limit))
    return {"items": [{"ts": _iso(d.ts), "symbol": s, "action": d.action, "score": d.score, "reasons": d.reason.get("reasons", []),
                       "blockers": d.reason.get("blockers", []), "execution_status": d.execution_status} for d, s in rows]}


def latest_decision(db: Session, symbol: str, max_age_minutes: int = 30) -> dict | None:
    """Most recent stored decision for the symbol, ignored when older than a couple of bars."""
    try:
        r = db.execute(select(TradingDecision).join(Instrument, Instrument.id == TradingDecision.instrument_id)
                       .where(Instrument.symbol == symbol).order_by(TradingDecision.ts.desc()).limit(1)).scalars().first()
    except Exception:
        return None
    if r is None or utcnow() - _utc(r.ts) > timedelta(minutes=max_age_minutes):
        return None
    return {"action": r.action, "reasons": r.reason.get("reasons", []), "blockers": r.reason.get("blockers", [])}


@router.get("/alerts")
def alerts(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_session)):
    rows = db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(limit))
    return {"items": [{"ts": _iso(a.created_at), "severity": a.severity, "kind": a.kind, "message": a.message} for a in rows]}


@router.post("/system/{action}")
def system_action(action: str, request: Request, _: str = Depends(require_admin), db: Session = Depends(get_session)):
    if action not in ACTIONS:
        raise HTTPException(404, "unknown action")
    target, allowed = ACTIONS[action]
    cur = get_state(db)
    if cur not in allowed:
        raise HTTPException(409, f"לא ניתן לבצע '{action}' כשהמערכת במצב {cur}")
    set_state(db, target, f"manual:{action}", request.client.host if request.client else None)
    if target == "EMERGENCY_STOP":
        db.add(Alert(severity="critical", kind="emergency_stop", message="עצירת חירום ידנית"))
        db.commit()
    return {"state": target}
