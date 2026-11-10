"""Read-only API for the info center: sources, news and central-bank events."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .collectors.common import utcnow
from .db import get_session
from .models import CentralBankEvent, DataSource, IngestionRun, NewsArticle

router = APIRouter(prefix="/api")


def _aware(t):
    return t if t is None or t.tzinfo else t.replace(tzinfo=utcnow().tzinfo)


def _health(s: DataSource) -> str:
    """connected only while the last success is recent (3 poll periods); otherwise stale/error."""
    last = _aware(s.last_success_at)
    if s.status == "error":
        return "error"
    if last is None:
        return s.status
    return "connected" if utcnow() - last <= timedelta(seconds=3 * max(s.poll_seconds, 60)) else "stale"


def news_state(db: Session) -> str:
    try:
        srcs = db.scalars(select(DataSource).where(DataSource.kind.in_(("news", "central_bank")))).all()
    except Exception:
        return "not_connected"
    return "connected" if any(_health(s) == "connected" for s in srcs) else "not_connected"


@router.get("/sources")
def sources(db: Session = Depends(get_session)):
    last_run = {}
    for r in db.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(500)):
        last_run.setdefault(r.source_id, r)
    out = []
    for s in db.scalars(select(DataSource).order_by(DataSource.kind, DataSource.name)):
        r = last_run.get(s.id)
        out.append({"name": s.name, "kind": s.kind, "url": s.url, "poll_seconds": s.poll_seconds, "enabled": s.enabled,
                    "status": _health(s), "last_success_at": _aware(s.last_success_at).isoformat() if s.last_success_at else None,
                    "last_run": {"received": r.items_received, "new": r.items_new, "error": r.error} if r else None})
    return {"items": out}


@router.get("/news")
def news(limit: int = Query(100, ge=1, le=300), currency: str | None = None, db: Session = Depends(get_session)):
    q = (select(NewsArticle, DataSource.name).join(DataSource, DataSource.id == NewsArticle.source_id)
         .order_by(NewsArticle.published_at.desc()).limit(limit * 3 if currency else limit))
    rows = [{"title": a.title, "url": a.url, "source": n, "published_at": _aware(a.published_at).isoformat(),
             "discovered_at": _aware(a.discovered_at).isoformat(), "currencies": a.currencies} for a, n in db.execute(q)]
    if currency:
        rows = [r for r in rows if currency.upper() in r["currencies"]][:limit]
    total = db.scalar(select(func.count()).select_from(NewsArticle))
    return {"items": rows, "total": total}


@router.get("/central-bank")
def central_bank(limit: int = Query(60, ge=1, le=200), db: Session = Depends(get_session)):
    rows = db.scalars(select(CentralBankEvent).order_by(CentralBankEvent.event_time.desc()).limit(limit)).all()
    return {"items": [{"bank": e.bank, "kind": e.kind, "title": e.title, "url": e.url,
                       "event_time": _aware(e.event_time).isoformat(), "available_at": _aware(e.available_at).isoformat()} for e in rows]}
