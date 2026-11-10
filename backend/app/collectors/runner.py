"""Background scheduler for keyless collectors. Each job runs in a worker thread; failures are logged, never raised."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from . import gdelt
from .common import ensure_source, record_run, save_articles, save_bank_events, utcnow
from .feeds import FEEDS, Feed, fetch_feed, parse_articles, parse_bank_events

log = logging.getLogger("collectors")


@dataclass(frozen=True)
class Job:
    name: str
    kind: str
    url: str
    poll_seconds: int
    run: Callable[[Session, object], tuple[int, int]]  # (db, source) -> (received, new)


def _feed_job(feed: Feed) -> Job:
    def run(db, src):
        content = fetch_feed(feed)
        if feed.kind == "central_bank":
            items = parse_bank_events(feed, content)
            return len(items), save_bank_events(db, items)
        items = parse_articles(feed, content)
        return len(items), save_articles(db, src, items)
    return Job(feed.name, feed.kind, feed.url, feed.poll_seconds, run)


def _gdelt_run(db, src):
    items = gdelt.parse(gdelt.fetch())
    return len(items), save_articles(db, src, items)


def jobs() -> list[Job]:
    return [_feed_job(f) for f in FEEDS] + [Job(gdelt.NAME, "news", gdelt.URL, gdelt.POLL_SECONDS, _gdelt_run)]


def run_job(sf: sessionmaker, job: Job) -> None:
    started = utcnow()
    with sf() as db:
        src = ensure_source(db, job.name, job.kind, job.url, job.poll_seconds)
        if not src.enabled:
            return
        received = new = 0
        error = None
        try:
            received, new = job.run(db, src)
        except Exception as e:  # noqa: BLE001 - a failing source must not stop the others
            db.rollback()
            error = f"{type(e).__name__}: {e}"[:300]
            log.warning("collector %s failed: %s", job.name, error)
        record_run(db, src, started, received, new, error)


async def _loop(sf: sessionmaker, job: Job, delay: float) -> None:
    await asyncio.sleep(delay)
    while True:
        await asyncio.to_thread(run_job, sf, job)
        await asyncio.sleep(job.poll_seconds)


def start(sf: sessionmaker) -> list[asyncio.Task]:
    # Staggered starts keep us under GDELT's 1 request / 5 s limit.
    return [asyncio.create_task(_loop(sf, j, 3.0 * i)) for i, j in enumerate(jobs())]
