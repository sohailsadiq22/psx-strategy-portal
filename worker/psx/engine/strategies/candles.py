"""Candlestick strategies (5-8, 18-20) with configurable context filter and next-candle confirmation."""
from __future__ import annotations

import numpy as np

from ..base import Check, Context, Signal, finalize


def _body(ctx, k):
    return abs(ctx.c[k] - ctx.o[k])


def _avg_body(ctx, k, n=10):
    s = max(0, k - n)
    return float(np.mean(np.abs(ctx.c[s:k] - ctx.o[s:k]))) if k > s else 0.0


def context_checks(ctx: Context, k: int) -> list[Check]:
    p = ctx.params
    sma = ctx.col(f"sma{p['context_sma']}") if f"sma{p['context_sma']}" in ctx.df else ctx.col("sma20")
    lb = int(p["context_lookback"])
    down = bool(k >= lb and np.isfinite(sma[k]) and ctx.c[k] < sma[k] and ctx.c[k] < ctx.c[k - lb])
    low20 = float(ctx.l[max(0, k - 19) : k + 1].min())
    tol = 1 + float(p["context_support_pct"]) / 100
    near_low = bool(ctx.l[k] <= low20 * tol)
    sup = [x for x in ctx.pivots().known_at(k, "L") if x.price <= ctx.l[k] * tol and x.price >= ctx.l[k] / tol and x.idx < k]
    near = near_low or bool(sup)
    return [
        Check(f"Prior downtrend (close < SMA{p['context_sma']} and < close {lb} bars ago)", down,
              f"close {ctx.c[k]:.2f}, SMA {sma[k]:.2f}, {lb} bars ago {ctx.c[k - lb]:.2f}" if k >= lb and np.isfinite(sma[k]) else "insufficient history"),
        Check(f"Near support (within {p['context_support_pct']}% of 20-day low or confirmed support)", near,
              f"low {ctx.l[k]:.2f}, 20-day low {low20:.2f}" + (f", support pivot {sup[-1].price:.2f}" if sup else "")),
    ]


def _emit(ctx: Context, k: int, first: int, name: str, pattern_checks: list[Check]) -> list[Signal]:
    """Pattern completed at bar k (pattern spans first..k). Returns Buy at confirmation bar or Watch."""
    p = ctx.params
    checks = pattern_checks + context_checks(ctx, first)
    if not all(c.passed for c in checks if c.required):
        return []
    pat_low, pat_high = float(ctx.l[first : k + 1].min()), float(ctx.h[k])
    geom = {"points": [{"i": k, "price": pat_low, "label": name}], "box": {"from": first, "to": k, "low": pat_low, "high": float(ctx.h[first : k + 1].max())}}
    stop = ctx.buffer_below(pat_low)
    if p["candle_confirmation"]:
        j = k + 1
        if j >= ctx.n:
            return [finalize(Signal(k, "Watch", name, checks + [Check("Next candle closes above pattern high", False, "awaiting next candle")],
                                    stop=stop, target_r=float(p["candle_target_r"]), geometry=geom))]
        ok = bool(ctx.c[j] > pat_high)
        if not ok:
            return []
        checks = checks + [Check("Next candle closes above pattern high", True, f"{ctx.c[j]:.2f} > {pat_high:.2f}")]
        return [finalize(Signal(j, "Buy", name, checks + [ctx.vol_check(j, required=False)], stop=stop, target_r=float(p["candle_target_r"]), geometry=geom))]
    return [finalize(Signal(k, "Buy", name, checks + [ctx.vol_check(k, required=False)], stop=stop, target_r=float(p["candle_target_r"]), geometry=geom))]


def _scan(ctx: Context, need: int, test, name: str) -> list[Signal]:
    out = []
    for k in range(need, ctx.n):
        r = test(ctx, k)
        if r:
            first, checks = r
            out += _emit(ctx, k, first, name, checks)
    return out


def bullish_engulfing(ctx: Context, p: dict) -> list[Signal]:
    def t(ctx, k):
        o, c = ctx.o, ctx.c
        if c[k - 1] < o[k - 1] and c[k] > o[k] and o[k] <= c[k - 1] and c[k] >= o[k - 1] and _body(ctx, k) > _body(ctx, k - 1):
            return k - 1, [Check("Bullish body engulfs prior bearish body", True, f"{o[k]:.2f}-{c[k]:.2f} covers {c[k - 1]:.2f}-{o[k - 1]:.2f}")]
    return _scan(ctx, 2, t, "Bullish Engulfing")


