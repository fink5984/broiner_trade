"""Shared helpers for keyless collectors: source bookkeeping, dedupe, currency tagging, run logging."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CentralBankEvent, DataSource, IngestionRun, NewsArticle

USER_AGENT = "broiner-trade/0.1 (research; paper trading)"
TIMEOUT = httpx.Timeout(20.0)

# Title keywords -> currency/commodity codes. Matching is on the headline only; nothing is inferred beyond it.
_TAGS = {
    "USD": r"\b(dollar|usd|fed|federal reserve|fomc|powell|treasury|u\.s\.|us economy)\b",
    "EUR": r"\b(euro|eur|ecb|eurozone|lagarde|european central bank)\b",
    "GBP": r"\b(pound|sterling|gbp|bank of england|boe|bailey)\b",
    "ILS": r"\b(shekel|ils|bank of israel|israel)\b",
    "XAU": r"\b(gold|xau|bullion)\b",
}
_TAG_RE = {k: re.compile(v, re.I) for k, v in _TAGS.items()}


def tag_currencies(text: str) -> list[str]:
    return [k for k, rx in _TAG_RE.items() if rx.search(text)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def url_hash(url: str) -> str:
    p = urlsplit(url.strip())
    return hashlib.sha256(urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query, "")).encode()).hexdigest()


@dataclass(frozen=True)
class RawArticle:
    url: str
    title: str
    published_at: datetime


@dataclass(frozen=True)
class RawBankEvent:
    bank: str
    kind: str
    external_id: str
    title: str
    url: str | None
    event_time: datetime


def ensure_source(db: Session, name: str, kind: str, url: str, poll_seconds: int) -> DataSource:
    s = db.scalars(select(DataSource).where(DataSource.name == name)).first()
    if s is None:
        s = DataSource(name=name, kind=kind, url=url, poll_seconds=poll_seconds, enabled=True, config={}, status="starting")
        db.add(s)
        db.commit()
    return s


def save_articles(db: Session, source: DataSource, items: list[RawArticle]) -> int:
    if not items:
        return 0
    by_hash = {url_hash(i.url): i for i in items if i.url and i.title}
    existing = set(db.scalars(select(NewsArticle.url_hash).where(NewsArticle.url_hash.in_(list(by_hash)))))
    new = 0
    for h, i in by_hash.items():
        if h in existing:
            continue
        db.add(NewsArticle(source_id=source.id, url=i.url, url_hash=h, title=i.title.strip(), body=None,
                           published_at=i.published_at, countries=[], currencies=tag_currencies(i.title)))
        new += 1
    db.commit()
    return new


def save_bank_events(db: Session, items: list[RawBankEvent]) -> int:
    if not items:
        return 0
    banks = {i.bank for i in items}
    existing = set(db.execute(select(CentralBankEvent.bank, CentralBankEvent.external_id).where(CentralBankEvent.bank.in_(banks))).all())
    new, seen = 0, set()
    for i in items:
        key = (i.bank, i.external_id)
        if key in existing or key in seen:
            continue
        seen.add(key)
        db.add(CentralBankEvent(bank=i.bank, kind=i.kind, external_id=i.external_id, title=i.title.strip(), text=None,
                                url=i.url, event_time=i.event_time))
        new += 1
    db.commit()
    return new


def record_run(db: Session, source: DataSource, started: datetime, received: int, new: int, error: str | None) -> None:
    """Writes the run log and updates source status. last_success_at moves only on success."""
    db.add(IngestionRun(source_id=source.id, started_at=started, finished_at=utcnow(), items_received=received,
                        items_new=new, error=error))
    source.status = "error" if error else "connected"
    if not error:
        source.last_success_at = utcnow()
    db.commit()
