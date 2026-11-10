from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import settings_service as ss
from .config import settings as cfg_settings
from .db import SessionLocal, get_session
from . import market_data as md
from .collectors import runner as collectors
from .info import news_state, router as info_router
from .security import require_admin
from .trading import service as trading
from .trading.api import latest_decision, router as trading_router

from .backtest.engine import BacktestConfig, run_backtest
from .demo_data import SYMBOLS, TF, synthetic_candles
from .engines import indicators as ind
from .engines.technical import TechnicalParams, analyze
from .risk.engine import Instrument, RiskLimits

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = collectors.start(SessionLocal) if cfg_settings.collectors_enabled else []
    if cfg_settings.trading_service_enabled:
        tasks.append(trading.start(SessionLocal))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Broiner Trade API", lifespan=lifespan)
app.include_router(info_router)
app.include_router(trading_router)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

DEMO_NOTE = "נתונים סינתטיים - אינם נתוני שוק"
app.state.session_factory = SessionLocal


def _db_state() -> str:
    try:
        from .db import engine
        with engine.connect() as c:
            c.execute(text("select 1"))
        return "connected"
    except Exception:
        return "not_connected"


def _system_state(db: Session) -> str:
    try:
        return trading.get_state(db)
    except Exception:
        return "PAUSED"


@app.get("/api/settings/{key}")
def get_setting(key: str, db: Session = Depends(get_session)):
    if key not in ss.SCHEMAS:
        raise HTTPException(404, "unknown settings key")
    return ss.get_current(db, key) | {"hard_ceilings": __import__("app.risk.engine", fromlist=["x"]).HARD_CEILINGS if key == "risk" else None}


@app.get("/api/settings/{key}/history")
def setting_history(key: str, db: Session = Depends(get_session)):
    if key not in ss.SCHEMAS:
        raise HTTPException(404, "unknown settings key")
    return ss.history(db, key)


@app.put("/api/settings/{key}")
def put_setting(key: str, body: dict, request: Request, user: str = Depends(require_admin), db: Session = Depends(get_session)):
    try:
        return ss.update_setting(db, key, body, user, request.client.host if request.client else None)
    except KeyError:
        raise HTTPException(404, "unknown settings key")
    except ValidationError as e:
        raise HTTPException(422, "; ".join(str(x["msg"]).replace("Value error, ", "") + " (" + ".".join(map(str, x["loc"])) + ")" for x in e.errors()))


@app.get("/api/status")
def status(db: Session = Depends(get_session)):
    src = {"status": "not_configured"}
    try:
        src = md.source_status(db)
    except Exception:
        pass
    live = str(src.get("status", "")).startswith("connected")
    return {"mode": "PAPER", "live_trading_enabled": False, "system": _system_state(db),
            "database": _db_state(), "trading_mode": cfg_settings.trading_mode, "broker": "paper (simulated)",
            "market_data": "fxcm_demo" if live else "synthetic_demo", "market_source": src,
            "ai": "not_configured", "news": news_state(db),
            "initial_capital": 10000, "currency": "ILS", "demo_note": DEMO_NOTE}


def _series(db: Session, symbol: str, tf: str) -> tuple[pd.DataFrame, bool]:
    if symbol not in SYMBOLS or tf not in TF:
        raise HTTPException(404, "unknown symbol/timeframe")
    return md.candles_for(db, symbol, tf, SYMBOLS)


def _quote_info(db: Session, symbol: str, df: pd.DataFrame, live: bool) -> dict:
    q = md.latest_quote(db, symbol) if live else None
    if q is None:
        close = float(df.close.iloc[-1])
        return {"price": close, "bid": None, "ask": None, "spread": float(close * 0.0002) if not live else None,
                "quote_time": None, "quote_age_s": None, "stale": live}
    age = md.quote_age_seconds(q)
    # Displayed price is BID everywhere, matching the BID-based candles in the chart.
    return {"price": q.bid, "bid": q.bid, "ask": q.ask, "spread": q.ask - q.bid,
            "quote_time": md._utc(q.ts).isoformat(), "quote_age_s": age, "stale": age is None or age > 120}


@app.get("/api/markets")
def markets(db: Session = Depends(get_session)):
    out = []
    for s in SYMBOLS:
        df, live = _series(db, s, "15m")
        r = analyze(df)
        qi = _quote_info(db, s, df, live)
        back = min(96, len(df) - 1)
        out.append({"symbol": s, **qi,
                    "change_pct": float((qi["price"] / df.close.iloc[-1 - back] - 1) * 100),
                    "technical": r.direction, "score": r.score, "regime": r.regime,
                    "news": None, "macro": None, "trade_status": "NO_TRADE", "demo": not live,
                    "source": md.LIVE_SOURCE if live else "synthetic",
                    "spark": [float(x) for x in df.close.iloc[-96::2]]})
    return {"items": out, "demo_note": DEMO_NOTE}


