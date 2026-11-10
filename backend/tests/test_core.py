from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.broker.base import OrderRequest, Quote, Side
from app.broker.paper import PaperBroker
from app.engines import indicators as ind
from app.engines.technical import analyze
from app.risk.engine import (AccountState, Instrument, OpenPosition, RiskLimits, SystemState, TradeProposal,
                             drawdown_pct, evaluate, positions_to_force_close, size_position)

NOW = datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc)
USDILS = Instrument("USDILS", "USD", "ILS", min_units=1000, unit_step=1000, max_spread=0.05)


def candles(n=300, seed=1, drift=0.0, start=3.6):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="15min", tz="UTC")
    close = start + np.cumsum(rng.normal(drift, 0.003, n))
    open_ = np.r_[close[0], close[:-1]]
    hi = np.maximum(open_, close) + rng.uniform(0, 0.002, n)
    lo = np.minimum(open_, close) - rng.uniform(0, 0.002, n)
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close}, index=idx)


# ---------- indicators ----------
def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 100, dtype=float))
    assert ind.rsi(up).dropna().iloc[-1] == 100.0
    assert 0 <= ind.rsi(candles()["close"]).dropna().min() <= 100


def test_ema_sma_known_values():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert ind.sma(s, 3).iloc[-1] == pytest.approx(4.0)
    assert ind.ema(s, 3).iloc[-1] == pytest.approx(4.0625, abs=1e-9)


def test_indicators_have_no_lookahead():
    df = candles()
    full = ind.rsi(df["close"]); part = ind.rsi(df["close"].iloc[:200])
    assert full.iloc[199] == pytest.approx(part.iloc[199])
    f = ind.atr(df); p = ind.atr(df.iloc[:200])
    assert f.iloc[199] == pytest.approx(p.iloc[199])
    m1 = ind.macd(df["close"])["hist"]; m2 = ind.macd(df["close"].iloc[:200])["hist"]
    assert m1.iloc[199] == pytest.approx(m2.iloc[199])


def test_swing_pivots_confirmed_only_after_right_bars():
    df = candles()
    ph_full, _ = ind.swing_levels(df)
    ph_cut, _ = ind.swing_levels(df.iloc[:150])
    pd.testing.assert_series_equal(ph_full.iloc[:150], ph_cut, check_names=False)


def test_resample_drops_incomplete_bucket():
    df = candles(n=10)  # 2.5 hours of 15m data -> last hour bucket incomplete
    out = ind.resample_candles(df, "1h")
    assert len(out) == 2
    assert out.iloc[0]["open"] == df.iloc[0]["open"]
    assert out.iloc[0]["high"] == df.iloc[:4]["high"].max()


def test_gap_detection_ignores_weekend():
    idx = pd.DatetimeIndex(pd.to_datetime(["2026-01-09 21:45", "2026-01-11 22:00", "2026-01-11 22:15", "2026-01-11 23:00"], utc=True))
    gaps = ind.find_gaps(idx, pd.Timedelta("15min"))
    assert len(gaps) == 1 and gaps[0][0] == idx[2]


def test_breakout_detected():
    df = candles(100, drift=0)
    rng_hi = df["high"].iloc[-21:-1].max()
    df.iloc[-1, df.columns.get_loc("close")] = rng_hi + 0.05
    df.iloc[-1, df.columns.get_loc("high")] = rng_hi + 0.06
    b = ind.detect_breakout(df)
    assert b and b["direction"] == "up"


def test_technical_trend_and_insufficient_data():
    up = analyze(candles(300, drift=0.002))
    assert up.direction == "BUY"
    down = analyze(candles(300, drift=-0.002))
    assert down.direction == "SELL"
    short = analyze(candles(10))
    assert short.direction == "NEUTRAL" and "insufficient" in short.explanation[0]


def test_technical_reproducible():
    df = candles(300, seed=5)
    assert analyze(df).as_dict() == analyze(df).as_dict()


