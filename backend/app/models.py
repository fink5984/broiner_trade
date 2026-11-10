"""SQLAlchemy schema. All timestamps are timezone-aware UTC. UUID primary keys.

Published strategy versions are immutable (enforced in the service layer + `published_at` set once).
Trading history tables never cascade-delete from log tables.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Numeric, String,
                        Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

Json = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(18, 6)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def fk(table: str, nullable: bool = False, index: bool = True):
    return mapped_column(Uuid, ForeignKey(f"{table}.id"), nullable=nullable, index=index)


def ts(nullable: bool = False, default=True):
    return mapped_column(DateTime(timezone=True), nullable=nullable, default=utcnow if default else None)


# ---------------- identity / config ----------------
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin / operator / viewer
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ts()
    __table_args__ = (CheckConstraint("role in ('admin','operator','viewer')", name="ck_user_role"),)


class SystemSetting(Base):
    """Versioned key/value config. A change inserts a new row (version+1); old rows are kept."""
    __tablename__ = "system_settings"
    id: Mapped[uuid.UUID] = pk()
    key: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    value: Mapped[dict] = mapped_column(Json)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    changed_by: Mapped[uuid.UUID | None] = fk("users", True)
    created_at: Mapped[datetime] = ts()
    __table_args__ = (UniqueConstraint("key", "version"), Index("ix_settings_current", "key", "is_current"))


class CredentialMetadata(Base):
    """Metadata only. Secret values are never stored here or exposed to the frontend."""
    __tablename__ = "credentials_metadata"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)
    provider: Mapped[str] = mapped_column(String(60))
    storage: Mapped[str] = mapped_column(String(30), default="env")  # env / encrypted_file
    last_rotated_at: Mapped[datetime | None] = ts(True, False)
    created_at: Mapped[datetime] = ts()


# ---------------- data sources / ingestion ----------------
class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(30))  # market / news / central_bank / macro
    url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    poll_seconds: Mapped[int] = mapped_column(Integer, default=900)
    config: Mapped[dict] = mapped_column(Json, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_success_at: Mapped[datetime | None] = ts(True, False)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[uuid.UUID] = pk()
    source_id: Mapped[uuid.UUID] = fk("data_sources")
    started_at: Mapped[datetime] = ts()
    finished_at: Mapped[datetime | None] = ts(True, False)
    items_received: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Instrument(Base):
    __tablename__ = "instruments"
    id: Mapped[uuid.UUID] = pk()
    symbol: Mapped[str] = mapped_column(String(20), unique=True)
    base: Mapped[str] = mapped_column(String(10))
    quote: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(20), default="fx")
    min_units: Mapped[float] = mapped_column(Float, default=1000)
    unit_step: Mapped[float] = mapped_column(Float, default=1000)
    max_spread: Mapped[float] = mapped_column(Float, default=0.05)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketQuote(Base):
    __tablename__ = "market_quotes"
    id: Mapped[uuid.UUID] = pk()
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    source: Mapped[str] = mapped_column(String(60))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bid: Mapped[float] = mapped_column(Float)
    ask: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("instrument_id", "source", "ts"), Index("ix_quotes_inst_ts", "instrument_id", "ts"),
                      CheckConstraint("ask >= bid", name="ck_quote_spread"))


class MarketCandle(Base):
    __tablename__ = "market_candles"
    id: Mapped[uuid.UUID] = pk()
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    timeframe: Mapped[str] = mapped_column(String(5))
    source: Mapped[str] = mapped_column(String(60))
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("instrument_id", "timeframe", "source", "open_time"),
                      Index("ix_candles_lookup", "instrument_id", "timeframe", "open_time"),
                      CheckConstraint("high >= low", name="ck_candle_hl"))


class NewsArticle(Base):
    __tablename__ = "news_articles"
    id: Mapped[uuid.UUID] = pk()
    source_id: Mapped[uuid.UUID] = fk("data_sources")
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)  # dedupe key
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)  # only if the source permits; never fabricated
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = ts()
    countries: Mapped[list] = mapped_column(Json, default=list)
    currencies: Mapped[list] = mapped_column(Json, default=list)
    __table_args__ = (Index("ix_news_published", "published_at"),)


class NewsEvent(Base):
    __tablename__ = "news_events"
    id: Mapped[uuid.UUID] = pk()
    event_type: Mapped[str] = mapped_column(String(80))
    first_article_id: Mapped[uuid.UUID] = fk("news_articles")
    cluster_key: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = ts()


class CentralBankEvent(Base):
    __tablename__ = "central_bank_events"
    id: Mapped[uuid.UUID] = pk()
    bank: Mapped[str] = mapped_column(String(10))  # BOI / FED / BOE / ECB
    kind: Mapped[str] = mapped_column(String(30))  # rate_decision / speech / minutes / projection / calendar
    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = ts()
    __table_args__ = (UniqueConstraint("bank", "external_id"),)


class EconomicRelease(Base):
    __tablename__ = "economic_releases"
    id: Mapped[uuid.UUID] = pk()
    series_id: Mapped[str] = mapped_column(String(60))
    country: Mapped[str] = mapped_column(String(3))
    name: Mapped[str] = mapped_column(String(200))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    forecast: Mapped[float | None] = mapped_column(Float)  # only with a reliable source
    actual: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(30))


class MacroDataVintage(Base):
    """Point-in-time macro data: every revision is a new row; backtests pick by available_at."""
    __tablename__ = "macro_data_vintages"
    id: Mapped[uuid.UUID] = pk()
    series_id: Mapped[str] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(40))
    observation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(30))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    vintage: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("series_id", "observation_date", "available_at"),
                      Index("ix_macro_pit", "series_id", "observation_date", "available_at"))


# ---------------- AI ----------------
class AIProvider(Base):
    __tablename__ = "ai_providers"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(40), unique=True)  # gemini / openai
    default_model: Mapped[str | None] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_budget: Mapped[float | None] = mapped_column(Float)
    monthly_budget: Mapped[float | None] = mapped_column(Float)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)


class AIPromptVersion(Base):
    __tablename__ = "ai_prompt_versions"
    id: Mapped[uuid.UUID] = pk()
    task: Mapped[str] = mapped_column(String(30))  # system / news / central_bank
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    provider_id: Mapped[uuid.UUID | None] = fk("ai_providers", True)
    model: Mapped[str | None] = mapped_column(String(80))
    temperature: Mapped[float | None] = mapped_column(Float)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = fk("users", True)
    created_at: Mapped[datetime] = ts()
    __table_args__ = (UniqueConstraint("task", "version"),)


class AIAnalysisRun(Base):
    __tablename__ = "ai_analysis_runs"
    id: Mapped[uuid.UUID] = pk()
    task: Mapped[str] = mapped_column(String(30))
    prompt_version_id: Mapped[uuid.UUID] = fk("ai_prompt_versions")
    model: Mapped[str] = mapped_column(String(80))
    input_ref: Mapped[str] = mapped_column(String(80))  # article / event id
    status: Mapped[str] = mapped_column(String(20))  # ok / invalid_output / error / over_budget
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = ts()


class AIAnalysisResult(Base):
    __tablename__ = "ai_analysis_results"
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = fk("ai_analysis_runs")
    instrument_id: Mapped[uuid.UUID | None] = fk("instruments", True)
    payload: Mapped[dict] = mapped_column(Json)  # validated JSON
    predicted_direction: Mapped[str | None] = mapped_column(String(10))
    horizon_hours: Mapped[float | None] = mapped_column(Float)
    price_at_prediction: Mapped[float | None] = mapped_column(Float)
    price_at_horizon: Mapped[float | None] = mapped_column(Float)  # filled after horizon for scoring
    available_at: Mapped[datetime] = ts()


# ---------------- strategies ----------------
class Strategy(Base):
    __tablename__ = "strategies"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft / paper / disabled
    created_at: Mapped[datetime] = ts()
    versions: Mapped[list["StrategyVersion"]] = relationship(back_populates="strategy")


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    id: Mapped[uuid.UUID] = pk()
    strategy_id: Mapped[uuid.UUID] = fk("strategies")
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(Json)  # technical / news / macro / decision / hold settings
    published_at: Mapped[datetime | None] = ts(True, False)  # once set, row is immutable
    created_by: Mapped[uuid.UUID | None] = fk("users", True)
    created_at: Mapped[datetime] = ts()
    strategy: Mapped[Strategy] = relationship(back_populates="versions")
    __table_args__ = (UniqueConstraint("strategy_id", "version"),)


class StrategyParameter(Base):
    __tablename__ = "strategy_parameters"
    id: Mapped[uuid.UUID] = pk()
    version_id: Mapped[uuid.UUID] = fk("strategy_versions")
    engine: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict] = mapped_column(Json)
    __table_args__ = (UniqueConstraint("version_id", "engine", "name"),)


class StrategyAssignment(Base):
    __tablename__ = "strategy_assignments"
    id: Mapped[uuid.UUID] = pk()
    version_id: Mapped[uuid.UUID] = fk("strategy_versions")
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    mode: Mapped[str] = mapped_column(String(10), default="PAPER")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (CheckConstraint("mode in ('PAPER','LIVE')", name="ck_assign_mode"),)


# ---------------- decisions / trading ----------------
class MarketRegime(Base):
    __tablename__ = "market_regimes"
    id: Mapped[uuid.UUID] = pk()
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    regime: Mapped[str] = mapped_column(String(30))


class TradingSignal(Base):
    __tablename__ = "trading_signals"
    id: Mapped[uuid.UUID] = pk()
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    engine: Mapped[str] = mapped_column(String(20))
    score: Mapped[float] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(Json, default=dict)
    ts: Mapped[datetime] = ts()


class TradingDecision(Base):
    __tablename__ = "trading_decisions"
    id: Mapped[uuid.UUID] = pk()
    ts: Mapped[datetime] = ts()
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    strategy_version_id: Mapped[uuid.UUID] = fk("strategy_versions")
    prompt_version_ids: Mapped[list] = mapped_column(Json, default=list)
    action: Mapped[str] = mapped_column(String(10))
    score: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[dict] = mapped_column(Json, default=dict)
    market_snapshot: Mapped[dict] = mapped_column(Json, default=dict)
    technical_analysis_id: Mapped[uuid.UUID | None] = fk("trading_signals", True)
    news_analysis_ids: Mapped[list] = mapped_column(Json, default=list)
    macro_analysis_ids: Mapped[list] = mapped_column(Json, default=list)
    execution_status: Mapped[str] = mapped_column(String(20), default="none")
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    __table_args__ = (CheckConstraint("action in ('BUY','SELL','HOLD','CLOSE','NO_TRADE')", name="ck_decision_action"),)


class RiskCheck(Base):
    __tablename__ = "risk_checks"
    id: Mapped[uuid.UUID] = pk()
    decision_id: Mapped[uuid.UUID] = fk("trading_decisions")
    allowed: Mapped[bool] = mapped_column(Boolean)
    units: Mapped[float] = mapped_column(Float, default=0)
    risk_amount: Mapped[float] = mapped_column(Float, default=0)
    reasons: Mapped[list] = mapped_column(Json, default=list)
    drawdown_pct: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = ts()


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(120))
    broker: Mapped[str] = mapped_column(String(40))  # paper / fxcm / mt4
    mode: Mapped[str] = mapped_column(String(10), default="PAPER")
    currency: Mapped[str] = mapped_column(String(3), default="ILS")
    live_approved: Mapped[bool] = mapped_column(Boolean, default=False)  # needs separate admin approval
    created_at: Mapped[datetime] = ts()
    __table_args__ = (CheckConstraint("mode in ('PAPER','LIVE')", name="ck_acct_mode"),
                      CheckConstraint("mode = 'PAPER' or live_approved", name="ck_live_requires_approval"))


class BrokerOrder(Base):
    __tablename__ = "broker_orders"
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID] = fk("broker_accounts")
    decision_id: Mapped[uuid.UUID | None] = fk("trading_decisions", True)
    client_order_id: Mapped[str] = mapped_column(String(80), unique=True)  # idempotency
    broker_order_id: Mapped[str | None] = mapped_column(String(80))
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    side: Mapped[str] = mapped_column(String(4))
    units: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))
    fill_price: Mapped[float | None] = mapped_column(Float)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = ts()


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID] = fk("broker_accounts")
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    side: Mapped[str] = mapped_column(String(4))
    units: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    opened_at: Mapped[datetime] = ts()
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[uuid.UUID] = pk()
    number: Mapped[int] = mapped_column(Integer, unique=True)
    position_id: Mapped[uuid.UUID | None] = fk("positions", True)
    decision_id: Mapped[uuid.UUID | None] = fk("trading_decisions", True)
    strategy_version_id: Mapped[uuid.UUID] = fk("strategy_versions")
    prompt_version_ids: Mapped[list] = mapped_column(Json, default=list)
    instrument_id: Mapped[uuid.UUID] = fk("instruments")
    mode: Mapped[str] = mapped_column(String(10), default="PAPER")
    side: Mapped[str] = mapped_column(String(4))
    units: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    exit_time: Mapped[datetime | None] = ts(True, False)
    exit_price: Mapped[float | None] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float, default=0)
    spread_cost: Mapped[float] = mapped_column(Float, default=0)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    entry_reason: Mapped[str | None] = mapped_column(Text)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    events: Mapped[list] = mapped_column(Json, default=list)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID] = fk("broker_accounts")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    balance: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    peak_equity: Mapped[float] = mapped_column(Float)
    cashflow: Mapped[float] = mapped_column(Float, default=0)  # deposits(+)/withdrawals(-)


# ---------------- research ----------------
class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[uuid.UUID] = pk()
    strategy_version_id: Mapped[uuid.UUID | None] = fk("strategy_versions", True)
    instrument_id: Mapped[uuid.UUID | None] = fk("instruments", True)
    config: Mapped[dict] = mapped_column(Json)
    metrics: Mapped[dict] = mapped_column(Json)
    equity_curve: Mapped[list] = mapped_column(Json, default=list)
    data_is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = fk("users", True)
    created_at: Mapped[datetime] = ts()


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = fk("backtest_runs")
    side: Mapped[str] = mapped_column(String(4))
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float] = mapped_column(Float)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float] = mapped_column(Float)
    units: Mapped[float] = mapped_column(Float)
    net_pnl: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(30))


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"
    id: Mapped[uuid.UUID] = pk()
    base_config: Mapped[dict] = mapped_column(Json)
    grid: Mapped[dict] = mapped_column(Json)
    results: Mapped[list] = mapped_column(Json, default=list)
    ranking_criteria: Mapped[dict] = mapped_column(Json, default=dict)
    created_at: Mapped[datetime] = ts()


# ---------------- ops ----------------
class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = pk()
    severity: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    trade_id: Mapped[uuid.UUID | None] = fk("trades", True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = ts()


class AuditLog(Base):
    """Never deleted by log retention; independent from technical logs and trade history."""
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = pk()
    ts: Mapped[datetime] = ts()
    user_id: Mapped[uuid.UUID | None] = fk("users", True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str | None] = mapped_column(String(200))
    old_value: Mapped[dict | None] = mapped_column(Json)
    new_value: Mapped[dict | None] = mapped_column(Json)
    ip: Mapped[str | None] = mapped_column(String(45))
