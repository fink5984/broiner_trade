import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base

c = TestClient(app)


@pytest.fixture(autouse=True)
def empty_db():
    """Isolated empty DB: these tests must never read the real (live) database."""
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    S = sessionmaker(eng, expire_on_commit=False)

    def override():
        with S() as s:
            yield s
    prev = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override
    yield
    if prev:
        app.dependency_overrides[get_session] = prev
    else:
        app.dependency_overrides.pop(get_session, None)


def test_status_is_paper_and_live_disabled():
    s = c.get("/api/status").json()
    assert s["mode"] == "PAPER" and s["live_trading_enabled"] is False


def test_markets_flagged_demo():
    r = c.get("/api/markets").json()
    assert r["items"] and all(i["demo"] for i in r["items"])


def test_market_detail_and_unknown():
    d = c.get("/api/markets/USDILS?tf=1h").json()
    assert d["demo"] and d["candles"] and d["decision"]["action"] == "NO_TRADE"
    assert c.get("/api/markets/FOO").status_code == 404


def test_backtest_endpoint_and_validation():
    r = c.post("/api/backtest", json={"candles": 600}).json()
    assert r["demo"] and "max_drawdown_pct" in r["metrics"] and r["equity"]
    assert c.post("/api/backtest", json={"ema_fast": 60, "ema_slow": 50}).status_code == 422
    assert c.post("/api/backtest", json={"risk_per_trade_pct": 5}).status_code == 422
