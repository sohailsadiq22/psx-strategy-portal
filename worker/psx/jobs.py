"""Background jobs: signal scanning, signal status tracking, backtests, daily ingestion. Run with `python -m psx.jobs`."""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
import traceback

import numpy as np
import pandas as pd

from .config import SOURCE_SUMMARY
from .db import service
from .engine.base import Context, Signal, dated, describe, param_hash
from .engine.indicators import add_standard
from .engine.registry import STRATEGIES, default_params, run_strategy
from .ingest.derive import load_ohlcv
from .backtest.costs import CostModel
from .backtest.runner import ConfigurationRequired, run_backtest, universe
from .backtest.simulator import Rules, simulate_symbol

log = logging.getLogger("psx.jobs")

DEFAULT_SETTINGS = {
    "liquidity": {"min_avg_volume": 50_000, "min_avg_value": 2_000_000},
    "include_unadjusted": True,
    "position_amount": 100_000,
    "costs": {},
    "rules": {},
    "live_lookback_bars": 1,
}


def _j(x):
    return json.dumps(x, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))


def user_config(conn, user_id: str) -> tuple[dict, dict]:
    row = conn.execute("select settings from user_settings where user_id=%s", (user_id,)).fetchone()
    settings = {**DEFAULT_SETTINGS, **((row or {}).get("settings") or {})}
    strat = {k: {"enabled": True, "params": default_params(k)} for k in STRATEGIES}
    for r in conn.execute("select strategy_key, enabled, params from strategy_settings where user_id=%s", (user_id,)).fetchall():
        if r["strategy_key"] in strat:
            strat[r["strategy_key"]] = {"enabled": r["enabled"], "params": {**default_params(r["strategy_key"]), **(r["params"] or {})}}
    return settings, strat


def _status_from_trade(t, sig: Signal) -> tuple[str, str | None]:
    if sig.action != "Buy":
        return "Watch", None
    if t is None or t.status == "pending":
        return "Open", "Awaiting entry at next open"
    if t.status == "skipped":
        return "Cancelled", "; ".join(t.flags)
    if t.status == "open":
        return "Open", None
    r = t.exit_reason or ""
    if r.startswith("Stop"):
        return "Stop-Loss Hit", r
    if r.startswith("Target"):
        return "Target Hit", r
    return "Closed", r


