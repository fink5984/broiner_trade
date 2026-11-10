"""Deterministic SYNTHETIC candles. NOT market data. Every API response using this is flagged demo=True."""
import numpy as np
import pandas as pd

SYMBOLS = {"USDILS": 3.65, "GBPUSD": 1.31, "EURUSD": 1.09, "AUDUSD": 0.66, "NZDUSD": 0.60, "USDCAD": 1.36, "USDCHF": 0.88, "USDJPY": 150.0,
           "XAUUSD": 2650.0, "XAGUSD": 31.0, "USOIL": 70.0, "UKOIL": 74.0, "NGAS": 3.0, "COPPER": 4.2}
TF = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}


def synthetic_candles(symbol: str, n: int = 1200, seed_offset: int = 0) -> pd.DataFrame:
    base = SYMBOLS[symbol]
    rng = np.random.default_rng(abs(hash(symbol)) % 10_000 if False else sum(map(ord, symbol)) + seed_offset)
    idx = pd.date_range(end=pd.Timestamp("2026-01-09 21:45", tz="UTC"), periods=n, freq="15min")
    vol = base * 0.0008
    close = base + np.cumsum(rng.normal(0, vol, n))
    open_ = np.r_[close[0], close[:-1]]
    hi = np.maximum(open_, close) + rng.uniform(0, vol, n)
    lo = np.minimum(open_, close) - rng.uniform(0, vol, n)
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close}, index=idx)
