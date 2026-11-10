from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app import market_data as md
from app.db import get_session
from app.models import (Alert, AuditLog, Base, BrokerOrder, Instrument, Position, RiskCheck, Trade, TradingDecision)
from app.trading import service as svc_mod
from app.trading.service import TradingService, get_state, set_state

NOW = datetime(2026, 11, 10, 12, 7, tzinfo=timezone.utc)
LAST_BAR = datetime(2026, 11, 10, 11, 45, tzinfo=timezone.utc)  # closes 12:00, inside the 10 minute freshness window


def uptrend(n=300):
    rng = np.random.default_rng(3)
    idx = pd.date_range(end=LAST_BAR, periods=n, freq="15min")
    close = 3.0 + 0.004 * np.arange(n) + rng.normal(0, 0.002, n)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + 0.001, "low": np.minimum(open_, close) - 0.001,
                         "close": close}, index=idx)


def quote(mid, ts=NOW):
    return {"bid": mid - 0.0006, "ask": mid + 0.0006, "mid": mid, "spread": 0.0012, "ts": ts.isoformat(), "age_s": 1.0}


@pytest.fixture()
def env(monkeypatch):
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    S = sessionmaker(eng, expire_on_commit=False)
    with S() as s:
        s.add(Instrument(symbol="USDILS", base="USD", quote="ILS"))
        s.commit()
    df = uptrend()
    quotes = {"USDILS": quote(float(df.close.iloc[-1]))}
    monkeypatch.setattr(svc_mod, "utcnow", lambda: NOW)
    monkeypatch.setattr(md, "latest_quotes", lambda db, window_seconds=600: dict(quotes))
    monkeypatch.setattr(md, "live_candles", lambda db, sym, tf, limit=400, complete_only=True: df if sym == "USDILS" else None)
    return S, TradingService(S), quotes


def count(S, model):
    with S() as s:
        return len(s.scalars(select(model)).all())


def activate(S):
    with S() as s:
        set_state(s, "ACTIVE", "test")


def test_paused_by_default_never_opens(env):
    S, svc, _ = env
    svc.step()
    assert count(S, TradingDecision) == 0 and count(S, Trade) == 0
    with S() as s:
        assert get_state(s) == "PAUSED"


def test_active_opens_one_paper_trade_with_full_audit_trail_and_is_idempotent(env):
    S, svc, _ = env
    activate(S)
    svc.step()
    svc.step()
    with S() as s:
        t = s.scalars(select(Trade)).one()
        assert t.side == "BUY" and t.mode == "PAPER" and t.exit_time is None and t.number == 1
        assert t.stop_loss < t.entry_price < t.take_profit
        assert s.scalars(select(TradingDecision)).one().execution_status == "filled"
        assert s.scalars(select(RiskCheck)).one().allowed is True
        assert s.scalars(select(BrokerOrder)).one().status == "FILLED"
        assert s.scalars(select(Position)).one().is_open is True
        assert any(a.kind == "trade_opened" for a in s.scalars(select(Alert)))
    assert len(svc.broker.positions) == 1


def test_stop_loss_closes_and_persists_pnl(env):
    S, svc, quotes = env
    activate(S)
    svc.step()
    with S() as s:
        sl = s.scalars(select(Trade)).one().stop_loss
    quotes["USDILS"] = quote(sl - 0.001, NOW + timedelta(seconds=10))
    svc.step()
    with S() as s:
        t = s.scalars(select(Trade)).one()
        assert t.exit_reason == "STOP_LOSS" and t.net_pnl < 0 and t.exit_price <= sl
        assert s.scalars(select(Position)).one().is_open is False
    assert not svc.broker.positions and svc.broker.balance == pytest.approx(10_000 + t.net_pnl)


def test_restart_restores_open_position_and_balance(env):
    S, svc, _ = env
    activate(S)
    svc.step()
    fresh = TradingService(S)
    fresh.startup()
    assert set(fresh.broker.positions) == set(svc.broker.positions)
    assert fresh.broker.balance == pytest.approx(svc.broker.balance)


def test_emergency_stop_closes_everything_and_latches(env):
    S, svc, _ = env
    activate(S)
    svc.step()
    with S() as s:
        set_state(s, "EMERGENCY_STOP", "test")
    svc.step()
    assert not svc.broker.positions
    with S() as s:
        assert s.scalars(select(Trade)).one().exit_reason == "EMERGENCY_STOP"
        assert get_state(s) == "EMERGENCY_STOP"
        assert s.scalars(select(AuditLog).where(AuditLog.action == "system.state.emergency_stop")).first()


def test_system_controls_api(env):
    S, svc, _ = env

    def override():
        with S() as s:
            yield s
    prev = main.app.dependency_overrides.get(get_session)
    main.app.dependency_overrides[get_session] = override
    main.cfg_settings.admin_token = "t0ken"
    H = {"X-Admin-Token": "t0ken"}
    try:
        c = TestClient(main.app)
        assert c.post("/api/system/start").status_code == 401
        assert c.post("/api/system/pause", headers=H).status_code == 409  # already paused
        assert c.post("/api/system/start", headers=H).json() == {"state": "ACTIVE"}
        assert c.get("/api/status").json()["system"] == "ACTIVE"
        assert c.post("/api/system/emergency-stop", headers=H).json() == {"state": "EMERGENCY_STOP"}
        assert c.post("/api/system/start", headers=H).status_code == 409  # latched: needs explicit reset
        assert c.post("/api/system/reset", headers=H).json() == {"state": "PAUSED"}
        o = c.get("/api/trading/overview").json()
        assert (o["state"], o["initial_capital"], o["equity"], o["mode"]) == ("PAUSED", 10_000, 10_000, "PAPER")
        assert c.get("/api/trades").json() == {"items": []}
    finally:
        if prev:
            main.app.dependency_overrides[get_session] = prev
        else:
            main.app.dependency_overrides.pop(get_session, None)