def _outcome(t, costs: CostModel, amount: float) -> dict:
    if t is None or t.entry_raw is None:
        return {}
    fill = costs.fill_price(t.entry_raw, "buy")
    shares = max(1, int(amount // fill))
    px = t.exit_raw if t.status == "closed" else t.last_close
    if px is None:
        return {"entry": t.entry_raw, "entry_date": t.entry_date}
    rt = costs.round_trip(fill, costs.fill_price(px, "sell"), shares)
    basis = fill * shares + rt["buy_costs"]["total"]
    return {"entry": t.entry_raw, "entry_date": t.entry_date, "stop": t.stop, "target": t.target,
            "exit_price": t.exit_raw if t.status == "closed" else None, "exit_date": t.exit_date, "exit_reason": t.exit_reason,
            "pnl_net": rt["net_before_tax"], "pnl_pct": rt["net_before_tax"] / basis * 100,
            "outcome": None if t.status != "closed" else ("Win" if rt["net_before_tax"] > 0 else "Loss")}


def scan(user_id: str, kind: str = "live", symbols: list[str] | None = None, strategies: list[str] | None = None,
         start: str | None = None, end: str | None = None, progress=None) -> dict:
    """Detect signals for a user's enabled strategies and persist them (deduplicated by symbol/strategy/date/param hash)."""
    with service() as conn:
        settings, strat = user_config(conn, user_id)
        keys = [k for k in (strategies or STRATEGIES) if k in STRATEGIES and strat[k]["enabled"]]
        if not keys:
            raise ConfigurationRequired("CONFIGURATION REQUIRED: no strategies enabled")
        uni = universe({"symbols": symbols or [], "include_unadjusted": settings["include_unadjusted"]}, conn)
        dv = conn.execute("select id, created_at from data_versions where kind='prices_eod' order by id desc limit 1").fetchone()
        if not dv:
            raise ConfigurationRequired("CONFIGURATION REQUIRED: no PSX price data loaded")
        latest = conn.execute("select max(date) d from prices_eod").fetchone()["d"]
        costs, rules = CostModel.from_dict(settings["costs"]), Rules.from_dict(settings["rules"])
        liq = settings["liquidity"]
        inserted = found = 0
        for n, u in enumerate(uni):
            df = load_ohlcv(u["symbol"], None, end, conn=conn)
            if len(df) < 60:
                continue
            df["date"] = pd.to_datetime(df["date"])
            df = add_standard(df)
            last_i = len(df) - 1
            if kind == "live" and df["date"].iloc[-1].date() != latest:
                continue
            for k in keys:
                p = strat[k]["params"]
                ctx = Context(df, p)
                sigs, ex = run_strategy(k, ctx)
                if kind == "live":
                    lb = int(settings["live_lookback_bars"])
                    sigs = [s for s in sigs if s.idx > last_i - lb]
                else:
                    sigs = [s for s in sigs if (not start or ctx.date(s.idx) >= start) and (not end or ctx.date(s.idx) <= end)]
                va, vv = ctx.col("vol_avg20"), ctx.col("value_avg20")
                sigs = [s for s in sigs if np.isfinite(va[s.idx]) and va[s.idx] >= liq["min_avg_volume"] and vv[s.idx] >= liq["min_avg_value"]]
                if not sigs:
                    continue
                trades = {x.idx: simulate_symbol(u["symbol"], ctx, [x], ex, rules)[0] for x in sigs if x.action == "Buy"}
                for s in sigs:
                    found += 1
                    inserted += _save_signal(conn, user_id, kind, u, k, s, ctx, trades.get(s.idx), p, costs, settings, dv)
            if progress and n % 20 == 0:
                progress(n / len(uni), f"Scanned {n}/{len(uni)} symbols, {found} signals")
            conn.commit()
        conn.commit()
    return {"symbols": len(uni), "signals_found": found, "new_signals": inserted, "latest_date": str(latest)}


def _save_signal(conn, user_id, kind, u, key, s: Signal, ctx: Context, trade, params, costs, settings, dv) -> int:
    sig_px = float(ctx.c[s.idx])
    est_stop = s.stop if s.stop is not None else (sig_px - s.stop_atr if s.stop_atr else None)
    est_target = s.target if s.target is not None else (sig_px + s.target_r * (sig_px - est_stop) if s.target_r and est_stop else None)
    status, note = _status_from_trade(trade, s)
    oc = _outcome(trade, costs, settings["position_amount"]) if s.action == "Buy" else {}
    last_px, prev_px = float(ctx.c[-1]), float(ctx.c[-2]) if ctx.n > 1 else float(ctx.c[-1])
    reason = s.reason or describe(s, STRATEGIES[key].name)
    row = conn.execute(
        """insert into signals(user_id, kind, symbol, company, strategy_key, pattern, action, signal_date, signal_price, entry, entry_date,
              stop, target, status, checklist, confirmed, indicators, geometry, reason, params, param_hash, data_source, data_version_id,
              data_updated_at, latest_price, latest_date, exit_price, exit_date, exit_reason, outcome, pnl_net, pnl_pct, flags, spec)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (user_id, symbol, strategy_key, signal_date, param_hash) do nothing returning id""",
        (user_id, kind, u["symbol"], u.get("name"), key, s.pattern, s.action, ctx.date(s.idx), sig_px, oc.get("entry"), oc.get("entry_date"),
         oc.get("stop", est_stop), oc.get("target", est_target), status, _j([c.__dict__ for c in s.checks]), s.confirmed, _j(s.indicators),
         _j(dated(s.geometry, ctx)), reason, _j(params), param_hash(params), SOURCE_SUMMARY, dv["id"], dv["created_at"], last_px, ctx.date(ctx.n - 1),
         oc.get("exit_price"), oc.get("exit_date"), oc.get("exit_reason"), oc.get("outcome"), oc.get("pnl_net"), oc.get("pnl_pct"),
         _j((trade.flags if trade else []) + ([f"{u['symbol']} price history UNADJUSTED"] if u["adjustment_status"] == "UNADJUSTED" else [])),
         _j({"stop": s.stop, "stop_atr": s.stop_atr, "target": s.target, "target_r": s.target_r, "idx_date": ctx.date(s.idx),
             "change_pct": (last_px / prev_px - 1) * 100 if prev_px else None}))).fetchone()
    if not row:
        return 0
    conn.execute("insert into signal_status_history(signal_id,user_id,status,at_date,price,note) values (%s,%s,%s,%s,%s,%s)",
                 (row["id"], user_id, "Detected", ctx.date(s.idx), sig_px, f"{s.action}: {s.pattern}"))
    if status not in ("Open", "Watch") or oc.get("entry_date"):
        if oc.get("entry_date"):
            conn.execute("insert into signal_status_history(signal_id,user_id,status,at_date,price,note) values (%s,%s,'Entered',%s,%s,'Next-day open')",
                         (row["id"], user_id, oc["entry_date"], oc["entry"]))
        if status not in ("Open", "Watch"):
            conn.execute("insert into signal_status_history(signal_id,user_id,status,at_date,price,note) values (%s,%s,%s,%s,%s,%s)",
                         (row["id"], user_id, status, oc.get("exit_date"), oc.get("exit_price"), note))
    return 1


def update_statuses(user_id: str | None = None, progress=None) -> dict:
    """Re-evaluate Open signals against new bars using the same rules as the backtester."""
    changed = 0
    with service() as conn:
        rows = conn.execute("select * from signals where status='Open' and action='Buy' and (%s::uuid is null or user_id=%s::uuid)",
                            (user_id, user_id)).fetchall()
        by_sym: dict[str, list] = {}
        for r in rows:
            by_sym.setdefault(r["symbol"], []).append(r)
        settings_cache = {}
        for n, (sym, sigs) in enumerate(by_sym.items()):
            df = load_ohlcv(sym, conn=conn)
            if df.empty:
                continue
            df["date"] = pd.to_datetime(df["date"])
            ctx = Context(add_standard(df), {})
            dates = list(df["date"].dt.strftime("%Y-%m-%d"))
            for r in sigs:
                if r["user_id"] not in settings_cache:
                    settings_cache[r["user_id"]] = user_config(conn, str(r["user_id"]))[0]
                st = settings_cache[r["user_id"]]
                d = str(r["signal_date"])
                if d not in dates:
                    continue
                i = dates.index(d)
                sp = r["spec"] or {}
                s = Signal(i, "Buy", r["pattern"], [], stop=sp.get("stop"), stop_atr=sp.get("stop_atr"), target=sp.get("target"),
                           target_r=sp.get("target_r"), strategy=r["strategy_key"])
                ex = None
                sd = STRATEGIES.get(r["strategy_key"])
                if sd and sd.exit_signal:
                    ex = run_strategy(r["strategy_key"], Context(ctx.df, r["params"]))[1]
                t = simulate_symbol(sym, ctx, [s], ex, Rules.from_dict(st["rules"]))[0]
                status, note = _status_from_trade(t, s)
                oc = _outcome(t, CostModel.from_dict(st["costs"]), st["position_amount"])
                conn.execute("""update signals set latest_price=%s, latest_date=%s, entry=coalesce(%s, entry), entry_date=coalesce(%s, entry_date),
                                  stop=coalesce(%s, stop), target=coalesce(%s, target), status=%s, exit_price=%s, exit_date=%s, exit_reason=%s,
                                  outcome=%s, pnl_net=%s, pnl_pct=%s, updated_at=now() where id=%s""",
                             (float(ctx.c[-1]), dates[-1], oc.get("entry"), oc.get("entry_date"), oc.get("stop"), oc.get("target"), status,
                              oc.get("exit_price"), oc.get("exit_date"), oc.get("exit_reason"), oc.get("outcome"), oc.get("pnl_net"),
                              oc.get("pnl_pct"), r["id"]))
                if oc.get("entry_date") and not r["entry_date"]:
                    conn.execute("insert into signal_status_history(signal_id,user_id,status,at_date,price,note) values (%s,%s,'Entered',%s,%s,'Next-day open')",
                                 (r["id"], r["user_id"], oc["entry_date"], oc["entry"]))
                if status != r["status"]:
                    changed += 1
                    conn.execute("insert into signal_status_history(signal_id,user_id,status,at_date,price,note) values (%s,%s,%s,%s,%s,%s)",
                                 (r["id"], r["user_id"], status, oc.get("exit_date") or dates[-1], oc.get("exit_price"), note))
            conn.commit()
    return {"open_checked": len(rows), "status_changes": changed}


def save_backtest(user_id: str, job_id: str | None, cfg: dict, progress=None) -> str:
    res = run_backtest(cfg, progress)
    trades = res.pop("trades")
    with service() as conn:
        run = conn.execute(
            """insert into backtest_runs(user_id, job_id, name, inputs, param_hashes, data_version_id, seed, results, results_hash)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
            (user_id, job_id, cfg.get("name"), _j(res["config"]), _j({k: param_hash(p) for k, p in res["config"]["params"].items()}),
             res["data_version"]["id"], int(res["config"]["seed"]), _j(res), res["result_hash"])).fetchone()["id"]
        with conn.cursor().copy("""copy backtest_trades(run_id,user_id,strategy_key,symbol,segment,signal_date,entry_date,entry_price,stop,target,
                                   exit_date,exit_price,exit_reason,shares,gross_pnl,costs,net_pnl,ret_pct,status,flags,signal) from stdin""") as cp:
            for t in trades:
                cp.write_row((run, user_id, t["strategy"], t["symbol"], t.get("segment", ""), t["signal_date"], t.get("entry_date"),
                              t.get("entry_price") or t.get("entry_raw"), t.get("stop"), t.get("target"), t.get("exit_date"),
                              t.get("exit_price"), t.get("exit_reason"), t.get("shares"), t.get("gross_pnl"), t.get("costs"),
                              t.get("net_pnl"), t.get("ret_pct"), t["status"], _j(t.get("flags", [])), _j(t.get("signal"))))
        conn.commit()
    return str(run)


def daily_update(progress=None) -> dict:
    """Download new PSX market summaries, rebuild adjustments, refresh index data and re-check open signals."""
    from .ingest import derive, summary
    from .ingest.psx_api import PSXClient, load_index
    with service() as conn:
        last = conn.execute("select max(date) d from prices_eod").fetchone()["d"]
    start = (last + dt.timedelta(days=1)) if last else dt.date.today() - dt.timedelta(days=30)
    dl = summary.download_range(start, dt.date.today())
    loaded = summary.load_all()
    adj = derive.build_adjustments()
    derive.refresh_symbols()
    try:
        idx = load_index("KSE100", PSXClient(delay=2))
    except Exception as e:  # index refresh is optional for signal tracking
        idx = f"error: {e}"
    st = update_statuses()
    return {"download": dl, "loaded": loaded, "adjustments": adj, "kse100": idx, "statuses": st}


def run_job(job: dict) -> None:
    jid, uid, kind, p = str(job["id"]), str(job["user_id"]), job["kind"], job["params"] or {}

    def progress(frac: float, msg: str):
        with service() as c:
            c.execute("update jobs set progress=%s, total=100, message=%s where id=%s", (int(frac * 100), msg, jid))
            c.commit()

    try:
        if kind == "scan":
            out = scan(uid, p.get("kind", "live"), p.get("symbols"), p.get("strategies"), p.get("start"), p.get("end"), progress)
            ref = None
        elif kind == "backtest":
            ref = save_backtest(uid, jid, p, progress)
            out = {"run_id": ref}
        elif kind == "status_update":
            out, ref = update_statuses(uid, progress), None
        elif kind == "ingest":
            out, ref = daily_update(progress), None
        else:
            raise ValueError(f"unknown job kind {kind}")
        with service() as c:
            c.execute("update jobs set status='done', progress=100, total=100, message=%s, result_ref=%s, finished_at=now() where id=%s",
                      (_j(out)[:2000], ref, jid))
            c.commit()
    except Exception as e:
        log.exception("job %s failed", jid)
        with service() as c:
            c.execute("update jobs set status='error', error=%s, message=%s, finished_at=now() where id=%s",
                      (traceback.format_exc()[-4000:], str(e)[:500], jid))
            c.commit()


def claim_job() -> dict | None:
    with service() as c:
        j = c.execute("""update jobs set status='running', started_at=now() where id = (
                           select id from jobs where status='queued' order by created_at for update skip locked limit 1) returning *""").fetchone()
        c.commit()
    return j


def worker_loop(poll: float = 2.0, once: bool = False):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with service() as c:  # recover jobs interrupted by a restart
        c.execute("update jobs set status='queued' where status='running'")
        c.commit()
    while True:
        j = claim_job()
        if j:
            log.info("running job %s (%s)", j["id"], j["kind"])
            run_job(j)
        elif once:
            return
        else:
            time.sleep(poll)


if __name__ == "__main__":
    worker_loop()
