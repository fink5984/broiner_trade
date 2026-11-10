"""Unified broker interface. Strategy/risk/decision code depends only on this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    ts: datetime  # UTC

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2


@dataclass
class OrderRequest:
    client_order_id: str          # idempotency key; same id is never executed twice
    symbol: str
    side: Side
    units: float
    stop_loss: float
    take_profit: float | None = None


class BrokerError(Exception):
    pass


class BrokerAdapter(ABC):
    is_live: bool = False

    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def get_account(self) -> dict: ...
    @abstractmethod
    def get_symbols(self) -> list[dict]: ...
    @abstractmethod
    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]: ...
    @abstractmethod
    def get_historical_candles(self, symbol: str, timeframe: str, start: datetime, end: datetime): ...
    @abstractmethod
    def get_positions(self) -> list[dict]: ...
    @abstractmethod
    def get_orders(self) -> list[dict]: ...
    @abstractmethod
    def place_order(self, req: OrderRequest) -> dict: ...
    @abstractmethod
    def modify_order(self, position_id: str, stop_loss: float | None, take_profit: float | None) -> dict: ...
    @abstractmethod
    def close_position(self, position_id: str) -> dict: ...
    @abstractmethod
    def cancel_order(self, order_id: str) -> dict: ...
    @abstractmethod
    def reconcile_state(self) -> dict: ...
