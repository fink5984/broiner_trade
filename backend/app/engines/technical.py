"""Deterministic technical analysis engine (no AI). Reproducible from candle data alone."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import indicators as ind


@dataclass
class TechnicalParams:
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    breakout_lookback: int = 20
    breakout_confirm_bars: int = 1
    use_rsi: bool = True
    use_macd: bool = True
    use_ema: bool = True
    use_breakout: bool = True
    use_patterns: bool = True
    compute_levels: bool = True   # S/R levels are for display; disabled in backtests for speed
    adx_like_trend_threshold: float = 0.25  # |ema_slow slope| / ATR over 10 bars


@dataclass
class TechnicalResult:
    score: float            # -1 (strong sell) .. +1 (strong buy)
    direction: str          # BUY / SELL / NEUTRAL
    trend_strength: float   # 0..1
    regime: str             # trending / ranging
    volatility: str         # high / low / normal
    atr: float
    components: dict = field(default_factory=dict)
    patterns: list = field(default_factory=list)
    levels: list = field(default_factory=list)
    explanation: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def analyze(df: pd.DataFrame, p: TechnicalParams | None = None) -> TechnicalResult:
    """Analyze candles (UTC-indexed, ONLY closed candles). Uses data up to and including last row."""
    p = p or TechnicalParams()
    need = max(p.ema_slow, p.macd_slow + p.macd_signal, p.breakout_lookback + 2) + 5
    if len(df) < need:
        return TechnicalResult(0.0, "NEUTRAL", 0.0, "unknown", "normal", 0.0,
                               explanation=[f"insufficient data: {len(df)} < {need} candles"])
    close = df["close"]
    comps: dict[str, float] = {}
    why: list[str] = []
    a = float(ind.atr(df, p.atr_period).iloc[-1])
    slow = ind.ema(close, p.ema_slow)
    slope = float(slow.iloc[-1] - slow.iloc[-11]) if len(slow.dropna()) > 11 else 0.0
    ts = min(1.0, abs(slope) / (a * 10 * p.adx_like_trend_threshold)) if a > 0 else 0.0
    regime = "trending" if ts >= 0.5 else "ranging"

    if p.use_ema:
        f, s = ind.ema(close, p.ema_fast).iloc[-1], ind.ema(close, p.ema_slow).iloc[-1]
        comps["ema"] = 1.0 if f > s and close.iloc[-1] > f else -1.0 if f < s and close.iloc[-1] < f else 0.0
        why.append(f"EMA{p.ema_fast}{'>' if f > s else '<'}EMA{p.ema_slow}")
    if p.use_rsi:
        r = float(ind.rsi(close, p.rsi_period).iloc[-1])
        if regime == "trending":      # momentum confirmation; extremes are not reversal signals in a trend
            comps["rsi"] = max(-1.0, min(1.0, (r - 50) / 25))
        else:                         # mean reversion at extremes when ranging
            comps["rsi"] = -1.0 if r >= p.rsi_overbought else 1.0 if r <= p.rsi_oversold else (r - 50) / 50 * 0.5
        why.append(f"RSI={r:.1f} ({regime})")
    if p.use_macd:
        m = ind.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
        h, hp = m["hist"].iloc[-1], m["hist"].iloc[-2]
        comps["macd"] = (1.0 if h > 0 else -1.0) * (1.0 if abs(h) >= abs(hp) else 0.5)
        why.append(f"MACD hist={h:.5f}")
    brk = ind.detect_breakout(df, p.breakout_lookback, p.breakout_confirm_bars) if p.use_breakout else None
    if brk:
        comps["breakout"] = 1.0 if brk["direction"] == "up" else -1.0
        why.append(f"breakout {brk['direction']} @ {brk['level']:.5f}")
    pats = ind.candle_patterns(df) if p.use_patterns else []
    bull = {"hammer", "bullish_engulfing"}
    bear = {"shooting_star", "bearish_engulfing"}
    if any(x in bull for x in pats) or any(x in bear for x in pats):
        comps["patterns"] = (1.0 if any(x in bull for x in pats) else 0.0) - (1.0 if any(x in bear for x in pats) else 0.0)
        why.append("patterns: " + ",".join(pats))

    score = sum(comps.values()) / len(comps) if comps else 0.0
    atr_series = ind.atr(df, p.atr_period).dropna()
    pct = float((atr_series.iloc[-1] > atr_series).mean()) if len(atr_series) > 30 else 0.5
    vol = "high" if pct > 0.85 else "low" if pct < 0.15 else "normal"
    direction = "BUY" if score >= 0.3 else "SELL" if score <= -0.3 else "NEUTRAL"
    return TechnicalResult(round(score, 4), direction, round(ts, 4), regime, vol, a, comps, pats,
                           ind.support_resistance(df) if p.compute_levels else [], why)