@app.get("/api/markets/{symbol}")
def market_detail(symbol: str, tf: str = "15m", db: Session = Depends(get_session)):
    df, live = _series(db, symbol, tf)
    df = df.tail(400)
    r = analyze(df)
    qi = _quote_info(db, symbol, df, live)
    e20, e50 = ind.ema(df.close, 20), ind.ema(df.close, 50)
    rows = lambda s: [{"time": int(t.timestamp()), "value": float(v)} for t, v in s.dropna().items()]
    candles = [{"time": int(t.timestamp()), "open": r_.open, "high": r_.high, "low": r_.low, "close": r_.close}
               for t, r_ in df.iterrows()]
    forming = md.forming_candle(db, symbol, tf) if live else None
    if forming and (not candles or forming["time"] > candles[-1]["time"]):
        candles.append(forming)  # display only; analysis above used closed candles
    else:
        forming = None
    blockers = ["ניתוח AI של חדשות ונגידים טרם מחובר — המסחר מבוסס טכני בלבד"]
    if not live:
        blockers.append("אין מקור מחירים אמיתי לנכס זה (נתונים סינתטיים)")
    elif qi["stale"]:
        blockers.append("מחיר אחרון ישן מדי — אסור לפתוח עסקה על נתון לא עדכני")
    state = _system_state(db)
    if state != "ACTIVE":
        blockers.append("המערכת מושהית — אין פתיחת עסקאות חדשות" if state == "PAUSED" else "עצירת חירום פעילה")
    decision = {"action": "NO_TRADE", "reasons": [], "blockers": blockers}
    last = latest_decision(db, symbol) if live and not qi["stale"] else None
    if last:
        decision = {"action": last["action"], "reasons": last["reasons"], "blockers": last["blockers"] + blockers}
    return {"symbol": symbol, "timeframe": tf, "demo": not live, "source": md.LIVE_SOURCE if live else "synthetic",
            "demo_note": DEMO_NOTE, "quote": qi,
            "candles": candles,
            "forming": forming is not None,
            "ema20": rows(e20), "ema50": rows(e50),
            "analysis": {"technical": r.as_dict(), "news": None, "macro": None},
            "decision": decision}


def _quotes_snapshot() -> dict:
    with app.state.session_factory() as db:
        return md.latest_quotes(db)


@app.get("/api/stream/quotes")
async def stream_quotes(request: Request):
    """Server-Sent Events: latest Bid/Ask per symbol, pushed every second."""
    async def gen():
        while not await request.is_disconnected():
            try:
                payload = {"quotes": await asyncio.to_thread(_quotes_snapshot)}
            except Exception as e:
                payload = {"quotes": {}, "error": str(e)[:200]}
            yield "data: " + json.dumps(payload) + "\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class BtRequest(BaseModel):
    symbol: str = "USDILS"
    candles: int = Field(900, ge=300, le=3000)
    initial_capital: float = Field(10_000, gt=0)
    spread: float = Field(0.01, ge=0)
    slippage: float = Field(0.002, ge=0)
    commission_per_unit: float = Field(0.0, ge=0)
    atr_sl_mult: float = Field(1.5, gt=0)
    rr: float = Field(2.0, gt=0)
    ema_fast: int = Field(20, ge=2)
    ema_slow: int = Field(50, ge=3)
    rsi_period: int = Field(14, ge=2)
    risk_per_trade_pct: float = Field(0.25, gt=0)


@app.post("/api/backtest")
def backtest(req: BtRequest, db: Session = Depends(get_session)):
    if req.symbol not in SYMBOLS:
        raise HTTPException(404, "unknown symbol")
    if req.ema_fast >= req.ema_slow:
        raise HTTPException(422, "ema_fast must be smaller than ema_slow")
    live_df = None
    try:
        live_df = md.live_candles(db, req.symbol, "15m", limit=req.candles)
    except Exception:
        pass
    live = live_df is not None and len(live_df) >= 300
    df = live_df if live else synthetic_candles(req.symbol, req.candles)
    try:
        risk = RiskLimits(risk_per_trade_pct=req.risk_per_trade_pct)
        risk.validate()
    except ValueError as e:
        raise HTTPException(422, str(e))
    spread_cap = SYMBOLS[req.symbol] * 0.01
    cfg = BacktestConfig(Instrument(req.symbol, req.symbol[:3], req.symbol[3:], max_spread=spread_cap, max_slippage=spread_cap),
                         req.initial_capital, req.spread, req.slippage, req.commission_per_unit,
                         atr_sl_mult=req.atr_sl_mult, rr=req.rr, risk=risk,
                         tech=TechnicalParams(ema_fast=req.ema_fast, ema_slow=req.ema_slow, rsi_period=req.rsi_period,
                                              compute_levels=False))
    res = run_backtest(df, cfg)
    m = {k: (None if isinstance(v, float) and v == float("inf") else v) for k, v in res["metrics"].items()}
    return {"demo": not live, "source": md.LIVE_SOURCE if live else "synthetic", "candles_used": len(df),
            "period": [df.index[0].isoformat(), df.index[-1].isoformat()], "demo_note": DEMO_NOTE, "metrics": m,
            "equity": [{"time": int(t.timestamp()), "value": v} for t, v in res["equity"]],
            "trades": [dataclasses.asdict(t) | {"entry_time": t.entry_time.isoformat(),
                                                "exit_time": t.exit_time.isoformat()} for t in res["trades"]],
            "rejected_by_risk": res["rejected_by_risk"]}