# ---------- risk ----------
def proposal(entry=3.6, sl=3.58, bid=3.5995, ask=3.6005, side="BUY", ts=NOW, **kw):
    return TradeProposal(USDILS, side, entry, sl, bid, ask, ts, quote_to_account=1.0, **kw)


def acct(equity=10_000, peak=10_000, **kw):
    return AccountState(equity, peak, kw.pop("day", equity), kw.pop("week", equity), **kw)


def test_position_sizing_matches_risk_budget():
    # 25 ILS budget, 0.02 stop -> 1250 units -> floors to 1000 (step)
    units, risk, rej = size_position(proposal(), RiskLimits(), 10_000)
    assert rej is None and units == 1000 and risk == pytest.approx(20.0)
    assert risk <= 25


def test_min_size_exceeding_risk_returns_no_trade():
    d = evaluate(proposal(sl=3.40), acct(), RiskLimits(), NOW)  # 0.2 stop -> 1000 units risks 200
    assert not d.allowed and "minimum size" in d.reasons[0]


def test_wrong_side_and_zero_stop():
    assert size_position(proposal(sl=3.7), RiskLimits(), 10_000)[2]
    assert size_position(proposal(sl=3.6), RiskLimits(), 10_000)[2]


def test_costs_and_slippage_reduce_size():
    big = size_position(proposal(sl=3.598), RiskLimits(), 10_000)[0]
    small = size_position(proposal(sl=3.598, expected_slippage=0.002, est_cost_per_unit_quote=0.001), RiskLimits(), 10_000)[0]
    assert small < big


def test_stale_quote_blocked():
    d = evaluate(proposal(ts=NOW - timedelta(minutes=10)), acct(), RiskLimits(), NOW)
    assert not d.allowed and any("stale" in r for r in d.reasons)


def test_spread_limit():
    d = evaluate(proposal(bid=3.5, ask=3.7), acct(), RiskLimits(), NOW)
    assert not d.allowed and any("spread" in r for r in d.reasons)


def test_daily_and_weekly_limits():
    assert not evaluate(proposal(), acct(equity=9890, peak=10000, day=10000), RiskLimits(), NOW).allowed
    assert not evaluate(proposal(), acct(equity=9690, peak=10000, week=10000, day=9690), RiskLimits(), NOW).allowed


def test_drawdown_tiers():
    lim = RiskLimits()
    d10 = evaluate(proposal(sl=3.595), acct(equity=9000, peak=10000, day=9000, week=9000), lim, NOW)
    assert d10.allowed and d10.flags  # reduced, still allowed
    d12 = evaluate(proposal(), acct(equity=8800, peak=10000, day=8800, week=8800), lim, NOW)
    assert not d12.allowed
    assert drawdown_pct(8500, 10000) == pytest.approx(15)


def test_emergency_stop_at_15_percent_and_latch():
    lim = RiskLimits()
    a = acct(equity=8500, peak=10000, day=8500, week=8500,
             positions=[OpenPosition("USDILS", "BUY", 1000, 3.6, 3.58, 1.0, NOW)])
    assert not evaluate(proposal(), a, lim, NOW).allowed
    assert len(positions_to_force_close(a, lim, NOW)) == 1
    recovered = acct(equity=10000, peak=10000, system_state=SystemState.EMERGENCY_STOP)
    assert not evaluate(proposal(), recovered, lim, NOW).allowed  # latched until manual reset


def test_max_positions_aggregate_and_duplicate_symbol():
    lim = RiskLimits(max_open_positions=1)
    pos = OpenPosition("GBPILS", "BUY", 1000, 4.7, 4.68, 1.0, NOW)
    assert not evaluate(proposal(), acct(positions=[pos]), lim, NOW).allowed
    lim2 = RiskLimits(max_aggregate_risk_pct=0.25)
    pos2 = OpenPosition("GBPILS", "BUY", 1000, 4.7, 4.68, 1.0, NOW)
    d = evaluate(proposal(), acct(positions=[pos2]), lim2, NOW)
    assert not d.allowed and any("aggregate" in r for r in d.reasons)
    same = OpenPosition("USDILS", "BUY", 1000, 3.6, 3.58, 1.0, NOW)
    assert not evaluate(proposal(), acct(positions=[same]), RiskLimits(), NOW).allowed


