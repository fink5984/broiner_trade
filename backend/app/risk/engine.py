"""Independent Risk Engine. No AI dependency. Hard safety limits cannot be overridden by strategies."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum


class SystemState(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    FAULT = "FAULT"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    base: str
    quote: str
    min_units: float = 1000.0
    unit_step: float = 1000.0
    max_spread: float = 0.05      # absolute price units
    max_slippage: float = 0.05


# Absolute ceilings a strategy/user setting may never exceed.
HARD_CEILINGS = {"risk_per_trade_pct": 1.0, "max_aggregate_risk_pct": 3.0, "dd_emergency_pct": 20.0,
                 "max_leverage": 30.0, "max_hold_hours": 72.0}


@dataclass
class RiskLimits:
    account_currency: str = "ILS"
    risk_per_trade_pct: float = 0.25
    max_aggregate_risk_pct: float = 0.75
    daily_loss_pct: float = 1.0
    weekly_loss_pct: float = 3.0
    dd_reduce_pct: float = 10.0
    dd_block_pct: float = 12.0
    dd_emergency_pct: float = 15.0
    max_hold_hours: float = 24.0
    max_open_positions: int = 2
    max_leverage: float = 10.0                 # notional / equity
    max_currency_exposure_pct: float = 300.0   # per-currency notional as % of equity
    max_data_age_seconds: float = 120.0
    reduce_factor: float = 0.5                 # risk multiplier when DD >= dd_reduce_pct

    def validate(self) -> None:
        for k, ceil in HARD_CEILINGS.items():
            if getattr(self, k) > ceil:
                raise ValueError(f"{k}={getattr(self, k)} exceeds hard ceiling {ceil}")
        if not (self.dd_reduce_pct <= self.dd_block_pct <= self.dd_emergency_pct):
            raise ValueError("drawdown thresholds must be ordered reduce <= block <= emergency")
        if self.risk_per_trade_pct <= 0 or self.max_open_positions < 1:
            raise ValueError("invalid risk limits")


@dataclass
class OpenPosition:
    symbol: str
    side: str
    units: float
    entry: float
    stop_loss: float
    quote_to_account: float
    opened_at: datetime

    def risk_amount(self) -> float:
        return abs(self.entry - self.stop_loss) * self.units * self.quote_to_account

    def notional_account(self) -> float:
        return self.entry * self.units * self.quote_to_account


@dataclass
class AccountState:
    equity: float                      # balance + unrealized
    peak_equity: float                 # already adjusted for deposits/withdrawals
    equity_day_start: float
    equity_week_start: float
    positions: list[OpenPosition] = field(default_factory=list)
    system_state: SystemState = SystemState.ACTIVE


@dataclass
class TradeProposal:
    instrument: Instrument
    side: str
    entry: float
    stop_loss: float
    bid: float
    ask: float
    quote_ts: datetime
    quote_to_account: float
    est_cost_per_unit_quote: float = 0.0
    expected_slippage: float = 0.0
    take_profit: float | None = None


@dataclass
class RiskDecision:
    allowed: bool
    units: float = 0.0
    risk_amount: float = 0.0
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    drawdown_pct: float = 0.0

    def as_dict(self):
        return asdict(self)


def drawdown_pct(equity: float, peak: float) -> float:
    return 0.0 if peak <= 0 else max(0.0, (peak - equity) / peak * 100.0)


def adjust_peak_for_cashflow(peak: float, cashflow: float) -> float:
    """Deposits raise the peak, withdrawals lower it, so cashflows never look like P&L."""
    return peak + cashflow


def evaluate_system_level(acc: AccountState, lim: RiskLimits) -> tuple[SystemState, list[str]]:
    dd = drawdown_pct(acc.equity, acc.peak_equity)
    if acc.system_state == SystemState.EMERGENCY_STOP:
        return SystemState.EMERGENCY_STOP, ["emergency stop latched; manual reset required"]
    if dd >= lim.dd_emergency_pct:
        return SystemState.EMERGENCY_STOP, [f"drawdown {dd:.2f}% >= emergency {lim.dd_emergency_pct}%"]
    return acc.system_state, []


def size_position(p: TradeProposal, lim: RiskLimits, equity: float, risk_mult: float = 1.0):
    """Return (units, risk_amount_in_account_ccy, reject_reason)."""
    stop_dist = abs(p.entry - p.stop_loss)
    if stop_dist <= 0:
        return 0.0, 0.0, "stop loss distance is zero"
    if (p.side == "BUY" and p.stop_loss >= p.entry) or (p.side == "SELL" and p.stop_loss <= p.entry):
        return 0.0, 0.0, "stop loss on wrong side of entry"
    loss_per_unit = (stop_dist + p.expected_slippage + p.est_cost_per_unit_quote) * p.quote_to_account
    budget = equity * lim.risk_per_trade_pct / 100.0 * risk_mult
    raw = budget / loss_per_unit
    inst = p.instrument
    units = math.floor(raw / inst.unit_step) * inst.unit_step
    if units < inst.min_units:
        min_risk = inst.min_units * loss_per_unit
        return 0.0, 0.0, f"minimum size {inst.min_units:g} units risks {min_risk:.2f} > allowed {budget:.2f}"
    return units, units * loss_per_unit, None


def evaluate(p: TradeProposal, acc: AccountState, lim: RiskLimits, now: datetime | None = None) -> RiskDecision:
    """Full pre-trade check. Any failed hard rule -> allowed=False (NO_TRADE)."""
    now = now or datetime.now(timezone.utc)
    lim.validate()
    dd = drawdown_pct(acc.equity, acc.peak_equity)
    d = RiskDecision(False, drawdown_pct=dd)
    st, why = evaluate_system_level(acc, lim)
    if st != SystemState.ACTIVE:
        d.reasons += why or [f"system state {st.value}"]
        return d
    if dd >= lim.dd_block_pct:
        d.reasons.append(f"drawdown {dd:.2f}% >= block threshold {lim.dd_block_pct}%")
        return d
    risk_mult = 1.0
    if dd >= lim.dd_reduce_pct:
        risk_mult = lim.reduce_factor
        d.flags.append(f"risk reduced x{risk_mult} (drawdown {dd:.2f}%)")
    day_loss = (acc.equity_day_start - acc.equity) / acc.equity_day_start * 100 if acc.equity_day_start > 0 else 0
    week_loss = (acc.equity_week_start - acc.equity) / acc.equity_week_start * 100 if acc.equity_week_start > 0 else 0
    if day_loss >= lim.daily_loss_pct:
        d.reasons.append(f"daily loss {day_loss:.2f}% >= {lim.daily_loss_pct}%")
    if week_loss >= lim.weekly_loss_pct:
        d.reasons.append(f"weekly loss {week_loss:.2f}% >= {lim.weekly_loss_pct}%")
    age = (now - p.quote_ts).total_seconds()
    if age > lim.max_data_age_seconds or age < -5:
        d.reasons.append(f"stale/invalid quote (age {age:.0f}s)")
    if p.bid <= 0 or p.ask <= 0 or p.ask < p.bid:
        d.reasons.append("invalid bid/ask")
    elif (p.ask - p.bid) > p.instrument.max_spread:
        d.reasons.append(f"spread {p.ask - p.bid:.5f} > max {p.instrument.max_spread}")
    if p.expected_slippage > p.instrument.max_slippage:
        d.reasons.append("expected slippage exceeds limit")
    if len(acc.positions) >= lim.max_open_positions:
        d.reasons.append(f"max open positions {lim.max_open_positions} reached")
    if any(x.symbol == p.instrument.symbol for x in acc.positions):
        d.reasons.append("position already open on symbol")
    if d.reasons:
        return d

    units, risk, rej = size_position(p, lim, acc.equity, risk_mult)
    if rej:
        d.reasons.append(rej)
        return d
    agg = sum(x.risk_amount() for x in acc.positions) + risk
    if agg > acc.equity * lim.max_aggregate_risk_pct / 100 + 1e-9:
        d.reasons.append(f"aggregate risk {agg:.2f} > limit {acc.equity * lim.max_aggregate_risk_pct / 100:.2f}")
        return d
    notional = p.entry * units * p.quote_to_account
    total_notional = sum(x.notional_account() for x in acc.positions) + notional
    if total_notional / acc.equity > lim.max_leverage:
        d.reasons.append(f"leverage {total_notional / acc.equity:.1f}x > {lim.max_leverage}x")
        return d
    for ccy in (p.instrument.base, p.instrument.quote):
        exp = notional + sum(x.notional_account() for x in acc.positions if ccy in x.symbol)
        if exp / acc.equity * 100 > lim.max_currency_exposure_pct:
            d.reasons.append(f"{ccy} exposure exceeds {lim.max_currency_exposure_pct}% of equity")
            return d
    d.allowed, d.units, d.risk_amount = True, units, risk
    return d


def positions_to_force_close(acc: AccountState, lim: RiskLimits, now: datetime | None = None):
    """Positions that must be closed: max-hold exceeded or emergency stop."""
    now = now or datetime.now(timezone.utc)
    out = []
    emergency = evaluate_system_level(acc, lim)[0] == SystemState.EMERGENCY_STOP
    for pos in acc.positions:
        if emergency:
            out.append((pos, "emergency stop"))
        elif now - pos.opened_at >= timedelta(hours=lim.max_hold_hours):
            out.append((pos, f"max hold {lim.max_hold_hours}h exceeded"))
    return out
