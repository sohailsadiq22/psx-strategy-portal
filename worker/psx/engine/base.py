"""Strategy framework: signals, confirmation checklists, registry."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from .indicators import add_standard
from .pivots import PivotIndex, find_pivots


@dataclass
class Check:
    name: str
    passed: bool
    value: str = ""
    required: bool = True


@dataclass
class Signal:
    idx: int
    action: str  # 'Buy' | 'Watch'
    pattern: str
    checks: list[Check]
    stop: float | None = None
    stop_atr: float | None = None  # if set, stop = entry - stop_atr (computed from actual entry)
    target: float | None = None
    target_r: float | None = None  # if set, target = entry + target_r * (entry - stop)
    geometry: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)
    reason: str = ""
    strategy: str = ""

    @property
    def confirmed(self) -> bool:
        return all(c.passed for c in self.checks if c.required)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["confirmed"] = self.confirmed
        return d


@dataclass
class StrategyDef:
    key: str
    name: str
    number: int
    tier: int
    category: str
    entry_rule: str
    confirmation_rule: str
    exit_rule: str
    invalidation_rule: str
    defaults: dict
    detect: Callable[["Context"], list[Signal]]
    exit_signal: Callable[["Context"], np.ndarray] | None = None

    def doc(self) -> dict:
        return {
            "key": self.key, "name": self.name, "number": self.number, "tier": self.tier,
            "category": self.category, "entry_rule": self.entry_rule,
            "confirmation_rule": self.confirmation_rule, "exit_rule": self.exit_rule,
            "invalidation_rule": self.invalidation_rule, "defaults": self.defaults,
            "has_indicator_exit": self.exit_signal is not None,
        }


GLOBAL_DEFAULTS = {
    "pivot_n": 5,
    "volume_mult": 1.5,
    "stop_buffer_pct": 0.5,
    "context_sma": 20,
    "context_lookback": 10,
    "context_support_pct": 3.0,
    "candle_confirmation": True,
    "candle_target_r": 2.0,
}


class Context:
    """Per-symbol evaluation context. Indicators are causal; pivots carry confirmation bars."""

    def __init__(self, df: pd.DataFrame, params: dict | None = None):
        self.df = df.reset_index(drop=True).copy()
        if "sma200" not in self.df:
            add_standard(self.df)
        self.params = {**GLOBAL_DEFAULTS, **(params or {})}
        self._pivots: dict[int, PivotIndex] = {}
        d = self.df
        self.o, self.h, self.l, self.c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.v = d["volume"].to_numpy(float)
        self.n = len(d)

    def pivots(self, n: int | None = None) -> PivotIndex:
        n = int(n or self.params["pivot_n"])
        if n not in self._pivots:
            self._pivots[n] = PivotIndex(find_pivots(self.df, n))
        return self._pivots[n]

    def col(self, name: str) -> np.ndarray:
        return self.df[name].to_numpy(float)

    def date(self, i: int) -> str:
        return str(pd.Timestamp(self.df["date"].iloc[i]).date())

    def vol_check(self, i: int, mult: float | None = None, required: bool = True) -> Check:
        mult = float(mult if mult is not None else self.params["volume_mult"])
        avg = self.col("vol_avg20")[i]
        ok = bool(np.isfinite(avg) and avg > 0 and self.v[i] >= mult * avg)
        val = f"{self.v[i]:,.0f} vs {mult}x avg {avg:,.0f}" if np.isfinite(avg) else "no 20-day average"
        return Check(f"Volume >= {mult}x 20-day average", ok, val, required)

    def buffer_below(self, price: float) -> float:
        return price * (1 - float(self.params["stop_buffer_pct"]) / 100)


def param_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]


def cross_above(a: np.ndarray, b: np.ndarray | float, i: int) -> bool:
    bi = b[i] if isinstance(b, np.ndarray) else b
    bp = b[i - 1] if isinstance(b, np.ndarray) else b
    return bool(i > 0 and np.isfinite(bi) and np.isfinite(bp) and a[i] > bi and a[i - 1] <= bp)


def finalize(sig: Signal) -> Signal:
    """A Buy is only allowed when every required confirmation passes."""
    if sig.action == "Buy" and not sig.confirmed:
        sig.action = "Watch"
    return sig


def describe(sig: Signal, name: str) -> str:
    lines = [f"{sig.pattern} detected ({name})."]
    req = [c for c in sig.checks if c.required]
    lines.append("Pattern confirmed." if sig.confirmed else "Confirmation INCOMPLETE: " + ", ".join(c.name for c in req if not c.passed) + ".")
    for c in sig.checks:
        if "Volume" in c.name:
            lines.append(f"Volume confirmation: {'PRESENT' if c.passed else 'ABSENT'}.")
        if "support" in c.name.lower() and c.passed:
            lines.append("Near support.")
    return " ".join(lines)


def dated(obj, ctx: "Context"):
    """Replace bar indices in signal geometry with ISO dates so charts can render any window of the series."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "i" and isinstance(v, (int, np.integer)):
                out["date"] = ctx.date(int(v))
            elif k in ("from", "to") and isinstance(v, (int, np.integer)):
                out[k] = ctx.date(int(v))
            else:
                out[k] = dated(v, ctx)
        return out
    if isinstance(obj, list):
        return [dated(x, ctx) for x in obj]
    return obj