def test_max_hold_force_close_and_hard_ceiling():
    old = OpenPosition("USDILS", "BUY", 1000, 3.6, 3.58, 1.0, NOW - timedelta(hours=25))
    assert positions_to_force_close(acct(positions=[old]), RiskLimits(), NOW)
    with pytest.raises(ValueError):
        RiskLimits(risk_per_trade_pct=5).validate()
    with pytest.raises(ValueError):
        RiskLimits(dd_emergency_pct=50).validate()


def test_leverage_limit():
    lim = RiskLimits(max_leverage=0.001)
    assert not evaluate(proposal(), acct(), lim, NOW).allowed


# ---------- paper broker ----------
def broker():
    b = PaperBroker(balance=10_000, commission_per_unit=0.0005, quote_to_account={"ILS": 1.0})
    b.connect()
    b.set_quote(Quote("USDILS", 3.5995, 3.6005, NOW))
    return b


def test_paper_open_close_pnl_with_spread_and_fees():
    b = broker()
    r = b.place_order(OrderRequest("o1", "USDILS", Side.BUY, 1000, 3.58, 3.64))
    assert r["status"] == "FILLED" and r["fill_price"] == 3.6005  # buys at ask
    b.set_quote(Quote("USDILS", 3.6195, 3.6205, NOW))
    rec = b.close_position(r["position_id"])
    assert rec["exit"] == 3.6195  # sells at bid
    assert rec["gross_pnl"] == pytest.approx(19.0)
    assert rec["net_pnl"] == pytest.approx(19.0 - 1.0)  # 2 x 0.5 commission
    assert b.balance == pytest.approx(10_000 + 18.0)


def test_paper_stop_loss_and_take_profit_trigger():
    b = broker()
    b.place_order(OrderRequest("o1", "USDILS", Side.BUY, 1000, 3.58, 3.64))
    hit = b.set_quote(Quote("USDILS", 3.5790, 3.5800, NOW))
    assert hit and hit[0]["exit_reason"] == "STOP_LOSS" and hit[0]["net_pnl"] < 0
    b2 = broker()
    b2.place_order(OrderRequest("s1", "USDILS", Side.SELL, 1000, 3.62, 3.56))
    hit = b2.set_quote(Quote("USDILS", 3.5590, 3.5600, NOW))
    assert hit[0]["exit_reason"] == "TAKE_PROFIT"


def test_paper_idempotent_orders():
    b = broker()
    a = b.place_order(OrderRequest("dup", "USDILS", Side.BUY, 1000, 3.58))
    c = b.place_order(OrderRequest("dup", "USDILS", Side.BUY, 1000, 3.58))
    assert c.get("duplicate") and len(b.positions) == 1 and a["position_id"] == c["position_id"]


def test_paper_rejections():
    b = broker()
    assert b.place_order(OrderRequest("a", "USDILS", Side.BUY, 10, 3.58))["status"] == "REJECTED"
    assert b.place_order(OrderRequest("b", "USDILS", Side.BUY, 1000, 3.7))["status"] == "REJECTED"
    assert b.place_order(OrderRequest("c", "USDILS", Side.BUY, 1000, None))["status"] == "REJECTED"
    assert b.place_order(OrderRequest("d", "USDILS", Side.BUY, 900_000, 3.5))["status"] == "REJECTED"  # margin


def test_paper_refuses_loosening_stop():
    b = broker()
    pid = b.place_order(OrderRequest("o", "USDILS", Side.BUY, 1000, 3.58))["position_id"]
    with pytest.raises(Exception):
        b.modify_order(pid, stop_loss=3.50)
    assert b.modify_order(pid, stop_loss=3.59)["stop_loss"] == 3.59


def test_paper_is_not_live():
    assert PaperBroker.is_live is False
