"""Swing pivots confirmed only after N bars on each side.

A pivot at bar p is known only at bar p + N (the confirmation bar). Strategies evaluating
bar i may only use pivots with confirm_idx <= i.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Pivot:
    idx: int
    confirm_idx: int
    price: float
    kind: str  # 'H' or 'L'


def find_pivots(df: pd.DataFrame, n: int = 5) -> list[Pivot]:
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    m = len(df)
    out: list[Pivot] = []
    for p in range(n, m - n):
        wh, wl = h[p - n : p + n + 1], l[p - n : p + n + 1]
        if h[p] == wh.max() and np.argmax(wh) == n:
            out.append(Pivot(p, p + n, float(h[p]), "H"))
        if l[p] == wl.min() and np.argmin(wl) == n:
            out.append(Pivot(p, p + n, float(l[p]), "L"))
    out.sort(key=lambda x: (x.confirm_idx, x.idx))
    return out


class PivotIndex:
    """Fast access to pivots confirmed by a given bar."""

    def __init__(self, pivots: list[Pivot]):
        self.pivots = pivots
        self.confirm = np.array([p.confirm_idx for p in pivots], dtype=int)

    def known_at(self, i: int, kind: str | None = None, lookback: int | None = None) -> list[Pivot]:
        k = int(np.searchsorted(self.confirm, i, side="right"))
        ps = self.pivots[:k]
        if kind:
            ps = [p for p in ps if p.kind == kind]
        if lookback is not None:
            ps = [p for p in ps if p.idx >= i - lookback]
        return sorted(ps, key=lambda p: p.idx)
