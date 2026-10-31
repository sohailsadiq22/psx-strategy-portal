"""Indicator strategies (9-12, 21-24). Exit series are causal: evaluated at bar close, executed next open."""
from __future__ import annotations

import numpy as np

from ..base import Check, Context, Signal, cross_above, finalize
from ..indicators import rolling_pct_rank


def _ind(ctx: Context, i: int, *names) -> dict:
    return {n: (round(float(ctx.col(n)[i]), 4) if np.isfinite(ctx.col(n)[i]) else None) for n in names}


def fibonacci(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, used = [], set()
    for i in range(2, ctx.n):
        highs = piv.known_at(i, "H", lookback=p["max_leg_age_bars"])
        if not highs:
            continue
        B = highs[-1]
        lows = [x for x in piv.known_at(i, "L") if x.idx < B.idx and x.idx >= B.idx - p["max_leg_bars"]]
        if not lows or B.idx in used:
            continue
        A = min(lows, key=lambda x: x.price)
        leg = B.price - A.price
        if (B.price / A.price - 1) * 100 < p["min_leg_pct"]:
            continue
        z_hi, z_lo = B.price - leg * p["zone_top"], B.price - leg * p["zone_bottom"]
        inval = B.price - leg * p["invalidation_level"]
        since = ctx.l[B.idx + 1 : i + 1]
        if since.size and since.min() < inval:
            used.add(B.idx)
            continue
        if ctx.h[B.idx + 1 : i + 1].max(initial=0) > B.price:
            used.add(B.idx)
            continue
        touched = any(z_lo <= ctx.l[j] <= z_hi for j in (i - 1, i))
        bull = ctx.c[i] > ctx.o[i]
        above_prev = ctx.c[i] > ctx.h[i - 1]
        if not (touched and bull and above_prev):
            continue
        used.add(B.idx)
        checks = [
            Check(f"Swing leg >= {p['min_leg_pct']}% from confirmed pivots", True, f"{A.price:.2f} -> {B.price:.2f} ({(B.price / A.price - 1) * 100:.1f}%)"),
            Check(f"Retraced into {p['zone_top'] * 100:.1f}%-{p['zone_bottom'] * 100:.1f}% zone", True, f"zone {z_lo:.2f}-{z_hi:.2f}"),
            Check("Bullish candle closes above previous high", True, f"{ctx.c[i]:.2f} > {ctx.h[i - 1]:.2f}"),
            Check(f"Not below {p['invalidation_level'] * 100:.1f}% level", True, f"{inval:.2f}"),
        ]
        levels = [{"from": {"i": A.idx, "price": B.price - leg * r}, "to": {"i": i, "price": B.price - leg * r}, "label": f"{r * 100:.1f}%"} for r in (0, 0.382, 0.5, 0.618, 0.786, 1)]
        out.append(finalize(Signal(i, "Buy", "Fibonacci Retracement", checks, stop=ctx.buffer_below(inval), target=B.price,
                                   geometry={"lines": levels, "points": [{"i": A.idx, "price": A.price, "label": "A"}, {"i": B.idx, "price": B.price, "label": "B"}]})))
    return out


def supertrend_ma200(ctx: Context, p: dict) -> list[Signal]:
    d, line, sma200 = ctx.col("st_dir"), ctx.col("st_line"), ctx.col("sma200")
    lb = int(p["sma_slope_bars"])
    out = []
    for i in range(lb + 1, ctx.n):
        if not (d[i] == 1 and d[i - 1] == -1):
            continue
        rising = bool(np.isfinite(sma200[i - lb]) and sma200[i] > sma200[i - lb])
        above = bool(np.isfinite(sma200[i]) and ctx.c[i] > sma200[i])
        checks = [
            Check("Supertrend(10,3) flipped up", True, f"line {line[i]:.2f}"),
            Check("Close > SMA200", above, f"{ctx.c[i]:.2f} vs {sma200[i]:.2f}" if np.isfinite(sma200[i]) else "SMA200 n/a"),
            Check(f"SMA200 rising ({lb} bars)", rising, f"{sma200[i]:.2f} vs {sma200[i - lb]:.2f}" if np.isfinite(sma200[i - lb]) else "n/a"),
        ]
        if not (above and rising):
            continue
        out.append(finalize(Signal(i, "Buy", "Supertrend + MA200", checks, stop=float(line[i]) if p["stop_at_supertrend"] else None,
                                   indicators=_ind(ctx, i, "st_line", "sma200", "atr14"))))
    return out


def supertrend_exit(ctx: Context, p: dict) -> np.ndarray:
    d = ctx.col("st_dir")
    return np.r_[False, (d[1:] == -1) & (d[:-1] == 1)]


def donchian(ctx: Context, p: dict) -> list[Signal]:
    hh = ctx.df["high"].shift(1).rolling(p["entry_bars"], min_periods=p["entry_bars"]).max().to_numpy()
    atr = ctx.col("atr14")
    out = []
    for i in range(1, ctx.n):
        if np.isfinite(hh[i]) and ctx.c[i] > hh[i] and not (np.isfinite(hh[i - 1]) and ctx.c[i - 1] > hh[i - 1]):
            checks = [Check(f"Close above previous {p['entry_bars']}-day high (current bar excluded)", True, f"{ctx.c[i]:.2f} > {hh[i]:.2f}")]
            out.append(finalize(Signal(i, "Buy", "Donchian Breakout", checks, stop_atr=p["stop_atr_mult"] * atr[i] if np.isfinite(atr[i]) else None,
                                       indicators={"donchian_high": round(float(hh[i]), 4), **_ind(ctx, i, "atr14")},
                                       geometry={"lines": [{"from": {"i": i - p["entry_bars"], "price": float(hh[i])}, "to": {"i": i, "price": float(hh[i])}, "label": f"{p['entry_bars']}D high"}]})))
    return out


def donchian_exit(ctx: Context, p: dict) -> np.ndarray:
    ll = ctx.df["low"].shift(1).rolling(p["exit_bars"], min_periods=p["exit_bars"]).min().to_numpy()
    return np.nan_to_num(ctx.c < ll, nan=False).astype(bool)


def rsi_macd(ctx: Context, p: dict) -> list[Signal]:
    rsi, m, s, hist, sma50 = ctx.col("rsi14"), ctx.col("macd"), ctx.col("macd_signal"), ctx.col("macd_hist"), ctx.col("sma50")
    atr = ctx.col("atr14")
    w = int(p["max_bars_apart"])
    rsi_x = np.r_[False, (rsi[1:] > 50) & (rsi[:-1] <= 50)]
    macd_x = np.r_[False, (m[1:] > s[1:]) & (m[:-1] <= s[:-1])]
    out, last = [], -10**9
    for i in range(1, ctx.n):
        if not (rsi_x[i] or macd_x[i]):
            continue
        lo = max(0, i - w)
        r_bars = np.where(rsi_x[lo : i + 1])[0]
        m_bars = np.where(macd_x[lo : i + 1])[0]
        if not len(r_bars) or not len(m_bars) or i - last <= w:
            continue
        checks = [
            Check("RSI(14) crossed above 50", True, f"RSI {rsi[i]:.1f}"),
            Check(f"MACD crossed above signal within {w} bars of RSI cross", True, f"MACD {m[i]:.3f} / signal {s[i]:.3f}"),
            Check("MACD histogram > 0", bool(hist[i] > 0), f"{hist[i]:.3f}"),
            Check("Close > SMA50", bool(np.isfinite(sma50[i]) and ctx.c[i] > sma50[i]), f"{ctx.c[i]:.2f} vs {sma50[i]:.2f}"),
        ]
        if not all(c.passed for c in checks):
            continue
        last = i
        out.append(finalize(Signal(i, "Buy", "RSI + MACD", checks, stop_atr=p["stop_atr_mult"] * atr[i] if np.isfinite(atr[i]) else None,
                                   indicators=_ind(ctx, i, "rsi14", "macd", "macd_signal", "macd_hist", "sma50"))))
    return out


def rsi_macd_exit(ctx: Context, p: dict) -> np.ndarray:
    rsi, m, s = ctx.col("rsi14"), ctx.col("macd"), ctx.col("macd_signal")
    x = np.r_[False, (m[1:] < s[1:]) & (m[:-1] >= s[:-1])]
    return x | np.nan_to_num(rsi < p["exit_rsi_below"], nan=False).astype(bool)


def golden_cross(ctx: Context, p: dict) -> list[Signal]:
    a, b, atr = ctx.col("sma50"), ctx.col("sma200"), ctx.col("atr14")
    out = []
    for i in range(1, ctx.n):
        if cross_above(a, b, i):
            stop_atr = p["stop_atr_mult"] * atr[i] if p["stop_atr_mult"] and np.isfinite(atr[i]) else None
            out.append(finalize(Signal(i, "Buy", "Golden Cross", [Check("SMA50 crossed above SMA200", True, f"{a[i]:.2f} > {b[i]:.2f}")],
                                       stop_atr=stop_atr, indicators=_ind(ctx, i, "sma50", "sma200"))))
    return out


def golden_cross_exit(ctx: Context, p: dict) -> np.ndarray:
    a, b = ctx.col("sma50"), ctx.col("sma200")
    return np.r_[False, (a[1:] < b[1:]) & (a[:-1] >= b[:-1])]


def bollinger_squeeze(ctx: Context, p: dict) -> list[Signal]:
    rank = rolling_pct_rank(ctx.df["bb_width"], p["rank_bars"]).to_numpy()
    up, atr = ctx.col("bb_up"), ctx.col("atr14")
    out = []
    for i in range(1, ctx.n):
        if not cross_above(ctx.c, up, i):
            continue
        lo = max(0, i - p["squeeze_recent_bars"])
        win = rank[lo:i]
        sq = bool(win.size and np.nanmin(win) <= p["squeeze_pct"] / 100) if np.isfinite(win).any() else False
        checks = [
            Check(f"Bandwidth in lowest {p['squeeze_pct']}% of last {p['rank_bars']} bars (within {p['squeeze_recent_bars']} bars)", sq,
                  f"min percentile {np.nanmin(win) * 100:.0f}%" if np.isfinite(win).any() else "n/a"),
            Check("Close above upper band", True, f"{ctx.c[i]:.2f} > {up[i]:.2f}"),
            ctx.vol_check(i),
        ]
        if not sq:
            continue
        out.append(finalize(Signal(i, "Buy", "Bollinger Squeeze Breakout", checks, stop_atr=p["stop_atr_mult"] * atr[i] if np.isfinite(atr[i]) else None,
                                   indicators=_ind(ctx, i, "bb_up", "bb_mid", "bb_lo", "bb_width"))))
    return out


def bollinger_exit(ctx: Context, p: dict) -> np.ndarray:
    return np.nan_to_num(ctx.c < ctx.col("bb_mid"), nan=False).astype(bool)


def high_52w(ctx: Context, p: dict) -> list[Signal]:
    n = int(p["lookback_bars"])
    hh = ctx.df["high"].shift(1).rolling(n, min_periods=n).max().to_numpy()
    atr = ctx.col("atr14")
    out = []
    for i in range(1, ctx.n):
        if np.isfinite(hh[i]) and ctx.c[i] > hh[i] and not (np.isfinite(hh[i - 1]) and ctx.c[i - 1] > hh[i - 1]):
            checks = [Check(f"Close above previous {n}-bar high", True, f"{ctx.c[i]:.2f} > {hh[i]:.2f}"), ctx.vol_check(i)]
            out.append(finalize(Signal(i, "Buy", "52-Week High Breakout", checks, stop_atr=p["stop_atr_mult"] * atr[i] if np.isfinite(atr[i]) else None,
                                       indicators={"high_252": round(float(hh[i]), 4)},
                                       geometry={"lines": [{"from": {"i": i - n, "price": float(hh[i])}, "to": {"i": i, "price": float(hh[i])}, "label": "52W high"}]})))
    return out


def high_52w_exit(ctx: Context, p: dict) -> np.ndarray:
    return np.nan_to_num(ctx.c < ctx.col("sma50"), nan=False).astype(bool)


def nr7_inside(ctx: Context, p: dict) -> list[Signal]:
    rng = ctx.h - ctx.l
    out, consumed = [], -1
    for k in range(7, ctx.n):
        nr7 = rng[k] < rng[k - 6 : k].min()
        inside = ctx.h[k] <= ctx.h[k - 1] and ctx.l[k] >= ctx.l[k - 1]
        mode = p["mode"]
        ok = (nr7 if mode == "nr7" else inside if mode == "inside" else (nr7 or inside))
        if not ok or k <= consumed:
            continue
        for j in range(k + 1, min(ctx.n, k + 1 + p["max_bars_to_breakout"])):
            if ctx.l[j] < ctx.l[k]:
                break
            if ctx.c[j] > ctx.h[k]:
                consumed = j
                checks = [Check("Setup bar is NR7" if nr7 else "Setup bar is an inside bar", True, f"range {rng[k]:.2f} on {ctx.date(k)}"),
                          Check("Close above setup bar high", True, f"{ctx.c[j]:.2f} > {ctx.h[k]:.2f}")]
                out.append(finalize(Signal(j, "Buy", "NR7 / Inside Bar Breakout", checks, stop=ctx.buffer_below(float(ctx.l[k])), target_r=p["target_r"],
                                           geometry={"box": {"from": k, "to": k, "low": float(ctx.l[k]), "high": float(ctx.h[k])}})))
                break
    return out
