"""Public RSS collectors (no account/key): central banks -> central_bank_events, finance news -> news_articles."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx

from .common import RawArticle, RawBankEvent, TIMEOUT, USER_AGENT


@dataclass(frozen=True)
class Feed:
    name: str
    kind: str  # data_sources.kind: central_bank / news
    url: str
    bank: str | None = None
    default_event: str = "press"
    poll_seconds: int = 900


FEEDS: list[Feed] = [
    Feed("Fed — Monetary policy", "central_bank", "https://www.federalreserve.gov/feeds/press_monetary.xml", "FED", "rate_decision", 1800),
    Feed("Fed — Speeches", "central_bank", "https://www.federalreserve.gov/feeds/speeches.xml", "FED", "speech", 1800),
    Feed("ECB — Press", "central_bank", "https://www.ecb.europa.eu/rss/press.xml", "ECB", "press", 1800),
    Feed("BoE — News", "central_bank", "https://www.bankofengland.co.uk/rss/news", "BOE", "press", 1800),
    Feed("BoE — Speeches", "central_bank", "https://www.bankofengland.co.uk/rss/speeches", "BOE", "speech", 1800),
    Feed("BBC Business", "news", "https://feeds.bbci.co.uk/news/business/rss.xml", poll_seconds=600),
    Feed("Guardian Business", "news", "https://www.theguardian.com/business/rss", poll_seconds=600),
    Feed("CNBC Finance", "news", "https://www.cnbc.com/id/10000664/device/rss/rss.html", poll_seconds=600),
    Feed("FXStreet", "news", "https://www.fxstreet.com/rss/news", poll_seconds=600),
]

_KIND_HINTS = (("minutes", "minutes"), ("projection", "projection"), ("monetary policy decision", "rate_decision"),
               ("fomc statement", "rate_decision"), ("bank rate", "rate_decision"), ("speech", "speech"))


def classify_event(title: str, default: str) -> str:
    t = title.lower()
    return next((k for hint, k in _KIND_HINTS if hint in t), default)


def _when(entry) -> datetime | None:
    """Publication time as UTC, or None when the feed gives none (never invented)."""
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc) if st else None


def fetch_feed(feed: Feed, client: httpx.Client | None = None) -> bytes:
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        r = client.get(feed.url)
        r.raise_for_status()
        return r.content
    finally:
        if own:
            client.close()


def parse_articles(feed: Feed, content: bytes) -> list[RawArticle]:
    out = []
    for e in feedparser.parse(content).entries:
        t = _when(e)
        if t and e.get("link") and e.get("title"):
            out.append(RawArticle(e["link"], e["title"], t))
    return out


def parse_bank_events(feed: Feed, content: bytes) -> list[RawBankEvent]:
    out = []
    for e in feedparser.parse(content).entries:
        t = _when(e)
        link, title = e.get("link"), e.get("title")
        if t and title and (link or e.get("id")):
            out.append(RawBankEvent(feed.bank or "", classify_event(title, feed.default_event), e.get("id") or link, title, link, t))
    return out