def hammer(ctx: Context, p: dict) -> list[Signal]:
    def t(ctx, k):
        o, h, l, c = ctx.o[k], ctx.h[k], ctx.l[k], ctx.c[k]
        rng = h - l
        if rng <= 0:
            return None
        body = abs(c - o)
        lower, upper = min(o, c) - l, h - max(o, c)
        if lower >= p["min_lower_shadow_x_body"] * max(body, 1e-9) and upper <= p["max_upper_shadow_pct"] / 100 * rng and min(o, c) >= l + rng * 2 / 3:
            return k, [Check(f"Lower shadow >= {p['min_lower_shadow_x_body']}x body, upper <= {p['max_upper_shadow_pct']}% of range, body in top third", True,
                             f"body {body:.2f}, lower {lower:.2f}, upper {upper:.2f}")]
    return _scan(ctx, 1, t, "Hammer")


def morning_star(ctx: Context, p: dict) -> list[Signal]:
    def t(ctx, k):
        o, c = ctx.o, ctx.c
        a, b = k - 2, k - 1
        b1 = _body(ctx, a)
        if not (c[a] < o[a] and b1 >= p["large_body_x_avg"] * _avg_body(ctx, a) and b1 > 0):
            return None
        if _body(ctx, b) > p["small_body_x_first"] * b1:
            return None
        mid = (o[a] + c[a]) / 2
        if c[k] > o[k] and c[k] > mid:
            return a, [Check("Large bearish, small body, bullish close above first midpoint", True, f"close {c[k]:.2f} > midpoint {mid:.2f}")]
    return _scan(ctx, 12, t, "Morning Star")


def piercing_line(ctx: Context, p: dict) -> list[Signal]:
    def t(ctx, k):
        o, c, l = ctx.o, ctx.c, ctx.l
        if not (c[k - 1] < o[k - 1] and c[k] > o[k]):
            return None
        ref = l[k - 1] if p["open_below"] == "prior_low" else c[k - 1]
        mid = (o[k - 1] + c[k - 1]) / 2
        if o[k] < ref and mid < c[k] < o[k - 1]:
            return k - 1, [Check(f"Opens below prior {'low' if p['open_below'] == 'prior_low' else 'close'}, closes above prior midpoint but below prior open", True,
                                 f"open {o[k]:.2f} < {ref:.2f}; close {c[k]:.2f} in ({mid:.2f}, {o[k - 1]:.2f})")]
    return _scan(ctx, 2, t, "Piercing Line")


def bullish_harami(ctx: Context, p: dict) -> list[Signal]:
    def t(ctx, k):
        o, c = ctx.o, ctx.c
        b1 = _body(ctx, k - 1)
        if not (c[k - 1] < o[k - 1] and b1 >= p["large_body_x_avg"] * _avg_body(ctx, k - 1) and b1 > 0):
            return None
        if c[k] > o[k] and o[k] >= c[k - 1] and c[k] <= o[k - 1] and _body(ctx, k) <= p["max_body_x_prior"] * b1:
            return k - 1, [Check("Small bullish body inside prior large bearish body", True, f"{o[k]:.2f}-{c[k]:.2f} inside {c[k - 1]:.2f}-{o[k - 1]:.2f}")]
    return _scan(ctx, 12, t, "Bullish Harami")


def three_white_soldiers(ctx: Context, p: dict) -> list[Signal]:
    def t(ctx, k):
        o, c = ctx.o, ctx.c
        js = (k - 2, k - 1, k)
        if not all(c[j] > o[j] for j in js):
            return None
        if not (c[k - 1] > c[k - 2] and c[k] > c[k - 1]):
            return None
        if not all(o[j - 1] <= o[j] <= c[j - 1] for j in (k - 1, k)):
            return None
        return k - 2, [Check("Three bullish candles, higher closes, each opens within prior body", True, " -> ".join(f"{c[j]:.2f}" for j in js))]
    return _scan(ctx, 3, t, "Three White Soldiers")


def tweezer_bottom(ctx: Context, p: dict) -> list[Signal]:
    def t(ctx, k):
        o, c, l = ctx.o, ctx.c, ctx.l
        if c[k - 1] < o[k - 1] and c[k] > o[k] and abs(l[k] - l[k - 1]) / min(l[k], l[k - 1]) * 100 <= p["low_tolerance_pct"]:
            return k - 1, [Check(f"Lows within {p['low_tolerance_pct']}%, bearish then bullish", True, f"{l[k - 1]:.2f} / {l[k]:.2f}")]
    return _scan(ctx, 2, t, "Tweezer Bottom")
