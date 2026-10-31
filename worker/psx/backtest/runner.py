"""Backtest orchestration: data loading, strategy runs, IS/OOS split, walk-forward, benchmarks, random baseline."""
from __future__ import annotations

import datetime as dt
import hashlib
import json

import numpy as np
import pandas as pd

from ..db import service
from ..engine.base import Context, Signal, param_hash
from ..engine.indicators import add_standard
from ..engine.registry import STRATEGIES, default_params, run_strategy
from ..ingest.derive import load_index_series, load_ohlcv
from .costs import CostModel, cgt_by_tax_year
from .metrics import by_bucket, summarize
from .simulator import Rules, Sizing, run_portfolio, simulate_symbol

DEFAULTS = {
    "symbols": [], "start": None, "end": None, "strategies": [], "params": {}, "capital": 1_000_000.0,
    "sizing": {}, "costs": {}, "rules": {}, "mode": "separate", "max_open": 0, "oos_split": 0.7,
    "walk_forward_folds": 0, "min_trades": 30, "random_runs": 100, "seed": 42, "include_unadjusted": True,
    "liquidity": {"min_avg_volume": 50_000, "min_avg_value": 2_000_000},
}


class ConfigurationRequired(Exception):
    pass


def normalize(cfg: dict) -> dict:
    c = {**DEFAULTS, **{k: v for k, v in (cfg or {}).items() if v is not None}}
    c["liquidity"] = {**DEFAULTS["liquidity"], **(cfg or {}).get("liquidity", {})}
    unknown = [k for k in c["strategies"] if k not in STRATEGIES]
    if unknown:
        raise ConfigurationRequired(f"Unknown strategies: {unknown}")
    if not c["strategies"]:
        raise ConfigurationRequired("Select at least one strategy")
    c["params"] = {k: {**default_params(k), **c["params"].get(k, {})} for k in c["strategies"]}
    return c


def universe(c: dict, conn) -> list[dict]:
    q = "select symbol, adjustment_status, instrument_type, name from symbols where bars > 0"
    rows = conn.execute(q).fetchall()
    if c["symbols"]:
        want = {s.upper() for s in c["symbols"]}
        rows = [r for r in rows if r["symbol"] in want]
    else:
        rows = [r for r in rows if r["instrument_type"] in ("equity", "etf")]
    if not c["include_unadjusted"]:
        rows = [r for r in rows if r["adjustment_status"] != "UNADJUSTED"]
    return sorted(rows, key=lambda r: r["symbol"])


def _liquid(ctx: Context, i: int, liq: dict) -> bool:
    va, vv = ctx.col("vol_avg20")[i], ctx.col("value_avg20")[i]
    return bool(np.isfinite(va) and va >= liq["min_avg_volume"] and np.isfinite(vv) and vv >= liq["min_avg_value"])


