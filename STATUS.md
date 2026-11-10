# AI Algorithmic Trading Platform — Status

Last updated: 2026-11-10. **Paper trading only. No live broker code exists. No real money is ever used.**

## How to run (Windows, no Docker)
`powershell -ExecutionPolicy Bypass -File .\start.ps1` starts the Neon tunnel, the API (:8000) and the UI (:5173).

**Why a tunnel:** this network blocks raw Postgres (port 5432) but allows HTTPS/WSS (443).
`tools/neon_tunnel.mjs` forwards `127.0.0.1:54329` to Neon's `wss://<host>/v2` endpoint. `backend/.env` points `DATABASE_URL` at it with `sslmode=disable`; TLS is provided by the wss leg. On a network without the block, point `DATABASE_URL` straight at Neon.

## Done and tested
Backend: 65 passing tests (`cd backend; .venv\Scripts\python -m pytest`).

| Module | File | Notes |
|---|---|---|
| Indicators | `app/engines/indicators.py` | SMA/EMA/RSI/MACD/ATR/Bollinger, resampling, gaps, swing S/R, breakout, candle patterns; no look-ahead |
| Technical engine | `app/engines/technical.py` | Deterministic, reproducible |
| AI schemas + prompt-injection guard | `app/engines/ai_schemas.py` | Pydantic validation; invalid output yields no signal |
| Decision Engine | `app/engines/decision.py` | Weights sum to 100, veto, agreement, staleness, cooldown, cost gate, idempotency |
| Risk Engine | `app/risk/engine.py` | Sizing, daily/weekly/DD tiers, latched EMERGENCY_STOP, hard ceilings |
| PaperBroker | `app/broker/` | Bid/Ask, slippage, fees, SL/TP, margin, idempotent orders |
| Backtester | `app/backtest/engine.py` | Next-bar fills, walk-forward, stability-ranked grid search |
| DB schema (35 tables) + Alembic | `app/models.py`, `migrations/` | Applied to Neon |
| Versioned settings + audit log | `app/settings_service.py` | Server-side validation; PUT gated by `ADMIN_TOKEN` |
| API | `app/main.py`, `app/info.py` | status, markets (live FXCM + synthetic fallback), backtest, settings, sources, news, central-bank |
| Trading service | `app/trading/` | Paper only, starts PAUSED. 15m closed bar -> technical signal -> Decision -> Risk -> PaperBroker; persists decisions, risk checks, orders, positions, trades, equity snapshots, alerts; restores broker from DB on restart; admin-gated start/pause/emergency-stop/reset (`/api/system/*`), auto emergency stop on drawdown. Technical-only until Gemini is connected |
| Keyless collectors | `app/collectors/` | Fed/ECB/BoE RSS -> `central_bank_events`; BBC/Guardian/CNBC/FXStreet RSS + GDELT -> `news_articles`; headline+link only, deduped, run-logged; started from the API lifespan (`COLLECTORS_ENABLED`). GDELT currently answers HTTP 429 to this IP (retries every 15 min). No public Bank of Israel feed found |

Frontend (`frontend/`): React + TypeScript + Tailwind. The design system and UI kit are written in-house (`src/index.css` tokens, `src/ui.tsx`, `src/charts.tsx`). Hebrew RTL, dark and light themes, responsive layout. All 6 pages exist. Settings are DB-backed; the backtest lab is live.

## Not built yet
- User login, 2FA, RBAC (settings currently gated by a single admin token)
- Data collectors: FRED (needs key), Bank of Israel
- Gemini provider + AI analysis pipeline
- Alerts delivery (email/Telegram), log viewer, WebSocket for trades
- Strategy CRUD/versions UI, optimisation UI, trades persistence
- Live broker adapters (intentionally absent)
- Docs: architecture, data-source/broker guide, deployment, test report

## Needs from the user
1. A market data source (broker demo / practice account API key).
2. `GEMINI_API_KEY`.
3. Rotate the Neon password (it was pasted in chat), then update `backend/.env`.
