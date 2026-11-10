import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db import get_session
from app.models import Base, DataSource, Instrument, MarketCandle, MarketQuote


@pytest.fixture()
def client():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    S = sessionmaker(eng, expire_on_commit=False)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with S() as s:
        inst = Instrument(symbol="USDILS", base="USD", quote="ILS")
        s.add(inst); s.flush()
        s.add(DataSource(name="FXCM Demo", kind="market", status="connected", config={}))
        start = now - timedelta(minutes=15 * 400)
        for i in range(400):
            px = 3.15 + 0.0005 * (i % 20)
            s.add(MarketCandle(instrument_id=inst.id, timeframe="m15", source="fxcm-demo", open_time=start + timedelta(minutes=15 * i),
                               open=px, high=px + 0.001, low=px - 0.001, close=px + 0.0002, is_complete=True))
        # forming candle must never be used
        s.add(MarketCandle(instrument_id=inst.id, timeframe="m15", source="fxcm-demo", open_time=now,
                           open=9, high=9, low=9, close=9, is_complete=False))
        s.add(MarketQuote(instrument_id=inst.id, source="fxcm-demo", ts=now - timedelta(seconds=10), bid=3.1560, ask=3.1572))
        s.commit()

    def override():
        with S() as s:
            yield s
    prev = main.app.dependency_overrides.get(get_session)
    main.app.dependency_overrides[get_session] = override
    yield TestClient(main.app), S, inst_id_of(S)
    if prev:
        main.app.dependency_overrides[get_session] = prev
    else:
        main.app.dependency_overrides.pop(get_session, None)


def inst_id_of(S):
    with S() as s:
        return s.query(Instrument).filter_by(symbol="USDILS").one().id


def test_live_data_replaces_synthetic_only_where_available(client):
    c, _, _ = client
    items = {i["symbol"]: i for i in c.get("/api/markets").json()["items"]}
    u = items["USDILS"]
    assert u["demo"] is False and u["source"] == "fxcm-demo"
    assert u["bid"] == 3.1560 and u["ask"] == 3.1572 and u["spread"] == pytest.approx(0.0012)
    assert u["price"] == 3.1560 and u["stale"] is False  # displayed price = BID, same basis as candles
    assert items["GBPUSD"]["demo"] is True and items["GBPUSD"]["source"] == "synthetic"


def test_incomplete_candle_excluded_and_status_live(client):
    c, _, _ = client
    d = c.get("/api/markets/USDILS?tf=15m").json()
    # the forming candle is appended for display only (last), and never used by the analysis
    assert d["demo"] is False and d["forming"] is True and d["candles"][-1]["close"] == 9
    assert all(x["close"] != 9 for x in d["candles"][:-1])
    assert d["analysis"]["technical"]["atr"] < 1  # a 9.0 candle in the analysis would blow up ATR
    assert not any("אין מקור מחירים" in b for b in d["decision"]["blockers"])
    assert c.get("/api/status").json()["market_data"] == "fxcm_demo"


def test_stale_quote_flagged_and_blocks(client):
    c, S, iid = client
    with S() as s:
        s.query(MarketQuote).delete()
        s.add(MarketQuote(instrument_id=iid, source="fxcm-demo", ts=datetime.now(timezone.utc) - timedelta(minutes=30), bid=3.15, ask=3.16))
        s.commit()
    d = c.get("/api/markets/USDILS").json()
    assert d["quote"]["stale"] is True and any("ישן" in b for b in d["decision"]["blockers"])


def test_backtest_uses_live_candles_when_enough(client):
    c, _, _ = client
    r = c.post("/api/backtest", json={"candles": 300}).json()
    assert r["demo"] is False and r["source"] == "fxcm-demo" and r["candles_used"] == 300


def test_latest_quotes_picks_newest_and_skips_old(client):
    from app import market_data as md
    _, S, iid = client
    now = datetime.now(timezone.utc)
    with S() as s:
        s.add(MarketQuote(instrument_id=iid, source="fxcm-demo", ts=now - timedelta(seconds=2), bid=3.2000, ask=3.2010))
        s.commit()
        q = md.latest_quotes(s)
    assert q["USDILS"]["bid"] == 3.2000 and q["USDILS"]["age_s"] < 10
    with S() as s:
        s.query(MarketQuote).delete()
        s.add(MarketQuote(instrument_id=iid, source="fxcm-demo", ts=now - timedelta(hours=2), bid=3.1, ask=3.2))
        s.commit()
        assert md.latest_quotes(s) == {}
