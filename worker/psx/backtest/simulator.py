"""Trade simulation with PSX rules.

Per symbol: one open position at a time. Entry at the next bar's OPEN after the signal candle.
Exit priority on each bar: gap below stop (exit at open) > same-candle stop & target (STOP first) >
stop (LOCKED if the bar closes at the lower circuit limit -> next open) > target > strategy exit
(evaluated at close, executed next open) > max holding period.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..engine.base import Context, Signal, dated
from .costs import CostModel


@dataclass
class Rules:
    entry_mode: str = "next_open"      # next_open | next_close
    circuit_pct: float = 7.5           # verify current PSX limit
    circuit_min_rs: float = 1.0        # PSX: % limit or Rs 1, whichever is higher (verify)
    max_hold_bars: int = 0             # 0 = no time stop
    skip_locked_entry: bool = True     # skip entries when the entry bar is locked at upper circuit

    @classmethod
    def from_dict(cls, d: dict | None) -> "Rules":
        d = d or {}
        return cls(**{k: type(getattr(cls, k))(v) for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Trade:
    symbol: str
    strategy: str
    signal_idx: int
    signal_date: str
    entry_idx: int | None = None
    entry_date: str | None = None
    entry_raw: float | None = None
    stop: float | None = None
    target: float | None = None
    exit_idx: int | None = None
    exit_date: str | None = None
    exit_raw: float | None = None
    exit_reason: str | None = None
    status: str = "pending"            # closed | open | skipped | pending
    flags: list = field(default_factory=list)
    signal: dict | None = None
    last_close: float | None = None


def _limit(ldcp: float, r: Rules, up: bool) -> float:
    if not np.isfinite(ldcp) or ldcp <= 0:
        return np.nan
    step = max(ldcp * r.circuit_pct / 100, r.circuit_min_rs)
    return ldcp + step if up else ldcp - step


def simulate_symbol(symbol: str, ctx: Context, signals: list[Signal], exit_arr: np.ndarray | None, rules: Rules) -> list[Trade]:
    o, h, l, c = ctx.o, ctx.h, ctx.l, ctx.c
    ldcp = ctx.col("ldcp") if "ldcp" in ctx.df else np.r_[np.nan, c[:-1]]
    n = ctx.n
    trades: list[Trade] = []
    busy_until = -1
    for s in sorted((x for x in signals if x.action == "Buy"), key=lambda x: x.idx):
        if s.idx <= busy_until:
            continue
        t = Trade(symbol, s.strategy, s.idx, ctx.date(s.idx), signal={**dated(s.to_dict(), ctx), "signal_date": ctx.date(s.idx)})
        j = s.idx + 1
        if j >= n:
            t.status, t.flags = "pending", ["Signal on latest bar: entry at next open"]
            trades.append(t)
            continue
        entry = o[j] if rules.entry_mode == "next_open" else c[j]
        up_lim = _limit(ldcp[j], rules, True)
        if np.isfinite(up_lim) and h[j] == l[j] and o[j] >= up_lim - 1e-6:
            t.flags.append("Entry bar locked at upper circuit: order may not fill")
            if rules.skip_locked_entry:
                t.status = "skipped"
                trades.append(t)
                continue
        stop = s.stop if s.stop is not None else (entry - s.stop_atr if s.stop_atr else None)
        if stop is not None and stop >= entry:
            t.status, t.flags = "skipped", t.flags + [f"Entry {entry:.2f} opened at/below stop {stop:.2f}"]
            trades.append(t)
            continue
        target = s.target
        if target is None and s.target_r and stop is not None:
            target = entry + s.target_r * (entry - stop)
        if target is not None and target <= entry:
            t.status, t.flags = "skipped", t.flags + [f"Entry {entry:.2f} opened above target {target:.2f}"]
            trades.append(t)
            continue
        t.entry_idx, t.entry_date, t.entry_raw, t.stop, t.target = j, ctx.date(j), float(entry), stop, target
        start_k = j if rules.entry_mode == "next_open" else j + 1
        for k in range(start_k, n):
            gap_ok = k > j
            hit_stop = stop is not None and l[k] <= stop
            hit_tgt = target is not None and h[k] >= target
            if gap_ok and stop is not None and o[k] <= stop:
                t.exit_idx, t.exit_raw, t.exit_reason = k, o[k], "Stop-Loss (gap below stop, exit at open)"
            elif gap_ok and target is not None and o[k] >= target:
                t.exit_idx, t.exit_raw, t.exit_reason = k, o[k], "Target (gap above target, exit at open)"
            elif hit_stop:
                lo_lim = _limit(ldcp[k], rules, False)
                locked = np.isfinite(lo_lim) and c[k] <= lo_lim + 1e-6 and l[k] >= c[k] - 1e-6
                if locked and k + 1 < n:
                    t.exit_idx, t.exit_raw = k + 1, o[k + 1]
                    t.exit_reason = "Stop-Loss LOCKED at lower circuit, exit at next open"
                    t.flags.append("LOCKED, exit may not be possible at stop price")
                elif locked:
                    t.flags.append("LOCKED at lower circuit on latest bar")
                    break
                else:
                    t.exit_idx, t.exit_raw = k, stop
                    t.exit_reason = "Stop-Loss (same candle as target: stop assumed first)" if hit_tgt else "Stop-Loss"
            elif hit_tgt:
                t.exit_idx, t.exit_raw, t.exit_reason = k, target, "Target Hit"
            elif exit_arr is not None and exit_arr[k] and k >= j:
                if k + 1 < n:
                    t.exit_idx, t.exit_raw, t.exit_reason = k + 1, o[k + 1], "Strategy exit (next open)"
                else:
                    t.flags.append("Strategy exit triggered on latest bar: sell at next open")
                    break
            elif rules.max_hold_bars and k - j >= rules.max_hold_bars:
                t.exit_idx, t.exit_raw, t.exit_reason = k, c[k], "Time stop (close)"
            if t.exit_idx is not None:
                break
        if t.exit_idx is not None:
            t.status, t.exit_date, t.exit_raw = "closed", ctx.date(t.exit_idx), float(t.exit_raw)
            busy_until = t.exit_idx
        else:
            t.status, t.last_close = "open", float(c[-1])
            busy_until = n
        trades.append(t)
    return trades


@dataclass
class Sizing:
    mode: str = "pct_equity"   # fixed_amount | pct_equity | risk
    fixed_amount: float = 100_000.0
    pct_equity: float = 10.0
    risk_pct: float = 1.0
    lot_size: int = 1

    @classmethod
    def from_dict(cls, d: dict | None) -> "Sizing":
        d = d or {}
        return cls(**{k: type(getattr(cls, k))(v) for k, v in d.items() if k in cls.__dataclass_fields__})


def run_portfolio(trades: list[Trade], capital: float, sizing: Sizing, costs: CostModel, max_open: int = 0,
                  closes: dict | None = None) -> dict:
    """Allocate capital chronologically. Exits on a date are processed before entries on that date."""
    cand = sorted([t for t in trades if t.entry_date], key=lambda t: (t.entry_date, t.symbol, t.strategy))
    cash, open_pos, out = capital, [], []
    held_symbols: set[str] = set()
    realized = []

    def close_until(date):
        nonlocal cash
        for p in sorted([p for p in open_pos if p["t"].exit_date and p["t"].exit_date <= date], key=lambda p: p["t"].exit_date):
            cash += p["proceeds"]
            open_pos.remove(p)
            held_symbols.discard(p["t"].symbol)
            realized.append(p)

    for t in cand:
        close_until(t.entry_date)
        rec = {"t": t}
        if max_open and len(open_pos) >= max_open:
            out.append({**_row(t), "status": "skipped", "flags": t.flags + ["Max open positions reached"]})
            continue
        if t.symbol in held_symbols:
            out.append({**_row(t), "status": "skipped", "flags": t.flags + ["Position already open in this stock"]})
            continue
        fill = costs.fill_price(t.entry_raw, "buy")
        equity = cash + sum(p["cost_basis"] for p in open_pos)
        if sizing.mode == "fixed_amount":
            alloc = sizing.fixed_amount
        elif sizing.mode == "risk" and t.stop is not None and fill > t.stop:
            alloc = equity * sizing.risk_pct / 100 / (fill - t.stop) * fill
        else:
            alloc = equity * sizing.pct_equity / 100
        alloc = min(alloc, cash)
        shares = int(alloc / (fill * (1 + 0.004)) // sizing.lot_size * sizing.lot_size)
        if shares < 1:
            out.append({**_row(t), "status": "skipped", "flags": t.flags + ["Insufficient cash"]})
            continue
        buy_c = costs.side_costs(fill, shares)["total"]
        cost_basis = fill * shares + buy_c
        cash -= cost_basis
        rec.update(shares=shares, entry_fill=fill, cost_basis=cost_basis)
        if t.status == "closed":
            exit_fill = costs.fill_price(t.exit_raw, "sell")
            rt = costs.round_trip(fill, exit_fill, shares)
            rec["proceeds"] = exit_fill * shares - rt["sell_costs"]["total"]
            row = {**_row(t), "shares": shares, "entry_price": fill, "exit_price": exit_fill, "gross_pnl": rt["gross"],
                   "costs": rt["costs"], "net_pnl": rt["net_before_tax"], "ret_pct": rt["net_before_tax"] / cost_basis * 100,
                   "status": "closed", "cost_detail": {"buy": rt["buy_costs"], "sell": rt["sell_costs"]}}
        else:
            mark = costs.fill_price(t.last_close or t.entry_raw, "sell")
            rt = costs.round_trip(fill, mark, shares)
            rec["proceeds"] = None
            row = {**_row(t), "shares": shares, "entry_price": fill, "exit_price": None, "mark_price": mark, "gross_pnl": rt["gross"],
                   "costs": rt["costs"], "net_pnl": rt["net_before_tax"], "ret_pct": rt["net_before_tax"] / cost_basis * 100, "status": "open"}
        rec["row"] = row
        open_pos.append(rec)
        held_symbols.add(t.symbol)
        out.append(row)
    close_until("9999-12-31")
    for p in open_pos:
        if p["proceeds"] is None:
            continue
    equity_curve = _equity_curve(out, capital, closes)
    return {"trades": out, "equity_curve": equity_curve}


def _row(t: Trade) -> dict:
    return {"symbol": t.symbol, "strategy": t.strategy, "signal_date": t.signal_date, "entry_date": t.entry_date, "entry_raw": t.entry_raw,
            "stop": t.stop, "target": t.target, "exit_date": t.exit_date, "exit_raw": t.exit_raw, "exit_reason": t.exit_reason,
            "flags": list(t.flags), "signal": t.signal, "status": t.status}


def _equity_curve(rows: list[dict], capital: float, closes: dict | None) -> list[dict]:
    """Daily equity = capital + realised net P/L + unrealised P/L of open positions (marked at close)."""
    import pandas as pd
    taken = [r for r in rows if r["status"] in ("closed", "open")]
    if not taken:
        return []
    if closes:
        dates = sorted({d for s in closes.values() for d in s.index})
    else:
        dates = sorted({r["entry_date"] for r in taken} | {r["exit_date"] for r in taken if r["exit_date"]})
    first = min(r["entry_date"] for r in taken)
    idx = pd.Index([d for d in dates if d >= first])
    eq = pd.Series(float(capital), index=idx)
    for r in taken:
        basis = r["entry_price"] * r["shares"] + r["cost_detail"]["buy"]["total"] if r.get("cost_detail") else r["entry_price"] * r["shares"]
        end = r["exit_date"]
        s = closes.get(r["symbol"]) if closes else None
        if s is not None:
            held = s[(s.index >= r["entry_date"]) & ((s.index < end) if end else True)]
            unreal = (held * r["shares"] - basis).reindex(idx)
            mask = (idx >= r["entry_date"]) & ((idx < end) if end else True)
            eq[mask] += unreal[mask].ffill().fillna(0).to_numpy()
        if end:
            eq[idx >= end] += r["net_pnl"]
    step = max(1, len(eq) // 600)
    pts = [{"date": d, "equity": round(float(v), 2)} for d, v in list(eq.items())[::step]]
    if pts[-1]["date"] != eq.index[-1]:
        pts.append({"date": eq.index[-1], "equity": round(float(eq.iloc[-1]), 2)})
    return pts
