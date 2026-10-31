"""Chart pattern strategies (1-4, 13-17). All pivots used are confirmed at or before the signal bar."""
from __future__ import annotations

import numpy as np

from ..base import Check, Context, Signal, cross_above, finalize


def _pct(a: float, b: float) -> float:
    return abs(a - b) / min(a, b) * 100


def double_bottom(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, used = [], set()
    for i in range(1, ctx.n):
        lows = piv.known_at(i, "L", lookback=p["max_bars_between"] + p["max_bars_to_breakout"] + 10)
        if len(lows) < 2:
            continue
        for a_i in range(len(lows) - 2, max(-1, len(lows) - 5), -1):
            L1, L2 = lows[a_i], lows[-1]
            key = (L1.idx, L2.idx)
            if key in used:
                continue
            gap = L2.idx - L1.idx
            if not (p["min_bars_between"] <= gap <= p["max_bars_between"]):
                continue
            if _pct(L1.price, L2.price) > p["lows_tolerance_pct"]:
                continue
            peak = float(ctx.h[L1.idx : L2.idx + 1].max())
            peak_i = L1.idx + int(np.argmax(ctx.h[L1.idx : L2.idx + 1]))
            low = min(L1.price, L2.price)
            if peak < max(L1.price, L2.price) * (1 + p["min_peak_pct"] / 100):
                continue
            if i - L2.idx > p["max_bars_to_breakout"]:
                continue
            if ctx.l[L2.idx + 1 : i + 1].min(initial=np.inf) < low:
                used.add(key)
                continue
            if not cross_above(ctx.c, peak, i):
                continue
            used.add(key)
            height = peak - low
            checks = [
                Check("Two confirmed pivot lows within tolerance", True, f"{L1.price:.2f} / {L2.price:.2f} ({_pct(L1.price, L2.price):.2f}%)"),
                Check(f"Lows {p['min_bars_between']}-{p['max_bars_between']} bars apart", True, f"{gap} bars"),
                Check(f"Middle peak >= {p['min_peak_pct']}% above lows", True, f"{peak:.2f} ({(peak / max(L1.price, L2.price) - 1) * 100:.1f}%)"),
                Check("Close above middle peak", True, f"close {ctx.c[i]:.2f} > {peak:.2f}"),
                ctx.vol_check(i, required=False),
            ]
            out.append(finalize(Signal(
                i, "Buy", "Double Bottom", checks, stop=ctx.buffer_below(low),
                target=peak + height * p["target_pct_of_height"] / 100,
                geometry={"points": [{"i": L1.idx, "price": L1.price, "label": "L1"}, {"i": peak_i, "price": peak, "label": "Peak"}, {"i": L2.idx, "price": L2.price, "label": "L2"}],
                          "lines": [{"from": {"i": L1.idx, "price": peak}, "to": {"i": i, "price": peak}, "label": "Neckline"}]},
            )))
            break
    return out


def ascending_triangle(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, last_level = [], None
    for i in range(1, ctx.n):
        highs = piv.known_at(i, "H", lookback=p["max_bars"])
        if len(highs) < 2:
            continue
        ref = highs[-1]
        touches = [h for h in highs if _pct(h.price, ref.price) <= p["resistance_tolerance_pct"]]
        if len(touches) < 2:
            continue
        res = max(t.price for t in touches)
        start = touches[0].idx
        length = i - start
        if not (p["min_bars"] <= length <= p["max_bars"]):
            continue
        lows = [l for l in piv.known_at(i, "L") if l.idx > start]
        if len(lows) < 2:
            continue
        rising = all(lows[k].price > lows[k - 1].price for k in range(1, len(lows)))
        if not rising or not cross_above(ctx.c, res, i):
            continue
        if last_level is not None and abs(last_level - res) < 1e-9:
            continue
        last_level = res
        vc = ctx.vol_check(i)
        checks = [
            Check(f"Flat resistance: >= 2 touches within {p['resistance_tolerance_pct']}%", True, f"{len(touches)} touches near {res:.2f}"),
            Check(">= 2 rising lows", True, " < ".join(f"{l.price:.2f}" for l in lows[-3:])),
            Check(f"Pattern {p['min_bars']}-{p['max_bars']} bars", True, f"{length} bars"),
            Check("Close above resistance", True, f"{ctx.c[i]:.2f} > {res:.2f}"),
            vc,
        ]
        out.append(finalize(Signal(
            i, "Buy", "Ascending Triangle", checks, stop=ctx.buffer_below(lows[-1].price),
            target=res + (res - lows[0].price),
            geometry={"lines": [{"from": {"i": start, "price": res}, "to": {"i": i, "price": res}, "label": "Resistance"},
                                {"from": {"i": lows[0].idx, "price": lows[0].price}, "to": {"i": lows[-1].idx, "price": lows[-1].price}, "label": "Rising lows"}],
                      "points": [{"i": t.idx, "price": t.price, "label": "R"} for t in touches] + [{"i": l.idx, "price": l.price, "label": "L"} for l in lows]},
        )))
    return out


def bull_flag(ctx: Context, p: dict) -> list[Signal]:
    out, last_top = [], -1
    for i in range(p["min_flag_bars"] + 2, ctx.n):
        for f in range(p["min_flag_bars"], p["max_flag_bars"] + 1):
            t = i - 1 - f
            if t < p["max_pole_bars"] or t == last_top:
                continue
            if ctx.h[t] < ctx.h[t : i].max():
                continue
            w0 = t - p["max_pole_bars"]
            b = w0 + int(np.argmin(ctx.l[w0:t]))
            pole = ctx.h[t] - ctx.l[b]
            gain = ctx.h[t] / ctx.l[b] - 1
            if gain * 100 < p["min_pole_gain_pct"]:
                continue
            flag_low = ctx.l[t + 1 : i].min()
            flag_high = ctx.h[t + 1 : i].max()
            retr = (ctx.h[t] - flag_low) / pole
            if retr * 100 > p["max_retrace_pct"]:
                continue
            vol_flag, vol_pole = ctx.v[t + 1 : i].mean(), ctx.v[b : t + 1].mean()
            if not cross_above(ctx.c, flag_high, i):
                continue
            last_top = t
            checks = [
                Check(f"Pole gain >= {p['min_pole_gain_pct']}% in <= {p['max_pole_bars']} bars", True, f"{gain * 100:.1f}% in {t - b} bars"),
                Check(f"Flag {p['min_flag_bars']}-{p['max_flag_bars']} bars", True, f"{f} bars"),
                Check(f"Flag retrace <= {p['max_retrace_pct']}% of pole", True, f"{retr * 100:.1f}%"),
                Check("Volume declining in flag", bool(vol_flag < vol_pole), f"flag avg {vol_flag:,.0f} vs pole avg {vol_pole:,.0f}"),
                Check("Close above flag high", True, f"{ctx.c[i]:.2f} > {flag_high:.2f}"),
            ]
            out.append(finalize(Signal(
                i, "Buy", "Bull Flag", checks, stop=ctx.buffer_below(flag_low), target=flag_high + pole,
                geometry={"lines": [{"from": {"i": b, "price": float(ctx.l[b])}, "to": {"i": t, "price": float(ctx.h[t])}, "label": "Pole"},
                                    {"from": {"i": t + 1, "price": float(flag_high)}, "to": {"i": i, "price": float(flag_high)}, "label": "Flag high"},
                                    {"from": {"i": t + 1, "price": float(flag_low)}, "to": {"i": i, "price": float(flag_low)}, "label": "Flag low"}]},
            )))
            break
    return out


def cup_handle(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, used = [], set()
    for i in range(1, ctx.n):
        highs = piv.known_at(i, "H", lookback=p["max_cup_bars"] + p["max_handle_bars"] + 5)
        if len(highs) < 2:
            continue
        R = highs[-1]
        h_len = i - 1 - R.idx
        if not (p["min_handle_bars"] <= h_len <= p["max_handle_bars"]):
            continue
        for Lr in reversed(highs[:-1]):
            cup_len = R.idx - Lr.idx
            if cup_len < p["min_cup_bars"]:
                continue
            if cup_len > p["max_cup_bars"]:
                break
            if (Lr.idx, R.idx) in used or _pct(Lr.price, R.price) > p["rim_tolerance_pct"]:
                continue
            if ctx.h[Lr.idx + 1 : R.idx].max(initial=0) > max(Lr.price, R.price):
                continue
            bottom_i = Lr.idx + int(np.argmin(ctx.l[Lr.idx : R.idx + 1]))
            bottom = float(ctx.l[bottom_i])
            depth = (Lr.price - bottom) / Lr.price * 100
            if not (p["min_depth_pct"] <= depth <= p["max_depth_pct"]):
                continue
            handle_low = float(ctx.l[R.idx + 1 : i].min())
            handle_high = float(ctx.h[R.idx : i].max())
            retr = (R.price - handle_low) / (R.price - bottom) * 100
            if retr > p["max_handle_retrace_pct"]:
                continue
            if not cross_above(ctx.c, handle_high, i):
                continue
            used.add((Lr.idx, R.idx))
            checks = [
                Check(f"Cup depth {p['min_depth_pct']}-{p['max_depth_pct']}%", True, f"{depth:.1f}%"),
                Check(f"Cup {p['min_cup_bars']}-{p['max_cup_bars']} bars", True, f"{cup_len} bars"),
                Check(f"Right rim within {p['rim_tolerance_pct']}% of left rim", True, f"{Lr.price:.2f} / {R.price:.2f}"),
                Check(f"Handle {p['min_handle_bars']}-{p['max_handle_bars']} bars, retrace <= {p['max_handle_retrace_pct']}%", True, f"{h_len} bars, {retr:.1f}%"),
                Check("Close above handle high", True, f"{ctx.c[i]:.2f} > {handle_high:.2f}"),
                ctx.vol_check(i),
            ]
            out.append(finalize(Signal(
                i, "Buy", "Cup & Handle", checks, stop=ctx.buffer_below(handle_low), target=handle_high + (Lr.price - bottom),
                geometry={"points": [{"i": Lr.idx, "price": Lr.price, "label": "Left rim"}, {"i": bottom_i, "price": bottom, "label": "Bottom"}, {"i": R.idx, "price": R.price, "label": "Right rim"}],
                          "lines": [{"from": {"i": Lr.idx, "price": handle_high}, "to": {"i": i, "price": handle_high}, "label": "Breakout"}]},
            )))
            break
    return out


def triple_bottom(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, used = [], set()
    for i in range(1, ctx.n):
        lows = piv.known_at(i, "L", lookback=p["max_bars"] + p["max_bars_to_breakout"])
        if len(lows) < 3:
            continue
        L1, L2, L3 = lows[-3:]
        key = (L1.idx, L3.idx)
        if key in used or L3.idx - L1.idx > p["max_bars"] or min(L2.idx - L1.idx, L3.idx - L2.idx) < p["min_bars_between"]:
            continue
        prices = [L1.price, L2.price, L3.price]
        if (max(prices) / min(prices) - 1) * 100 > p["lows_tolerance_pct"]:
            continue
        res = float(ctx.h[L1.idx : L3.idx + 1].max())
        low = min(prices)
        if res < max(prices) * (1 + p["min_peak_pct"] / 100) or i - L3.idx > p["max_bars_to_breakout"]:
            continue
        if ctx.l[L3.idx + 1 : i + 1].min(initial=np.inf) < low:
            used.add(key)
            continue
        if not cross_above(ctx.c, res, i):
            continue
        used.add(key)
        checks = [
            Check(f"Three confirmed pivot lows within {p['lows_tolerance_pct']}%", True, " / ".join(f"{x:.2f}" for x in prices)),
            Check("Close above highest peak between lows", True, f"{ctx.c[i]:.2f} > {res:.2f}"),
            ctx.vol_check(i, required=False),
        ]
        out.append(finalize(Signal(
            i, "Buy", "Triple Bottom", checks, stop=ctx.buffer_below(low), target=res + (res - low) * p["target_pct_of_height"] / 100,
            geometry={"points": [{"i": x.idx, "price": x.price, "label": f"L{k + 1}"} for k, x in enumerate((L1, L2, L3))],
                      "lines": [{"from": {"i": L1.idx, "price": res}, "to": {"i": i, "price": res}, "label": "Resistance"}]},
        )))
    return out


def rounding_bottom(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, used = [], set()
    for i in range(1, ctx.n):
        highs = piv.known_at(i, "H", lookback=p["max_bars"])
        for Lr in reversed(highs):
            w = i - Lr.idx
            if w < p["min_bars"]:
                continue
            if Lr.idx in used:
                break
            if ctx.h[Lr.idx + 1 : i].max(initial=0) > Lr.price or not cross_above(ctx.c, Lr.price, i):
                continue
            y = ctx.c[Lr.idx : i]
            x = np.linspace(-1, 1, len(y))
            a, b, c0 = np.polyfit(x, y, 2)
            fit = a * x * x + b * x + c0
            ss_res, ss_tot = float(((y - fit) ** 2).sum()), float(((y - y.mean()) ** 2).sum())
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            vertex = -b / (2 * a) if a != 0 else 9
            bottom_i = Lr.idx + int(np.argmin(ctx.l[Lr.idx : i]))
            bottom = float(ctx.l[bottom_i])
            depth = (Lr.price - bottom) / Lr.price * 100
            ok = a > 0 and r2 >= p["min_r2"] and abs(vertex) <= p["vertex_band"] and p["min_depth_pct"] <= depth <= p["max_depth_pct"]
            if not ok:
                continue
            used.add(Lr.idx)
            recent_lows = [l for l in piv.known_at(i, "L") if l.idx > bottom_i and l.price < ctx.c[i]]
            stop_base = recent_lows[-1].price if recent_lows else bottom
            checks = [
                Check(f"U-shaped base >= {p['min_bars']} bars", True, f"{w} bars"),
                Check(f"Curve fit R^2 >= {p['min_r2']}", True, f"R^2 {r2:.2f}, curvature {a:.3f}"),
                Check(f"Depth {p['min_depth_pct']}-{p['max_depth_pct']}%", True, f"{depth:.1f}%"),
                Check("Close above left rim", True, f"{ctx.c[i]:.2f} > {Lr.price:.2f}"),
                ctx.vol_check(i, required=False),
            ]
            curve = [{"i": Lr.idx + k, "price": float(fit[k])} for k in range(0, len(fit), max(1, len(fit) // 30))]
            out.append(finalize(Signal(
                i, "Buy", "Rounding Bottom", checks, stop=ctx.buffer_below(stop_base), target=Lr.price + (Lr.price - bottom),
                geometry={"polyline": curve, "points": [{"i": Lr.idx, "price": Lr.price, "label": "Left rim"}, {"i": bottom_i, "price": bottom, "label": "Bottom"}],
                          "lines": [{"from": {"i": Lr.idx, "price": Lr.price}, "to": {"i": i, "price": Lr.price}, "label": "Rim"}]},
            )))
            break
    return out


def _line_at(p1, p2, i):
    return p1.price + (p2.price - p1.price) * (i - p1.idx) / (p2.idx - p1.idx)


def inverse_hs(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, used = [], set()
    for i in range(1, ctx.n):
        lows = piv.known_at(i, "L", lookback=p["max_bars"])
        if len(lows) < 3:
            continue
        LS, H, RS = lows[-3:]
        if (LS.idx, RS.idx) in used or RS.idx - LS.idx < p["min_bars"]:
            continue
        if _pct(LS.price, RS.price) > p["shoulder_tolerance_pct"]:
            continue
        if H.price > min(LS.price, RS.price) * (1 - p["min_head_depth_pct"] / 100):
            continue
        highs = piv.known_at(i, "H")
        n1 = [x for x in highs if LS.idx < x.idx < H.idx]
        n2 = [x for x in highs if H.idx < x.idx < RS.idx]
        if not n1 or not n2:
            continue
        N1, N2 = max(n1, key=lambda x: x.price), max(n2, key=lambda x: x.price)
        neck_i, neck_p = _line_at(N1, N2, i), _line_at(N1, N2, i - 1)
        if ctx.l[RS.idx + 1 : i + 1].min(initial=np.inf) < RS.price or i - RS.idx > p["max_bars_to_breakout"]:
            continue
        if not (ctx.c[i] > neck_i and ctx.c[i - 1] <= neck_p):
            continue
        used.add((LS.idx, RS.idx))
        depth = _line_at(N1, N2, H.idx) - H.price
        checks = [
            Check("Head lower than both shoulders", True, f"head {H.price:.2f}, shoulders {LS.price:.2f}/{RS.price:.2f}"),
            Check(f"Shoulders within {p['shoulder_tolerance_pct']}%", True, f"{_pct(LS.price, RS.price):.2f}%"),
            Check("Close above neckline", True, f"{ctx.c[i]:.2f} > {neck_i:.2f}"),
            ctx.vol_check(i),
        ]
        out.append(finalize(Signal(
            i, "Buy", "Inverse Head & Shoulders", checks, stop=ctx.buffer_below(RS.price), target=neck_i + depth,
            geometry={"points": [{"i": LS.idx, "price": LS.price, "label": "LS"}, {"i": H.idx, "price": H.price, "label": "Head"}, {"i": RS.idx, "price": RS.price, "label": "RS"}],
                      "lines": [{"from": {"i": N1.idx, "price": N1.price}, "to": {"i": i, "price": neck_i}, "label": "Neckline"}]},
        )))
    return out


def rectangle(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, last = [], -10**9
    for i in range(1, ctx.n):
        if i - last < p["min_bars"]:
            continue
        for w in p["windows"]:
            s = i - w
            if s < 0:
                continue
            top, bot = float(ctx.h[s:i].max()), float(ctx.l[s:i].min())
            if (top / bot - 1) * 100 > p["max_range_pct"] or not cross_above(ctx.c, top, i):
                continue
            ph = [x for x in piv.known_at(i, "H") if x.idx >= s and _pct(x.price, top) <= p["touch_tolerance_pct"]]
            pl = [x for x in piv.known_at(i, "L") if x.idx >= s and _pct(x.price, bot) <= p["touch_tolerance_pct"]]
            if len(ph) < 2 or len(pl) < 2:
                continue
            last = i
            checks = [
                Check(">= 2 touches on top", True, f"{len(ph)} near {top:.2f}"),
                Check(">= 2 touches on bottom", True, f"{len(pl)} near {bot:.2f}"),
                Check(f"Box range <= {p['max_range_pct']}%", True, f"{(top / bot - 1) * 100:.1f}% over {w} bars"),
                Check("Close above box top", True, f"{ctx.c[i]:.2f} > {top:.2f}"),
                ctx.vol_check(i),
            ]
            out.append(finalize(Signal(
                i, "Buy", "Rectangle Breakout (Darvas Box)", checks, stop=ctx.buffer_below(bot), target=top + (top - bot),
                geometry={"lines": [{"from": {"i": s, "price": top}, "to": {"i": i, "price": top}, "label": "Box top"},
                                    {"from": {"i": s, "price": bot}, "to": {"i": i, "price": bot}, "label": "Box bottom"}]},
            )))
            break
    return out


def falling_wedge(ctx: Context, p: dict) -> list[Signal]:
    piv = ctx.pivots()
    out, used = [], set()
    for i in range(1, ctx.n):
        hs = piv.known_at(i, "H", lookback=p["max_bars"])
        ls = piv.known_at(i, "L", lookback=p["max_bars"])
        if len(hs) < 2 or len(ls) < 2:
            continue
        hs, ls = hs[-p["max_pivots"]:], ls[-p["max_pivots"]:]
        start = min(hs[0].idx, ls[0].idx)
        if (hs[0].idx, ls[0].idx) in used or i - start < p["min_bars"]:
            continue
        hx, hy = np.array([x.idx for x in hs]), np.array([x.price for x in hs])
        lx, ly = np.array([x.idx for x in ls]), np.array([x.price for x in ls])
        su, iu = np.polyfit(hx, hy, 1)
        sl, il = np.polyfit(lx, ly, 1)
        if not (su < 0 and sl < 0 and su < sl):
            continue
        up_i, up_p = su * i + iu, su * (i - 1) + iu
        lo_i = sl * i + il
        if up_i <= lo_i or not (ctx.c[i] > up_i and ctx.c[i - 1] <= up_p):
            continue
        used.add((hs[0].idx, ls[0].idx))
        checks = [
            Check("Upper and lower trendlines falling", True, f"slopes {su:.3f} / {sl:.3f} per bar"),
            Check("Trendlines converging", True, "upper slope steeper than lower"),
            Check("Close above upper trendline", True, f"{ctx.c[i]:.2f} > {up_i:.2f}"),
            ctx.vol_check(i, required=False),
        ]
        out.append(finalize(Signal(
            i, "Buy", "Falling Wedge", checks, stop=ctx.buffer_below(ls[-1].price), target=float(hy.max()),
            geometry={"lines": [{"from": {"i": int(hx[0]), "price": float(su * hx[0] + iu)}, "to": {"i": i, "price": float(up_i)}, "label": "Upper"},
                                {"from": {"i": int(lx[0]), "price": float(sl * lx[0] + il)}, "to": {"i": i, "price": float(lo_i)}, "label": "Lower"}]},
        )))
    return out