def run_backtest(cfg: dict, progress=None) -> dict:
    c = normalize(cfg)
    costs, rules, sizing = CostModel.from_dict(c["costs"]), Rules.from_dict(c["rules"]), Sizing.from_dict(c["sizing"])
    with service() as conn:
        dv = conn.execute("select id, created_at, last_date as max_date from data_versions order by id desc limit 1").fetchone()
        if not dv:
            raise ConfigurationRequired("CONFIGURATION REQUIRED: no PSX price data loaded. Run the ingestion job first.")
        uni = universe(c, conn)
        if not uni:
            raise ConfigurationRequired("CONFIGURATION REQUIRED: no symbols match the selection / adjustment filter")
        span = conn.execute("select min(date) a, max(date) b from prices_eod").fetchone()
        start = dt.date.fromisoformat(str(c["start"])) if c["start"] else span["a"]
        end = dt.date.fromisoformat(str(c["end"])) if c["end"] else span["b"]
        data, warnings = {}, []
        for k, u in enumerate(uni):
            df = load_ohlcv(u["symbol"], None, end, conn=conn)
            if len(df) < 30:
                continue
            df["date"] = pd.to_datetime(df["date"])
            data[u["symbol"]] = add_standard(df)
            if u["adjustment_status"] == "UNADJUSTED":
                warnings.append(f"{u['symbol']}: UNADJUSTED price history included")
            if progress and k % 25 == 0:
                progress(0.3 * k / len(uni), f"Loaded {k}/{len(uni)} symbols")
        kse = load_index_series("KSE100", conn)
    if not data:
        raise ConfigurationRequired("CONFIGURATION REQUIRED: selected symbols have insufficient price history")
    s_iso, e_iso = start.isoformat(), end.isoformat()
    cal = sorted({d for df in data.values() for d in df["date"].dt.strftime("%Y-%m-%d") if s_iso <= d <= e_iso})
    if len(cal) < 20:
        raise ConfigurationRequired("CONFIGURATION REQUIRED: date range has fewer than 20 trading days of data")
    split = cal[int(len(cal) * c["oos_split"])]
    closes = {s: pd.Series(df["close"].to_numpy(), index=df["date"].dt.strftime("%Y-%m-%d")) for s, df in data.items()}
    regime = _regime(kse)

    per_strategy, all_trades = {}, []
    total = len(c["strategies"])
    for si, key in enumerate(c["strategies"]):
        p = c["params"][key]
        trades, n_sig = [], 0
        for sym, df in data.items():
            ctx = Context(df, p)
            sigs, ex = run_strategy(key, ctx)
            keep = [s for s in sigs if s_iso <= ctx.date(s.idx) <= e_iso and s.action == "Buy" and _liquid(ctx, s.idx, c["liquidity"])]
            n_sig += len(keep)
            trades += simulate_symbol(sym, ctx, keep, ex, rules)
        all_trades += trades
        per_strategy[key] = {"params": p, "param_hash": param_hash(p), "n_signals": n_sig, "raw": trades}
        if progress:
            progress(0.3 + 0.4 * (si + 1) / total, f"Ran {STRATEGIES[key].name}")

    segments = {"in_sample": (s_iso, split), "out_of_sample": (split, "9999"), "full": (s_iso, "9999")}
    results, trade_rows = {}, []
    groups = {k: v["raw"] for k, v in per_strategy.items()} if c["mode"] == "separate" else {"combined": all_trades}
    rng_seed = int(c["seed"])
    for gi, (gkey, trades) in enumerate(groups.items()):
        res = {"segments": {}}
        for seg, (a, b) in segments.items():
            seg_trades = [t for t in trades if t.entry_date and a <= t.entry_date < b]
            n_sig = sum(1 for t in trades if a <= t.signal_date < b)
            pf = run_portfolio(seg_trades, c["capital"], sizing, costs, c["max_open"], closes)
            cgt = cgt_by_tax_year([r for r in pf["trades"] if r["status"] == "closed"], costs.cgt_pct)
            m = summarize(pf["trades"], c["capital"], pf["equity_curve"], cgt, n_sig)
            seg_end = cal[-1] if b == "9999" else b
            m["kse100"] = _kse_return(kse, a, seg_end)
            if seg != "full" and c["random_runs"]:
                m["random"] = _random_baseline(pf["trades"], data, a, seg_end, c, costs, rules, sizing, rng_seed + gi * 1000 + len(seg))
            m["by_year"] = by_bucket(pf["trades"], lambda r: r["entry_date"][:4])
            m["by_regime"] = by_bucket(pf["trades"], lambda r: regime.get(r["entry_date"], "unknown (no KSE-100 data)"))
            m["equity_curve"] = pf["equity_curve"]
            res["segments"][seg] = m
            if seg == "full":
                for r in pf["trades"]:
                    r["segment"] = "in_sample" if r["entry_date"] < split else "out_of_sample"
                    r["group"] = gkey
                trade_rows += pf["trades"]
        if c["walk_forward_folds"]:
            res["walk_forward"] = _walk_forward(trades, cal, int(c["walk_forward_folds"]), c, sizing, costs, closes)
        oos = res["segments"]["out_of_sample"]
        res["eligible"] = oos["completed_trades"] >= c["min_trades"]
        res["verdict"] = _verdict(oos, c["min_trades"])
        results[gkey] = res
        if progress:
            progress(0.7 + 0.3 * (gi + 1) / len(groups), f"Evaluated {gkey}")

    ranking = sorted([k for k, r in results.items() if r["eligible"]],
                     key=lambda k: -results[k]["segments"]["out_of_sample"]["return_pct"])
    data_version = {"id": dv["id"], "max_date": str(dv["max_date"]), "created_at": str(dv["created_at"])}
    for r in trade_rows:
        r.pop("signal", None) if False else None
    payload = {"config": c, "data_version": data_version, "split_date": split, "start": s_iso, "end": cal[-1],
               "symbols_tested": len(data), "results": results, "ranking": ranking, "warnings": warnings[:200],
               "n_warnings": len(warnings)}
    payload["result_hash"] = _hash({"cfg": c, "dv": data_version, "results": _strip_curves(results), "trades": trade_rows})
    payload["trades"] = trade_rows
    return payload


