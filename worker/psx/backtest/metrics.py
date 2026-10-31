from __future__ import annotations

import numpy as np


def max_drawdown(curve: list[dict]) -> float:
    if not curve:
        return 0.0
    eq = np.array([p["equity"] for p in curve], float)
    peak = np.maximum.accumulate(eq)
    return float(((eq - peak) / peak).min() * 100)


def summarize(rows: list[dict], capital: float, curve: list[dict], cgt: dict, n_signals: int) -> dict:
    closed = [r for r in rows if r["status"] == "closed"]
    opened = [r for r in rows if r["status"] == "open"]
    wins = [r for r in closed if r["net_pnl"] > 0]
    losses = [r for r in closed if r["net_pnl"] <= 0]
    gw, gl = sum(r["net_pnl"] for r in wins), sum(r["net_pnl"] for r in losses)
    gross = sum(r["gross_pnl"] for r in closed)
    costs = sum(r["costs"] for r in closed)
    net_before_tax = sum(r["net_pnl"] for r in closed)
    net = net_before_tax - cgt["total"]
    avg_w = gw / len(wins) if wins else 0.0
    avg_l = gl / len(losses) if losses else 0.0
    rs = []
    for r in closed:
        risk = (r["entry_price"] - r["stop"]) * r["shares"] if r.get("stop") and r["entry_price"] > r["stop"] else None
        if risk:
            rs.append(r["net_pnl"] / risk)
    holding = [_bars(r) for r in closed]
    return {
        "total_signals": n_signals, "trades_taken": len(closed) + len(opened), "completed_trades": len(closed),
        "open_trades": len(opened), "skipped": sum(1 for r in rows if r["status"] == "skipped"),
        "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100 if closed else None,
        "loss_rate": len(losses) / len(closed) * 100 if closed else None,
        "gross_pnl": gross, "gross_profit": sum(r["gross_pnl"] for r in closed if r["gross_pnl"] > 0),
        "gross_loss": sum(r["gross_pnl"] for r in closed if r["gross_pnl"] <= 0),
        "costs": costs, "cgt": cgt["total"], "cgt_by_year": cgt["by_year"],
        "net_pnl_before_tax": net_before_tax, "net_profit": net, "return_pct": net / capital * 100,
        "unrealised_open_pnl": sum(r["net_pnl"] for r in opened),
        "profit_factor": (gw / -gl) if gl < 0 else (None if not wins else float("inf")),
        "max_drawdown_pct": max_drawdown(curve), "avg_win": avg_w, "avg_loss": avg_l,
        "reward_risk": (avg_w / -avg_l) if avg_l < 0 else None,
        "expectancy": net_before_tax / len(closed) if closed else None,
        "expectancy_r": float(np.mean(rs)) if rs else None,
        "avg_holding_days": float(np.mean(holding)) if holding else None,
    }


def _bars(r):
    import datetime as dt
    return (dt.date.fromisoformat(r["exit_date"]) - dt.date.fromisoformat(r["entry_date"])).days


def by_bucket(rows: list[dict], key) -> dict:
    out: dict = {}
    for r in rows:
        if r["status"] != "closed":
            continue
        b = key(r)
        d = out.setdefault(b, {"trades": 0, "wins": 0, "net_pnl": 0.0})
        d["trades"] += 1
        d["wins"] += r["net_pnl"] > 0
        d["net_pnl"] += r["net_pnl"]
    for d in out.values():
        d["win_rate"] = d["wins"] / d["trades"] * 100 if d["trades"] else None
    return dict(sorted(out.items()))
