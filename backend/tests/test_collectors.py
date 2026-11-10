from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.collectors import feeds, gdelt, runner
from app.collectors.common import tag_currencies, url_hash
from app.db import get_session
from app.models import Base, CentralBankEvent, DataSource, IngestionRun, NewsArticle

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Federal Reserve issues FOMC statement</title><link>https://x.test/a</link><guid>g-a</guid><pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item>
<item><title>Gold rallies as dollar slips</title><link>https://x.test/b/</link><guid>g-b</guid><pubDate>Tue, 10 Nov 2026 09:00:00 GMT</pubDate></item>
<item><title>No date item</title><link>https://x.test/c</link></item>
</channel></rss>"""


@pytest.fixture()
def sf():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(eng, expire_on_commit=False)


def test_url_hash_ignores_case_and_trailing_slash():
    assert url_hash("HTTPS://X.test/b/") == url_hash("https://x.test/b")


def test_tagging_uses_headline_only():
    assert tag_currencies("Gold rallies as dollar slips") == ["USD", "XAU"]
    assert tag_currencies("Weather update") == []


def test_rss_items_without_date_are_dropped():
    f = feeds.Feed("n", "news", "u")
    items = feeds.parse_articles(f, RSS)
    assert [i.url for i in items] == ["https://x.test/a", "https://x.test/b/"]
    assert all(i.published_at.tzinfo == timezone.utc for i in items)


def test_bank_event_classification():
    f = feeds.Feed("Fed", "central_bank", "u", "FED", "press")
    ev = feeds.parse_bank_events(f, RSS)
    assert ev[0].kind == "rate_decision" and ev[0].bank == "FED" and ev[1].kind == "press"


def test_news_job_is_idempotent_and_logs_runs(sf, monkeypatch):
    feed = feeds.Feed("Test News", "news", "https://x.test/rss")
    monkeypatch.setattr(runner, "fetch_feed", lambda f: RSS)
    job = runner._feed_job(feed)
    runner.run_job(sf, job)
    runner.run_job(sf, job)
    with sf() as db:
        assert db.query(NewsArticle).count() == 2
        runs = db.scalars(select(IngestionRun).order_by(IngestionRun.started_at)).all()
        assert [(r.items_received, r.items_new, r.error) for r in runs] == [(2, 2, None), (2, 0, None)]
        assert db.scalars(select(DataSource)).one().status == "connected"


def test_central_bank_job_dedupes(sf, monkeypatch):
    feed = feeds.Feed("Fed", "central_bank", "https://x.test/rss", "FED", "press")
    monkeypatch.setattr(runner, "fetch_feed", lambda f: RSS)
    job = runner._feed_job(feed)
    runner.run_job(sf, job)
    runner.run_job(sf, job)
    with sf() as db:
        assert db.query(CentralBankEvent).count() == 2


def test_failing_source_is_recorded_not_raised(sf, monkeypatch):
    def boom(f):
        raise RuntimeError("HTTP 429")
    monkeypatch.setattr(runner, "fetch_feed", boom)
    runner.run_job(sf, runner._feed_job(feeds.Feed("Bad", "news", "u")))
    with sf() as db:
        s = db.scalars(select(DataSource)).one()
        assert s.status == "error" and s.last_success_at is None
        assert "429" in db.scalars(select(IngestionRun)).one().error


def test_gdelt_parse():
    p = {"articles": [{"url": "https://g.test/1", "title": "Inflation cools", "seendate": "20261110T120000Z"},
                      {"url": "https://g.test/2", "title": "bad date", "seendate": "nope"}]}
    items = gdelt.parse(p)
    assert len(items) == 1 and items[0].published_at.hour == 12


def test_api_endpoints_and_status(sf, monkeypatch):
    monkeypatch.setattr(runner, "fetch_feed", lambda f: RSS)
    runner.run_job(sf, runner._feed_job(feeds.Feed("Test News", "news", "https://x.test/rss")))
    runner.run_job(sf, runner._feed_job(feeds.Feed("Fed", "central_bank", "https://x.test/f", "FED", "press")))

    def override():
        with sf() as s:
            yield s
    prev = main.app.dependency_overrides.get(get_session)
    main.app.dependency_overrides[get_session] = override
    try:
        c = TestClient(main.app)
        news = c.get("/api/news").json()
        assert news["total"] == 2 and news["items"][0]["title"].startswith("Gold")
        assert [i["title"] for i in c.get("/api/news?currency=XAU").json()["items"]] == ["Gold rallies as dollar slips"]
        assert len(c.get("/api/central-bank").json()["items"]) == 2
        srcs = {s["name"]: s for s in c.get("/api/sources").json()["items"]}
        assert srcs["Test News"]["status"] == "connected" and srcs["Test News"]["last_run"]["new"] == 2
        assert c.get("/api/status").json()["news"] == "connected"
    finally:
        if prev:
            main.app.dependency_overrides[get_session] = prev
        else:
            main.app.dependency_overrides.pop(get_session, None)