def _verdict(m: dict, min_trades: int) -> str:
    if m["completed_trades"] < min_trades:
        return f"INSUFFICIENT SAMPLE: {m['completed_trades']} out-of-sample trades (< {min_trades}); no ranking."
    beats_k = m["kse100"] and m["kse100"]["return_pct"] is not None and m["return_pct"] > m["kse100"]["return_pct"]
    r = m.get("random") or {}
    beats_r = r.get("mean_return_pct") is not None and m["return_pct"] > r["p95_return_pct"]
    if m["return_pct"] > 0 and beats_k and beats_r:
        return "Out-of-sample net return is positive and beats KSE-100 and the 95th percentile of random entries. Past results do not guarantee future returns."
    parts = []
    if m["return_pct"] <= 0:
        parts.append("net out-of-sample return is not positive after costs")
    if not beats_k:
        parts.append("does not beat KSE-100 buy-and-hold")
    if not beats_r:
        parts.append("not distinguishable from random entries (below 95th percentile)")
    return "No evidence of edge: " + "; ".join(parts) + "."


def _kse_return(kse: pd.DataFrame, a: str, b: str) -> dict:
    if kse.empty:
        return {"return_pct": None, "note": "CONFIGURATION REQUIRED: KSE-100 data not loaded"}
    k = kse.assign(d=pd.to_datetime(kse["date"]).dt.strftime("%Y-%m-%d"))
    w = k[(k["d"] >= a) & (k["d"] <= b)]
    if len(w) < 2:
        return {"return_pct": None, "note": "KSE-100 data unavailable for this period"}
    first = w.iloc[0]
    base = first["open"] if pd.notna(first["open"]) and first["open"] > 0 else first["close"]
    cover = "full" if w["d"].iloc[0] <= _next(a) else f"partial (index data from {w['d'].iloc[0]})"
    return {"return_pct": float((w["close"].iloc[-1] / base - 1) * 100), "from": w["d"].iloc[0], "to": w["d"].iloc[-1],
            "coverage": cover, "note": "Index price return, no costs/dividends"}


def _next(d: str) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=7)).isoformat()


def _regime(kse: pd.DataFrame) -> dict:
    if kse.empty:
        return {}
    c = kse["close"].astype(float)
    ma = c.rolling(200, min_periods=200).mean()
    slope = ma - ma.shift(20)
    out = {}
    for d, px, m, s in zip(pd.to_datetime(kse["date"]).dt.strftime("%Y-%m-%d"), c, ma, slope):
        if not np.isfinite(m):
            continue
        out[d] = "bull" if px > m and s > 0 else "bear" if px < m and s < 0 else "sideways"
    return out


