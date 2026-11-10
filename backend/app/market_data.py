"""Read market data from the DB (written by the FXCM bridge). Falls back to clearly-flagged synthetic data."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .demo_data import synthetic_candles
from .engines import indicators as ind
from .models import DataSource, Instrument, MarketCandle, MarketQuote

LIVE_SOURCE = "fxcm-demo"
TF_DB = {"5m": "m5", "15m": "m15", "1h": "H1", "4h": "H4", "1d": "D1"}
TF_PANDAS = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def live_candles(db: Session, symbol: str, tf: str, limit: int = 600, complete_only: bool = True) -> pd.DataFrame | None:
    q = (select(MarketCandle).join(Instrument, Instrument.id == MarketCandle.instrument_id)
         .where(Instrument.symbol == symbol, MarketCandle.timeframe == TF_DB[tf], MarketCandle.source == LIVE_SOURCE,
                MarketCandle.is_synthetic.is_(False)))
    if complete_only:
        q = q.where(MarketCandle.is_complete.is_(True))
    rows = db.scalars(q.order_by(MarketCandle.open_time.desc()).limit(limit)).all()
    if not rows:
        return None
    df = pd.DataFrame([{"t": _utc(r.open_time), "open": r.open, "high": r.high, "low": r.low, "close": r.close} for r in rows])
    return df.set_index(pd.DatetimeIndex(df.pop("t"))).sort_index()


def latest_quote(db: Session, symbol: str) -> MarketQuote | None:
    return db.scalars(select(MarketQuote).join(Instrument, Instrument.id == MarketQuote.instrument_id)
                      .where(Instrument.symbol == symbol, MarketQuote.source == LIVE_SOURCE)
                      .order_by(MarketQuote.ts.desc()).limit(1)).first()


def source_status(db: Session) -> dict:
    s = db.scalars(select(DataSource).where(DataSource.name == "FXCM Demo")).first()
    if not s:
        return {"status": "not_configured", "last_success_at": None, "config": {}}
    return {"status": s.status, "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None, "config": s.config}


def candles_for(db: Session | None, symbol: str, tf: str, synthetic_symbols: dict) -> tuple[pd.DataFrame, bool]:
    """Returns (candles, is_live). Live data is preferred; otherwise synthetic (flagged)."""
    if db is not None:
        try:
            df = live_candles(db, symbol, tf)
            if df is not None and len(df) >= 30:
                return df, True
        except Exception:
            pass
    if symbol not in synthetic_symbols:
        raise KeyError(symbol)
    df = synthetic_candles(symbol)
    if tf in ("1h", "4h", "1d"):
        df = ind.resample_candles(df, TF_PANDAS[tf])
    return df, False


def quote_age_seconds(q: MarketQuote | None, now: datetime | None = None) -> float | None:
    if q is None:
        return None
    return ((now or datetime.now(timezone.utc)) - _utc(q.ts)).total_seconds()


def latest_quotes(db: Session, window_seconds: int = 600) -> dict[str, dict]:
    """Latest live quote per symbol within the window (one query, uses ix_quotes_inst_ts).
    Symbols with no quote inside the window are omitted (treated as stale by callers)."""
    now = datetime.now(timezone.utc)
    since = now - pd.Timedelta(seconds=window_seconds)
    sub = (select(MarketQuote.instrument_id, func.max(MarketQuote.ts).label("mx"))
           .where(MarketQuote.source == LIVE_SOURCE, MarketQuote.ts >= since)
           .group_by(MarketQuote.instrument_id).subquery())
    q = (select(Instrument.symbol, MarketQuote.bid, MarketQuote.ask, MarketQuote.ts)
         .join(sub, (MarketQuote.instrument_id == sub.c.instrument_id) & (MarketQuote.ts == sub.c.mx))
         .join(Instrument, Instrument.id == MarketQuote.instrument_id)
         .where(MarketQuote.source == LIVE_SOURCE))
    out = {}
    for sym, bid, ask, ts in db.execute(q):
        t = _utc(ts)
        out[sym] = {"bid": bid, "ask": ask, "mid": (bid + ask) / 2, "spread": ask - bid,
                    "ts": t.isoformat(), "epoch": t.timestamp(), "age_s": (now - t).total_seconds()}
    return out


def forming_candle(db: Session, symbol: str, tf: str) -> dict | None:
    """The newest still-forming candle (display only: never fed to analysis or signals)."""
    r = db.scalars(select(MarketCandle).join(Instrument, Instrument.id == MarketCandle.instrument_id)
                   .where(Instrument.symbol == symbol, MarketCandle.timeframe == TF_DB[tf],
                          MarketCandle.source == LIVE_SOURCE, MarketCandle.is_complete.is_(False))
                   .order_by(MarketCandle.open_time.desc()).limit(1)).first()
    if not r:
        return None
    return {"time": int(_utc(r.open_time).timestamp()), "open": r.open, "high": r.high, "low": r.low, "close": r.close}
