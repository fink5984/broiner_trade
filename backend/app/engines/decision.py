"""Decision Engine: combines technical / news / macro signals into BUY, SELL, HOLD, CLOSE, NO_TRADE.

Signals are normalised to [-1, +1]. The engine never talks to a broker and never sizes trades:
that is the Risk Engine's job. LLM output enters only as validated, typed signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone


@dataclass
class DecisionConfig:
    w_technical: float = 50.0
    w_news: float = 25.0
    w_macro: float = 25.0
    min_signal: float = 0.35            # |weighted score| required
    min_agreeing_engines: int = 2       # engines (with non-zero signal) agreeing with direction
    veto_news_against: float = 0.7      # news engine strongly opposing -> veto
    veto_macro_against: float = 0.7
    max_signal_age_minutes: float = 60.0
    min_cost_ratio: float = 2.0         # expected move must exceed costs by this factor
    cooldown_minutes: float = 60.0      # no re-entry on same asset within window

    def validate(self) -> None:
        total = self.w_technical + self.w_news + self.w_macro
        if abs(total - 100.0) > 1e-6:
            raise ValueError(f"engine weights must sum to 100 (got {total})")
        if min(self.w_technical, self.w_news, self.w_macro) < 0:
            raise ValueError("negative weight")


@dataclass
class EngineSignal:
    name: str                  # technical / news / macro
    score: float               # -1..+1
    as_of: datetime            # when the underlying data became available (UTC)
    valid: bool = True         # False: validation failed / unavailable -> contributes nothing
    ref_ids: list[str] = field(default_factory=list)


@dataclass
class Decision:
    action: str
    asset: str
    timestamp: datetime
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    contributions: dict = field(default_factory=dict)
    idempotency_key: str = ""

    def as_dict(self):
        return asdict(self)


def decide(asset: str, now: datetime, signals: dict[str, EngineSignal], cfg: DecisionConfig,
           open_side: str | None = None, expected_move: float | None = None, est_cost: float | None = None,
           last_entry_at: datetime | None = None, event_block: str | None = None,
           bar_time: datetime | None = None) -> Decision:
    cfg.validate()
    weights = {"technical": cfg.w_technical, "news": cfg.w_news, "macro": cfg.w_macro}
    dec = Decision("NO_TRADE", asset, now)
    usable: dict[str, EngineSignal] = {}
    for name, w in weights.items():
        s = signals.get(name)
        if s is None or not s.valid:
            dec.blockers.append(f"{name}: unavailable/invalid -> ignored")
            continue
        age = (now - s.as_of).total_seconds() / 60
        if age < -1:
            dec.blockers.append(f"{name}: signal timestamp in the future (look-ahead guard)")
            continue
        if age > cfg.max_signal_age_minutes and name != "macro":
            dec.blockers.append(f"{name}: stale ({age:.0f} min)")
            continue
        usable[name] = s
    if "technical" not in usable:
        dec.blockers.append("technical analysis is mandatory")
        return dec

    # missing engines contribute 0 (they never dilute by renormalising)
    score = sum(weights[n] / 100.0 * usable[n].score for n in usable)
    dec.score = round(score, 4)
    dec.contributions = {n: round(weights[n] / 100.0 * usable[n].score, 4) for n in usable}
    direction = "BUY" if score > 0 else "SELL"

    # existing position: exit logic
    if open_side:
        opposite = (open_side == "BUY" and score <= -cfg.min_signal) or (open_side == "SELL" and score >= cfg.min_signal)
        if opposite:
            dec.action = "CLOSE"
            dec.reasons.append(f"signal reversed against {open_side} (score {score:+.2f})")
        else:
            dec.action = "HOLD"
            dec.reasons.append("position open; no reversal signal")
        dec.idempotency_key = _key(asset, dec.action, bar_time or now)
        return dec

    if event_block:
        dec.blockers.append(event_block)
    if abs(score) < cfg.min_signal:
        dec.blockers.append(f"weighted score {score:+.2f} below threshold {cfg.min_signal}")
    agree = sum(1 for s in usable.values() if s.score * (1 if direction == "BUY" else -1) > 0.1)
    if agree < cfg.min_agreeing_engines:
        dec.blockers.append(f"only {agree} engine(s) agree, need {cfg.min_agreeing_engines}")
    sign = 1 if direction == "BUY" else -1
    for n, lim in (("news", cfg.veto_news_against), ("macro", cfg.veto_macro_against)):
        if n in usable and usable[n].score * sign <= -lim:
            dec.blockers.append(f"veto: {n} strongly opposes {direction}")
    if last_entry_at and (now - last_entry_at) < timedelta(minutes=cfg.cooldown_minutes):
        dec.blockers.append("cooldown after recent entry")
    if expected_move is not None and est_cost is not None and expected_move < est_cost * cfg.min_cost_ratio:
        dec.blockers.append(f"expected move {expected_move:.5f} < {cfg.min_cost_ratio}x costs {est_cost:.5f}")

    hard = [x for x in dec.blockers if not x.endswith("-> ignored") and "stale" not in x and "look-ahead" not in x]
    if hard:
        dec.action = "HOLD" if abs(score) < cfg.min_signal else "NO_TRADE"
        return dec
    dec.action = direction
    dec.reasons.append(f"weighted score {score:+.2f}, engines agreeing: {agree}")
    dec.idempotency_key = _key(asset, direction, bar_time or now)
    return dec


def _key(asset: str, action: str, t: datetime) -> str:
    """Same asset+action+bar always yields the same key -> duplicate entries are rejected downstream."""
    return f"{asset}:{action}:{t.astimezone(timezone.utc).strftime('%Y%m%d%H%M')}"


class DecisionLedger:
    """Remembers idempotency keys so the same event evaluated twice cannot open twice."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def claim(self, key: str) -> bool:
        if not key or key in self._seen:
            return False
        self._seen.add(key)
        return True