def _random_baseline(rows, data, a, b, c, costs, rules, sizing, seed) -> dict:
    taken = [r for r in rows if r["status"] in ("closed", "open")]
    if not taken:
        return {"runs": 0, "note": "No strategy trades in segment"}
    stop_pct = [(r["entry_raw"] - r["stop"]) / r["entry_raw"] for r in taken if r.get("stop")]
    tgt_pct = [(r["target"] - r["entry_raw"]) / r["entry_raw"] for r in taken if r.get("target")]
    hold = [(dt.date.fromisoformat(r["exit_date"]) - dt.date.fromisoformat(r["entry_date"])).days * 5 // 7 for r in taken if r.get("exit_date")]
    sp = float(np.median(stop_pct)) if stop_pct else None
    tp = float(np.median(tgt_pct)) if tgt_pct else None
    hb = max(1, int(np.median(hold))) if hold else 20
    ctxs = {}
    eligible = []
    for sym, df in data.items():
        d = df["date"].dt.strftime("%Y-%m-%d").to_numpy()
        idx = np.where((d >= a) & (d <= b))[0]
        if len(idx) > 1:
            eligible.append((sym, idx[:-1]))
    rets = []
    r2 = Rules(**{**rules.__dict__, "max_hold_bars": 0 if tp else hb})
    for run in range(int(c["random_runs"])):
        rng = np.random.default_rng(seed + run)
        picks: dict[str, list[int]] = {}
        for _ in range(len(taken)):
            sym, idx = eligible[rng.integers(len(eligible))]
            picks.setdefault(sym, []).append(int(idx[rng.integers(len(idx))]))
        trades = []
        for sym, ids in picks.items():
            ctx = ctxs.get(sym) or ctxs.setdefault(sym, Context(data[sym], {}))
            sigs = []
            for i in sorted(set(ids)):
                px = ctx.c[i]
                sigs.append(Signal(i, "Buy", "Random", [], stop=px * (1 - sp) if sp else None,
                                   target=px * (1 + tp) if tp else None, strategy="random"))
            trades += simulate_symbol(sym, ctx, sigs, None, r2)
        pf = run_portfolio(trades, c["capital"], sizing, costs, c["max_open"], None)
        net = sum(r["net_pnl"] for r in pf["trades"] if r["status"] == "closed")
        rets.append(net / c["capital"] * 100)
    rets = np.array(rets)
    return {"runs": len(rets), "seed": seed, "mean_return_pct": float(rets.mean()), "median_return_pct": float(np.median(rets)),
            "p5_return_pct": float(np.percentile(rets, 5)), "p95_return_pct": float(np.percentile(rets, 95)),
            "method": f"Same number of entries ({len(taken)}) on random liquid-universe dates, stop {sp and round(sp*100,2)}%, "
                      f"target {tp and round(tp*100,2)}%, {'' if tp else f'time exit {hb} bars, '}same costs and sizing (realised P/L before CGT)"}


def _walk_forward(trades, cal, folds, c, sizing, costs, closes) -> list[dict]:
    """Strategy rules/params are fixed (no fitting), so each window is an independent out-of-sample test."""
    edges = [cal[int(len(cal) * i / (folds + 1))] for i in range(folds + 1)] + ["9999"]
    out = []
    for i in range(1, folds + 1):
        a, b = edges[i], edges[i + 1]
        seg = [t for t in trades if t.entry_date and a <= t.entry_date < b]
        pf = run_portfolio(seg, c["capital"], sizing, costs, c["max_open"], closes)
        cgt = cgt_by_tax_year([r for r in pf["trades"] if r["status"] == "closed"], costs.cgt_pct)
        m = summarize(pf["trades"], c["capital"], pf["equity_curve"], cgt, len(seg))
        out.append({"fold": i, "from": a, "to": b if b != "9999" else cal[-1], **{k: m[k] for k in
                    ("completed_trades", "win_rate", "net_profit", "return_pct", "profit_factor", "max_drawdown_pct")}})
    return out


def _strip_curves(results: dict) -> dict:
    return {k: {s: {m: v for m, v in seg.items() if m != "equity_curve"} for s, seg in r["segments"].items()} for k, r in results.items()}


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
