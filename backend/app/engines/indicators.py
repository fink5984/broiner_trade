"""Deterministic indicator library. Pure functions over pandas Series/DataFrames.

All functions use only past/current values (no look-ahead): value at index i
depends solely on data at indices <= i.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})


def resample_candles(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate lower-timeframe candles to a higher timeframe.

    df: UTC DatetimeIndex (candle open time) with open/high/low/close[/volume].
    Only complete buckets are returned (the last bucket is dropped if the
    final source candle does not close it), so no partial candle leaks.
    """
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = df.resample(rule, label="left", closed="left").agg(agg).dropna(subset=["open"])
    if len(df) >= 2 and len(out) >= 1:
        step = df.index.to_series().diff().dropna().min()
        bucket = pd.tseries.frequencies.to_offset(rule)
        last_start = out.index[-1]
        if df.index[-1] + step < last_start + pd.Timedelta(bucket):
            out = out.iloc[:-1]
    return out


def find_gaps(index: pd.DatetimeIndex, step: pd.Timedelta, skip_weekend: bool = True) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return (prev, next) pairs where consecutive candles are further apart than `step`.

    Weekend gaps (Fri-Sun) are ignored for FX when skip_weekend is True."""
    gaps = []
    for a, b in zip(index[:-1], index[1:]):
        if b - a > step:
            if skip_weekend and a.weekday() in (4, 5) and b.weekday() in (6, 0):
                continue
            gaps.append((a, b))
    return gaps


def swing_levels(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[pd.Series, pd.Series]:
    """Confirmed swing highs/lows. A pivot at i is only *known* at i+right;
    the returned series is shifted so the value is placed at the confirmation bar."""
    hi, lo = df["high"], df["low"]
    w = left + right + 1
    is_hi = hi.rolling(w).apply(lambda x: float(x[left] == x.max() and (x[left] > x[:left]).all()), raw=True) == 1
    is_lo = lo.rolling(w).apply(lambda x: float(x[left] == x.min() and (x[left] < x[:left]).all()), raw=True) == 1
    pivot_hi = hi.shift(right).where(is_hi)
    pivot_lo = lo.shift(right).where(is_lo)
    return pivot_hi, pivot_lo


def support_resistance(df: pd.DataFrame, left: int = 3, right: int = 3, tol_atr: float = 0.5, max_levels: int = 6) -> list[dict]:
    """Cluster confirmed pivots into levels using tolerance = tol_atr * ATR."""
    ph, pl = swing_levels(df, left, right)
    a = atr(df).iloc[-1] if len(df) > 20 else float((df["high"] - df["low"]).mean())
    tol = max(float(a) * tol_atr, 1e-9)
    pts = [(float(v), "R") for v in ph.dropna()] + [(float(v), "S") for v in pl.dropna()]
    pts.sort()
    clusters: list[list[tuple[float, str]]] = []
    for p in pts:
        if clusters and abs(p[0] - np.mean([x[0] for x in clusters[-1]])) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    last = float(df["close"].iloc[-1])
    levels = [
        {"price": float(np.mean([x[0] for x in c])), "touches": len(c),
         "kind": "resistance" if np.mean([x[0] for x in c]) >= last else "support"}
        for c in clusters
    ]
    levels.sort(key=lambda l: (-l["touches"], abs(l["price"] - last)))
    return levels[:max_levels]


def detect_breakout(df: pd.DataFrame, lookback: int = 20, confirm_bars: int = 1, atr_buffer: float = 0.1) -> dict | None:
    """Breakout of the prior `lookback`-bar range, confirmed by `confirm_bars` closes beyond it."""
    if len(df) < lookback + confirm_bars + 1:
        return None
    ref = df.iloc[-(lookback + confirm_bars):-confirm_bars]
    recent = df.iloc[-confirm_bars:]
    a = float(atr(df).iloc[-1]) if len(df) > 20 else 0.0
    up, dn = float(ref["high"].max()) + atr_buffer * a, float(ref["low"].min()) - atr_buffer * a
    if (recent["close"] > up).all():
        return {"direction": "up", "level": up}
    if (recent["close"] < dn).all():
        return {"direction": "down", "level": dn}
    return None


def candle_patterns(df: pd.DataFrame) -> list[str]:
    """Patterns formed on the last closed candle(s)."""
    if len(df) < 3:
        return []
    c, p = df.iloc[-1], df.iloc[-2]
    body, rng = abs(c.close - c.open), c.high - c.low
    out: list[str] = []
    if rng <= 0:
        return out
    upper, lower = c.high - max(c.open, c.close), min(c.open, c.close) - c.low
    if body <= 0.1 * rng:
        out.append("doji")
    if lower >= 2 * body and upper <= 0.3 * rng and body > 0:
        out.append("hammer")
    if upper >= 2 * body and lower <= 0.3 * rng and body > 0:
        out.append("shooting_star")
    if p.close < p.open and c.close > c.open and c.close >= p.open and c.open <= p.close:
        out.append("bullish_engulfing")
    if p.close > p.open and c.close < c.open and c.close <= p.open and c.open >= p.close:
        out.append("bearish_engulfing")
    return out
