import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db import get_session
from app.models import AuditLog, Base

eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
Base.metadata.create_all(eng)
S = sessionmaker(eng, expire_on_commit=False)


def override():
    with S() as s:
        yield s


main.app.dependency_overrides[get_session] = override
main.cfg_settings.admin_token = "t0ken"
c = TestClient(main.app)
H = {"X-Admin-Token": "t0ken"}


def test_defaults_then_versioning_and_audit():
    assert c.get("/api/settings/risk").json()["is_default"] is True
    body = c.get("/api/settings/risk").json()["value"] | {"risk_per_trade_pct": 0.2}
    r = c.put("/api/settings/risk", json=body, headers=H).json()
    assert r["version"] == 1 and r["effective"] == "immediate"
    body["risk_per_trade_pct"] = 0.1
    assert c.put("/api/settings/risk", json=body, headers=H).json()["version"] == 2
    h = c.get("/api/settings/risk/history").json()
    assert [x["version"] for x in h] == [2, 1] and h[1]["current"] is False  # history preserved
    with S() as s:
        assert s.query(AuditLog).filter_by(action="settings.update.risk").count() == 2


def test_unchanged_does_not_bump_version():
    v = c.get("/api/settings/alerts").json()["value"]
    c.put("/api/settings/alerts", json=v | {"email_enabled": True}, headers=H)
    r = c.put("/api/settings/alerts", json=v | {"email_enabled": True}, headers=H).json()
    assert r.get("unchanged") and r["version"] == 1


def test_requires_admin_token():
    assert c.put("/api/settings/risk", json={}).status_code == 401
    assert c.put("/api/settings/risk", json={}, headers={"X-Admin-Token": "bad"}).status_code == 401


@pytest.mark.parametrize("key,patch", [("risk", {"risk_per_trade_pct": 5}), ("risk", {"dd_emergency_pct": 50}),
                                       ("risk", {"dd_reduce_pct": 14, "dd_block_pct": 12}),
                                       ("decision", {"w_technical": 60}), ("general", {"trading_mode": "LIVE"})])
def test_invalid_settings_rejected(key, patch):
    v = c.get(f"/api/settings/{key}").json()["value"] | patch
    assert c.put(f"/api/settings/{key}", json=v, headers=H).status_code == 422


def test_weights_sum_ok_and_unknown_key():
    v = c.get("/api/settings/decision").json()["value"] | {"w_technical": 40, "w_news": 30, "w_macro": 30}
    assert c.put("/api/settings/decision", json=v, headers=H).status_code == 200
    assert c.get("/api/settings/nope").status_code == 404
