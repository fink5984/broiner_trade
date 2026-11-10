"""Fully functional simulated broker: spread, slippage, commission, SL/TP, margin, idempotency."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from .base import BrokerAdapter, BrokerError, OrderRequest, Quote, Side


class PaperBroker(BrokerAdapter):
    is_live = False

    def __init__(self, balance: float = 10_000.0, currency: str = "ILS", leverage: float = 20.0,
                 commission_per_unit: float = 0.0, slippage: float = 0.0,
                 min_units: float = 1000.0, max_units: float = 1_000_000.0,
                 quote_to_account: dict[str, float] | None = None, quote_ccy: dict[str, str] | None = None):
        self.balance, self.currency, self.leverage = balance, currency, leverage
        self.commission_per_unit, self.slippage = commission_per_unit, slippage
        self.min_units, self.max_units = min_units, max_units
        self.q2a = quote_to_account or {"ILS": 1.0}
        self.quote_ccy = quote_ccy or {}
        self.quotes: dict[str, Quote] = {}
        self.positions: dict[str, dict] = {}
        self.closed: list[dict] = []
        self.orders: dict[str, dict] = {}       # client_order_id -> result (idempotency)
        self.connected = False
        self._lock = threading.RLock()

    def connect(self) -> None:
        self.connected = True

    # --- market feed: triggers SL/TP; gaps fill at the worse available price ---
    def set_quote(self, q: Quote) -> list[dict]:
        with self._lock:
            self.quotes[q.symbol] = q
            hit = []
            for pid, pos in list(self.positions.items()):
                if pos["symbol"] != q.symbol:
                    continue
                if pos["side"] == "BUY":
                    px = q.bid
                    if px <= pos["stop_loss"]:
                        hit.append(self._close(pid, px, "STOP_LOSS", q.ts))
                    elif pos["take_profit"] and px >= pos["take_profit"]:
                        hit.append(self._close(pid, pos["take_profit"], "TAKE_PROFIT", q.ts))
                else:
                    px = q.ask
                    if px >= pos["stop_loss"]:
                        hit.append(self._close(pid, px, "STOP_LOSS", q.ts))
                    elif pos["take_profit"] and px <= pos["take_profit"]:
                        hit.append(self._close(pid, pos["take_profit"], "TAKE_PROFIT", q.ts))
            return hit

    def _rate(self, symbol: str) -> float:
        ccy = self.quote_ccy.get(symbol, symbol[-3:])
        if ccy not in self.q2a:
            raise BrokerError(f"no conversion rate {ccy}->{self.currency}")
        return self.q2a[ccy]

    def _unrealized(self, pos: dict) -> float:
        q = self.quotes.get(pos["symbol"])
        if not q:
            return 0.0
        px = q.bid if pos["side"] == "BUY" else q.ask
        d = (px - pos["entry"]) if pos["side"] == "BUY" else (pos["entry"] - px)
        return d * pos["units"] * self._rate(pos["symbol"])

    def _margin_used(self) -> float:
        return sum(p["entry"] * p["units"] * self._rate(p["symbol"]) / self.leverage for p in self.positions.values())

    def get_account(self) -> dict:
        with self._lock:
            unreal = sum(self._unrealized(p) for p in self.positions.values())
            eq = self.balance + unreal
            m = self._margin_used()
            return {"balance": self.balance, "equity": eq, "unrealized": unreal, "margin_used": m,
                    "free_margin": eq - m, "currency": self.currency, "mode": "PAPER"}

    def get_symbols(self):
        return [{"symbol": s} for s in self.quotes]

    def get_quotes(self, symbols):
        return {s: self.quotes[s] for s in symbols if s in self.quotes}

    def get_historical_candles(self, symbol, timeframe, start, end):
        raise NotImplementedError("PaperBroker has no history; use the market data store")

    def get_positions(self):
        with self._lock:
            return [dict(p, unrealized=self._unrealized(p)) for p in self.positions.values()]

    def get_orders(self):
        return list(self.orders.values())

    def place_order(self, req: OrderRequest) -> dict:
        with self._lock:
            if not self.connected:
                raise BrokerError("not connected")
            if req.client_order_id in self.orders:
                return dict(self.orders[req.client_order_id], duplicate=True)
            q = self.quotes.get(req.symbol)
            if q is None:
                return self._reject(req, "no quote")
            if not (self.min_units <= req.units <= self.max_units):
                return self._reject(req, "units out of broker limits")
            if req.stop_loss is None:
                return self._reject(req, "stop loss required")
            fill = (q.ask + self.slippage) if req.side == Side.BUY else (q.bid - self.slippage)
            if (req.side == Side.BUY and req.stop_loss >= fill) or (req.side == Side.SELL and req.stop_loss <= fill):
                return self._reject(req, "stop loss on wrong side")
            margin = fill * req.units * self._rate(req.symbol) / self.leverage
            if margin > self.get_account()["free_margin"]:
                return self._reject(req, "insufficient margin")
            fee = self.commission_per_unit * req.units
            self.balance -= fee
            pid = uuid.uuid4().hex
            self.positions[pid] = {"id": pid, "symbol": req.symbol, "side": req.side.value, "units": req.units,
                                   "entry": fill, "stop_loss": req.stop_loss, "take_profit": req.take_profit,
                                   "opened_at": q.ts, "fees": fee, "client_order_id": req.client_order_id}
            res = {"order_id": req.client_order_id, "status": "FILLED", "position_id": pid, "fill_price": fill}
            self.orders[req.client_order_id] = res
            return res

    def _reject(self, req, reason):
        res = {"order_id": req.client_order_id, "status": "REJECTED", "reason": reason}
        self.orders[req.client_order_id] = res
        return res

    def modify_order(self, position_id, stop_loss=None, take_profit=None):
        with self._lock:
            pos = self.positions.get(position_id)
            if not pos:
                raise BrokerError("unknown position")
            if stop_loss is not None:
                looser = stop_loss < pos["stop_loss"] if pos["side"] == "BUY" else stop_loss > pos["stop_loss"]
                if looser:
                    raise BrokerError("refused: new stop loss increases risk")
                pos["stop_loss"] = stop_loss
            if take_profit is not None:
                pos["take_profit"] = take_profit
            return dict(pos)

    def _close(self, pid, price, reason, ts=None) -> dict:
        pos = self.positions.pop(pid)
        d = (price - pos["entry"]) if pos["side"] == "BUY" else (pos["entry"] - price)
        gross = d * pos["units"] * self._rate(pos["symbol"])
        fee = self.commission_per_unit * pos["units"]
        self.balance += gross - fee
        rec = dict(pos, exit=price, closed_at=ts or datetime.now(timezone.utc), exit_reason=reason,
                   gross_pnl=gross, fees=pos["fees"] + fee, net_pnl=gross - fee - pos["fees"])
        self.closed.append(rec)
        return rec

    def close_position(self, position_id, reason="MANUAL"):
        with self._lock:
            pos = self.positions.get(position_id)
            if not pos:
                raise BrokerError("unknown position")
            q = self.quotes[pos["symbol"]]
            return self._close(position_id, q.bid if pos["side"] == "BUY" else q.ask, reason, q.ts)

    def cancel_order(self, order_id):
        return {"order_id": order_id, "status": "NOT_PENDING"}  # market orders fill immediately

    def reconcile_state(self):
        with self._lock:
            return {"positions": len(self.positions), "balance": self.balance, "ok": True}
