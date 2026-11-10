"""Event-driven backtester without look-ahead.

Rules that prevent leakage:
* Decision at bar i uses candles[:i+1] only (closed candles).
* Entry fills at the OPEN of bar i+1 (plus spread/slippage), never at the signal bar's close.
* Exogenous signals (news/macro) are read through `available_at <= decision time`.
* If SL and TP are both inside one bar, SL is assumed first (conservative).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..engines import indicators as ind
from ..engines.decision import DecisionConfig, EngineSignal, decide
from ..engines.technical import TechnicalParams, analyze
from ..risk.engine import (AccountState, Instrument, OpenPosition, RiskLimits, TradeProposal, drawdown_pct,
                           evaluate)


@dataclass
class TimedSignal:
    """An exogenous signal with the time it BECAME KNOWN to the system (not event time)."""
    available_at: datetime
    score: float
    horizon_hours: float = 6.0
    ref: str = ""


@dataclass
class BacktestConfig:
    instrument: Instrument
    initial_capital: float = 10_000.0
    spread: float = 0.01                 # price units, applied symmetrically around mid
    slippage: float = 0.002
    commission_per_unit: float = 0.0
    swap_per_unit_day: float = 0.0       # financing cost per unit per day held, quote ccy
    quote_to_account: float = 1.0
    atr_sl_mult: float = 1.5
    rr: float = 2.0
    warmup: int = 120
    window: int = 400
    max_hold_hours: float = 24.0
    tech: TechnicalParams = field(default_factory=lambda: TechnicalParams(compute_levels=False))
    decision: DecisionConfig = field(default_factory=lambda: DecisionConfig(w_technical=100, w_news=0, w_macro=0,
                                                                            min_agreeing_engines=1, min_signal=0.4))
    risk: RiskLimits = field(default_factory=RiskLimits)
    news: list[TimedSignal] = field(default_factory=list)
    macro: list[TimedSignal] = field(default_factory=list)


@dataclass
class BtTrade:
    side: str
    entry_time: datetime
    entry: float
    units: float
    sl: float
    tp: float
    exit_time: datetime | None = None
    exit: float | None = None
    reason: str = ""
    gross: float = 0.0
    costs: float = 0.0
    net: float = 0.0


def _latest(signals: list[TimedSignal], now: datetime) -> EngineSignal | None:
    """Most recent signal known at `now`, decayed to zero over its horizon."""
    known = [s for s in signals if s.available_at <= now]
    if not known:
        return None
    s = max(known, key=lambda x: x.available_at)
    age_h = (now - s.available_at).total_seconds() / 3600
    if age_h >= s.horizon_hours:
        return None
    return EngineSignal("x", s.score * (1 - age_h / s.horizon_hours), s.available_at, True, [s.ref])


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig) -> dict:
    df = df.sort_index()
    if df.index.has_duplicates:
        raise ValueError("duplicate candle timestamps")
    inst, half = cfg.instrument, cfg.spread / 2
    cash = cfg.initial_capital
    peak = cash
    equity_curve: list[tuple[datetime, float]] = []
    trades: list[BtTrade] = []
    open_t: BtTrade | None = None
    pending: tuple[str, float, float] | None = None  # (side, sl_dist, tp_dist) decided at prev bar close
    rejected = 0

    idx = df.index
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    day_start_eq, day = cash, idx[0].date()
    week_start_eq, week = cash, idx[0].isocalendar()[1]

    for i in range(len(df)):
        t = idx[i]
        if t.date() != day:
            day, day_start_eq = t.date(), cash if open_t is None else equity_curve[-1][1]
        if t.isocalendar()[1] != week:
            week, week_start_eq = t.isocalendar()[1], cash if open_t is None else equity_curve[-1][1]

        # 1. fill pending entry at this bar's open
        if pending and open_t is None:
            side, sl_d, tp_d = pending
            fill = o[i] + half + cfg.slippage if side == "BUY" else o[i] - half - cfg.slippage
            sl = fill - sl_d if side == "BUY" else fill + sl_d
            tp = fill + tp_d if side == "BUY" else fill - tp_d
            eq_now = cash
            acc = AccountState(eq_now, max(peak, eq_now), day_start_eq, week_start_eq, [])
            prop = TradeProposal(inst, side, fill, sl, o[i] - half, o[i] + half, t.to_pydatetime(), cfg.quote_to_account,
                                 est_cost_per_unit_quote=cfg.commission_per_unit * 2, expected_slippage=cfg.slippage,
                                 take_profit=tp)
            rd = evaluate(prop, acc, cfg.risk, now=t.to_pydatetime())
            if rd.allowed:
                open_t = BtTrade(side, t.to_pydatetime(), fill, rd.units, sl, tp)
            else:
                rejected += 1
            pending = None

        # 2. manage open trade inside this bar (entry bar included)
        if open_t:
            ex, why = None, ""
            if open_t.side == "BUY":
                bid_low, bid_high = l[i] - half, h[i] - half
                if bid_low <= open_t.sl:
                    ex, why = min(open_t.sl, o[i] - half), "STOP_LOSS"
                elif bid_high >= open_t.tp:
                    ex, why = open_t.tp, "TAKE_PROFIT"
            else:
                ask_low, ask_high = l[i] + half, h[i] + half
                if ask_high >= open_t.sl:
                    ex, why = max(open_t.sl, o[i] + half), "STOP_LOSS"
                elif ask_low <= open_t.tp:
                    ex, why = open_t.tp, "TAKE_PROFIT"
            held = (t - pd.Timestamp(open_t.entry_time)).total_seconds() / 3600
            if ex is None and held >= cfg.max_hold_hours:
                ex = c[i] - half if open_t.side == "BUY" else c[i] + half
                why = "MAX_HOLD"
            if ex is not None:
                _close(open_t, t.to_pydatetime(), ex, why, cfg)
                cash += open_t.net
                trades.append(open_t)
                open_t = None

        # 3. mark-to-market equity at close of bar
        eq = cash
        if open_t:
            px = c[i] - half if open_t.side == "BUY" else c[i] + half
            d = (px - open_t.entry) if open_t.side == "BUY" else (open_t.entry - px)
            eq += d * open_t.units * cfg.quote_to_account
        peak = max(peak, eq)
        equity_curve.append((t.to_pydatetime(), eq))

        # 4. decision at close of bar i (uses data <= i only)
        if i < cfg.warmup or i == len(df) - 1 or pending:
            continue
        if drawdown_pct(eq, peak) >= cfg.risk.dd_emergency_pct:
            break
        win = df.iloc[max(0, i + 1 - cfg.window): i + 1]
        tr = analyze(win, cfg.tech)
        now = t.to_pydatetime()
        sigs = {"technical": EngineSignal("technical", tr.score, now)}
        for nm, src in (("news", cfg.news), ("macro", cfg.macro)):
            s = _latest(src, now)
            if s:
                s.name = nm
                sigs[nm] = s
        dec = decide(inst.symbol, now, sigs, cfg.decision, open_side=open_t.side if open_t else None,
                     bar_time=now)
        if open_t is None and dec.action in ("BUY", "SELL") and tr.atr > 0:
            pending = (dec.action, tr.atr * cfg.atr_sl_mult, tr.atr * cfg.atr_sl_mult * cfg.rr)
        elif open_t is not None and dec.action == "CLOSE":
            px = c[i] - half if open_t.side == "BUY" else c[i] + half
            _close(open_t, now, px, "SIGNAL_REVERSAL", cfg)
            cash += open_t.net
            trades.append(open_t)
            open_t = None

    if open_t:  # force close at last close
        px = c[-1] - half if open_t.side == "BUY" else c[-1] + half
        _close(open_t, idx[-1].to_pydatetime(), px, "END_OF_DATA", cfg)
        cash += open_t.net
        trades.append(open_t)
        equity_curve[-1] = (equity_curve[-1][0], cash)

    return {"trades": trades, "equity": equity_curve, "rejected_by_risk": rejected,
            "metrics": compute_metrics(trades, equity_curve, cfg.initial_capital)}


def _close(tr: BtTrade, t: datetime, px: float, why: str, cfg: BacktestConfig) -> None:
    d = (px - tr.entry) if tr.side == "BUY" else (tr.entry - px)
    days = max(0.0, (t - tr.entry_time).total_seconds() / 86400)
    tr.exit_time, tr.exit, tr.reason = t, px, why
    tr.gross = d * tr.units * cfg.quote_to_account
    tr.costs = (cfg.commission_per_unit * 2 + cfg.swap_per_unit_day * days) * tr.units * cfg.quote_to_account
    tr.net = tr.gross - tr.costs


def compute_metrics(trades: list[BtTrade], equity: list[tuple[datetime, float]], initial: float) -> dict:
    nets = np.array([t.net for t in trades], dtype=float)
    wins, losses = nets[nets > 0], nets[nets <= 0]
    final = equity[-1][1] if equity else initial
    eq = np.array([e for _, e in equity], dtype=float) if equity else np.array([initial])
    run_max = np.maximum.accumulate(eq)
    mdd = float(((run_max - eq) / run_max).max() * 100) if len(eq) else 0.0
    # Sharpe / Sortino on daily equity returns; reported only with >= 20 daily observations
    s = pd.Series([e for _, e in equity], index=pd.DatetimeIndex([t for t, _ in equity])) if equity else pd.Series(dtype=float)
    daily = s.resample("1D").last().dropna().pct_change().dropna() if len(s) else pd.Series(dtype=float)
    sharpe = sortino = None
    if len(daily) >= 20 and daily.std() > 0:
        sharpe = float(daily.mean() / daily.std() * math.sqrt(252))
        dn = daily[daily < 0]
        if len(dn) > 1 and dn.std() > 0:
            sortino = float(daily.mean() / dn.std() * math.sqrt(252))
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())
    return {
        "net_return_pct": (final - initial) / initial * 100,
        "final_equity": final,
        "trades": len(trades),
        "win_rate": float(len(wins) / len(nets) * 100) if len(nets) else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else (None if gross_win == 0 else float("inf")),
        "expectancy": float(nets.mean()) if len(nets) else 0.0,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "max_drawdown_pct": mdd,
        "sharpe": sharpe,
        "sortino": sortino,
        "total_costs": float(sum(t.costs for t in trades)),
    }


def walk_forward(df: pd.DataFrame, cfg: BacktestConfig, train_frac=0.5, val_frac=0.25) -> dict:
    """Chronological train / validation / test split (no shuffling). Each segment keeps a warm-up
    prefix of prior candles so indicators are valid but trades are only counted inside the segment."""
    n = len(df)
    a, b = int(n * train_frac), int(n * (train_frac + val_frac))
    out = {}
    for name, (s, e) in {"train": (0, a), "validation": (a, b), "test": (b, n)}.items():
        start = max(0, s - cfg.warmup)
        res = run_backtest(df.iloc[start:e], cfg)
        out[name] = res["metrics"] | {"candles": e - s}
    return out


def param_search(df: pd.DataFrame, base: BacktestConfig, grid: dict[str, list]) -> list[dict]:
    """Exhaustive grid over BacktestConfig fields (dotted names for tech.* / decision.*).
    Every trial is returned; ranking favours stability, not raw return."""
    import itertools
    import copy
    keys = list(grid)
    results = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        cfg = copy.deepcopy(base)
        for k, v in zip(keys, combo):
            obj, _, attr = k.rpartition(".")
            tgt = cfg
            for part in filter(None, obj.split(".")):
                tgt = getattr(tgt, part)
            setattr(tgt, attr, v)
        wf = walk_forward(df, cfg)
        results.append({"params": dict(zip(keys, combo)), "walk_forward": wf, "score": stability_score(wf)})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def stability_score(wf: dict) -> float:
    """Penalise overfitting: require positive expectancy in ALL segments, low drawdown, enough trades."""
    segs = [wf["train"], wf["validation"], wf["test"]]
    if any(s["trades"] < 3 for s in segs):
        return -1e9
    exp = [s["expectancy"] for s in segs]
    worst = min(exp)
    spread_pen = np.std(exp)
    dd = max(s["max_drawdown_pct"] for s in segs)
    if dd >= 15:
        return -1e6 - dd
    return float(worst - 0.5 * spread_pen - 0.5 * dd)
