"""HTTP API. Auth: Supabase JWT (HS256, SUPABASE_JWT_SECRET) or local auth (same token format). All user data is
read through `as_user`, so Postgres RLS is enforced on every request."""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path

import bcrypt
import jwt
import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..backtest.costs import CostModel
from ..backtest.runner import DEFAULTS as BT_DEFAULTS
from ..backtest.simulator import Rules, Sizing
from ..config import AUTH_MODE, JWT_SECRET, SUPABASE_ANON_KEY, SUPABASE_URL
from ..db import as_user, service
from ..engine.base import GLOBAL_DEFAULTS
from ..engine.indicators import add_standard
from ..engine.registry import STRATEGIES, default_params
from ..ingest.derive import load_index_series, load_ohlcv
from ..jobs import DEFAULT_SETTINGS

app = FastAPI(title="PSX Strategy Portal API")


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    if hasattr(o, "__float__") and not isinstance(o, (bool, int)):
        return float(o)
    return o


def ok(x):
    return JSONResponse(_clean(x))


def user_id(request: Request) -> str:
    h = request.headers.get("authorization", "")
    if not h.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        claims = jwt.decode(h[7:], JWT_SECRET, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}")
    return claims["sub"]


class Creds(BaseModel):
    email: str
    password: str


def _token(uid: str, email: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"sub": uid, "email": email, "role": "authenticated", "aud": "authenticated",
                       "iat": now, "exp": now + dt.timedelta(days=7)}, JWT_SECRET, algorithm="HS256")


@app.get("/api/config")
def config():
    return {"auth_mode": AUTH_MODE, "supabase_url": SUPABASE_URL or None,
            "supabase_anon_key": SUPABASE_ANON_KEY or None}


@app.post("/api/auth/register")
def register(c: Creds):
    if AUTH_MODE != "local":
        raise HTTPException(400, "Use Supabase Auth")
    if len(c.password) < 8 or "@" not in c.email:
        raise HTTPException(400, "Valid email and a password of at least 8 characters required")
    with service() as conn:
        if conn.execute("select 1 from auth.users where email=%s", (c.email.lower(),)).fetchone():
            raise HTTPException(409, "Email already registered")
        uid = conn.execute("insert into auth.users(email, encrypted_password) values (%s,%s) returning id",
                           (c.email.lower(), bcrypt.hashpw(c.password.encode(), bcrypt.gensalt()).decode())).fetchone()["id"]
        conn.commit()
    return {"access_token": _token(str(uid), c.email.lower()), "email": c.email.lower()}


@app.post("/api/auth/login")
def login(c: Creds):
    if AUTH_MODE != "local":
        raise HTTPException(400, "Use Supabase Auth")
    with service() as conn:
        r = conn.execute("select id, encrypted_password from auth.users where email=%s", (c.email.lower(),)).fetchone()
    if not r or not bcrypt.checkpw(c.password.encode(), r["encrypted_password"].encode()):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": _token(str(r["id"]), c.email.lower()), "email": c.email.lower()}


@app.get("/api/me")
def me(uid: str = Depends(user_id)):
    return {"user_id": uid}


# ---------- market data (shared, read-only) ----------
@app.get("/api/data/status")
def data_status():
    with service() as conn:
        p = conn.execute("select count(*) bars, count(distinct symbol) symbols, min(date) first, max(date) last, count(distinct date) days from prices_eod").fetchone()
        k = conn.execute("select count(*) n, min(date) first, max(date) last from index_eod where index_code='KSE100'").fetchone()
        adj = conn.execute("select instrument_type, adjustment_status, count(*) n from symbols where bars>0 group by 1,2 order by 1,2").fetchall()
        ev = conn.execute("select kind, count(*) n from adjustment_events group by 1 order by 1").fetchall()
        issues = conn.execute("select kind, count(*) n from data_issues group by 1 order by 1").fetchall()
        dv = conn.execute("select * from data_versions order by id desc limit 5").fetchall()
    configured = bool(p["bars"])
    return ok({"configured": configured, "message": None if configured else "CONFIGURATION REQUIRED: no PSX price data loaded. Run the ingestion job.",
               "prices": p, "kse100": k, "adjustment": adj, "adjustment_events": ev, "issues": issues, "versions": dv,
               "sources": {"prices": "PSX Data Portal daily market summary (dps.psx.com.pk/download/mkt_summary)",
                           "index": "PSX Data Portal KSE-100 timeseries (dps.psx.com.pk/timeseries/eod/KSE100)"}})


@app.get("/api/data/issues")
def data_issues(kind: str | None = None, symbol: str | None = None, limit: int = 200):
    with service() as conn:
        rows = conn.execute("""select * from data_issues where (%s::text is null or kind=%s) and (%s::text is null or symbol=%s)
                               order by date desc nulls last limit %s""", (kind, kind, symbol, symbol, limit)).fetchall()
    return ok(rows)


@app.get("/api/symbols")
def symbols(q: str = "", all_types: bool = False, limit: int = 50):
    with service() as conn:
        rows = conn.execute("""select symbol, name, sector_code, instrument_type, status, adjustment_status, first_date, last_date, bars
                               from symbols where bars>0 and (symbol ilike %s or name ilike %s) and (%s or instrument_type in ('equity','etf'))
                               order by symbol limit %s""", (f"{q}%", f"%{q}%", all_types, limit)).fetchall()
    return ok(rows)


@app.get("/api/chart/{symbol}")
def chart(symbol: str, until: str | None = None, start: str | None = None, adjusted: bool = True):
    """OHLCV + indicators. `until` truncates the series so no bar after that date is sent (as-of view)."""
    df = load_ohlcv(symbol.upper(), start=None, end=until, adjusted=adjusted)
    if df.empty:
        raise HTTPException(404, f"No price data for {symbol}")
    df["date"] = pd.to_datetime(df["date"])
    df = add_standard(df)
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    cols = ["open", "high", "low", "close", "volume", "sma20", "sma50", "sma200", "bb_up", "bb_mid", "bb_lo", "st_line", "st_dir",
            "rsi14", "macd", "macd_signal", "macd_hist", "atr14", "vol_avg20"]
    out = {"symbol": symbol.upper(), "dates": df["date"].dt.strftime("%Y-%m-%d").tolist()}
    for c in cols:
        out[c] = [None if not np.isfinite(v) else round(float(v), 4) for v in df[c].to_numpy(float)]
    with service() as conn:
        info = conn.execute("select name, adjustment_status, adjustment_note from symbols where symbol=%s", (symbol.upper(),)).fetchone()
        out["adjustment_events"] = conn.execute("select ex_date, factor, kind from adjustment_events where symbol=%s order by ex_date",
                                                (symbol.upper(),)).fetchall()
    out["info"] = info
    out["adjusted"] = adjusted
    return ok(out)


@app.get("/api/index/{code}")
def index(code: str = "KSE100"):
    df = load_index_series(code.upper())
    return ok({"dates": [str(d) for d in df["date"]], "close": df["close"].tolist()})


# ---------- strategies & settings ----------
@app.get("/api/strategies")
def strategies(uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        rows = {r["strategy_key"]: r for r in conn.execute("select * from strategy_settings").fetchall()}
    out = []
    for k, s in STRATEGIES.items():
        r = rows.get(k)
        out.append({**s.doc(), "defaults": default_params(k), "enabled": r["enabled"] if r else True,
                    "params": {**default_params(k), **((r or {}).get("params") or {})}})
    return ok({"strategies": out, "global_defaults": GLOBAL_DEFAULTS})


class StrategyUpdate(BaseModel):
    enabled: bool | None = None
    params: dict | None = None


@app.put("/api/strategies/{key}")
def update_strategy(key: str, body: StrategyUpdate, uid: str = Depends(user_id)):
    if key not in STRATEGIES:
        raise HTTPException(404, "Unknown strategy")
    defaults = default_params(key)
    params = None
    if body.params is not None:
        bad = [p for p in body.params if p not in defaults]
        if bad:
            raise HTTPException(400, f"Unknown parameters: {bad}")
        params = {}
        for p, v in body.params.items():
            d = defaults[p]
            try:
                params[p] = bool(v) if isinstance(d, bool) else type(d)(v) if d is not None else v
            except (TypeError, ValueError):
                raise HTTPException(400, f"Invalid value for {p}")
    with as_user(uid) as conn:
        conn.execute("""insert into strategy_settings(user_id, strategy_key, enabled, params) values (%s,%s,coalesce(%s,true),coalesce(%s::jsonb,'{}'))
                        on conflict (user_id, strategy_key) do update set enabled=coalesce(%s, strategy_settings.enabled),
                        params=coalesce(%s::jsonb, strategy_settings.params), updated_at=now()""",
                     (uid, key, body.enabled, json.dumps(params) if params is not None else None, body.enabled,
                      json.dumps(params) if params is not None else None))
    return strategies(uid)


@app.get("/api/settings")
def get_settings(uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        r = conn.execute("select settings from user_settings").fetchone()
    return ok({"settings": {**DEFAULT_SETTINGS, **((r or {}).get("settings") or {})},
               "defaults": {**DEFAULT_SETTINGS, "costs": CostModel().__dict__, "rules": Rules().__dict__,
                            "sizing": Sizing().__dict__, "backtest": {k: BT_DEFAULTS[k] for k in
                            ("capital", "oos_split", "min_trades", "random_runs", "seed", "walk_forward_folds")}}})


@app.put("/api/settings")
def put_settings(body: dict, uid: str = Depends(user_id)):
    allowed = set(DEFAULT_SETTINGS)
    s = {k: v for k, v in body.items() if k in allowed}
    with as_user(uid) as conn:
        conn.execute("""insert into user_settings(user_id, settings) values (%s,%s) on conflict (user_id)
                        do update set settings=user_settings.settings || excluded.settings, updated_at=now()""", (uid, json.dumps(s)))
    return get_settings(uid)


# ---------- signals ----------
SIGNAL_LIST_COLS = """id, kind, symbol, company, strategy_key, pattern, action, signal_date, signal_price, entry, entry_date, stop, target,
    status, confirmed, latest_price, latest_date, exit_price, exit_date, exit_reason, outcome, pnl_net, pnl_pct, param_hash, data_source,
    data_updated_at, reason, flags, spec, created_at, updated_at"""


@app.get("/api/signals")
def list_signals(kind: str | None = None, status: str | None = None, strategy: str | None = None, symbol: str | None = None,
                 action: str | None = None, date_from: str | None = Query(None, alias="from"), date_to: str | None = Query(None, alias="to"),
                 page: int = 1, page_size: int = 50, uid: str = Depends(user_id)):
    where, args = ["true"], []
    for col, v in (("kind", kind), ("status", status), ("strategy_key", strategy), ("symbol", symbol and symbol.upper()), ("action", action)):
        if v:
            where.append(f"{col}=%s")
            args.append(v)
    if date_from:
        where.append("signal_date>=%s")
        args.append(date_from)
    if date_to:
        where.append("signal_date<=%s")
        args.append(date_to)
    w = " and ".join(where)
    with as_user(uid) as conn:
        total = conn.execute(f"select count(*) n from signals where {w}", args).fetchone()["n"]
        rows = conn.execute(f"select {SIGNAL_LIST_COLS} from signals where {w} order by signal_date desc, symbol limit %s offset %s",
                            args + [page_size, (page - 1) * page_size]).fetchall()
        stats = conn.execute(f"""select count(*) total, count(*) filter (where status='Open') open, count(*) filter (where status='Target Hit') target,
                                 count(*) filter (where status='Stop-Loss Hit') stop, count(*) filter (where status='Closed') closed,
                                 count(*) filter (where outcome='Win') wins, count(*) filter (where outcome='Loss') losses,
                                 sum(pnl_net) filter (where outcome is not null) net from signals where {w}""", args).fetchone()
    return ok({"total": total, "rows": rows, "stats": stats})


@app.get("/api/signals/{sid}")
def get_signal(sid: str, as_of: bool = False, uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        s = conn.execute("select * from signals where id=%s", (sid,)).fetchone()
        if not s:
            raise HTTPException(404, "Signal not found")
        hist = conn.execute("select status, at_date, price, note, created_at from signal_status_history where signal_id=%s order by id", (sid,)).fetchall()
    sig_date = str(s["signal_date"])
    start = (dt.date.fromisoformat(sig_date) - dt.timedelta(days=400)).isoformat()
    c = chart(s["symbol"], until=sig_date if as_of else None, start=start).body
    return ok({"signal": s, "history": hist, "chart": json.loads(c), "as_of": as_of})


@app.delete("/api/signals/{sid}")
def delete_signal(sid: str, uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        n = conn.execute("delete from signals where id=%s", (sid,)).rowcount
    if not n:
        raise HTTPException(404, "Signal not found")
    return {"deleted": sid}


# ---------- jobs ----------
class JobIn(BaseModel):
    kind: str
    params: dict = {}


@app.post("/api/jobs")
def create_job(j: JobIn, uid: str = Depends(user_id)):
    if j.kind not in ("scan", "backtest", "status_update"):
        raise HTTPException(400, "kind must be scan, backtest or status_update")
    if j.kind == "backtest":
        unknown = [k for k in j.params.get("strategies", []) if k not in STRATEGIES]
        if not j.params.get("strategies") or unknown:
            raise HTTPException(400, f"Select strategies (unknown: {unknown})")
    with as_user(uid) as conn:
        r = conn.execute("insert into jobs(user_id, kind, params) values (%s,%s,%s) returning *", (uid, j.kind, json.dumps(j.params))).fetchone()
    return ok(r)


@app.get("/api/jobs")
def list_jobs(limit: int = 30, uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        return ok(conn.execute("select * from jobs order by created_at desc limit %s", (limit,)).fetchall())


@app.get("/api/jobs/{jid}")
def get_job(jid: str, uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        r = conn.execute("select * from jobs where id=%s", (jid,)).fetchone()
    if not r:
        raise HTTPException(404, "Job not found")
    return ok(r)


# ---------- backtests ----------
@app.get("/api/backtests")
def list_backtests(uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        rows = conn.execute("""select id, name, created_at, seed, results_hash, data_version_id, inputs->'strategies' strategies,
                               inputs->>'start' start, inputs->>'end' "end", results->>'symbols_tested' symbols_tested,
                               results->'ranking' ranking from backtest_runs order by created_at desc""").fetchall()
    return ok(rows)


@app.get("/api/backtests/{rid}")
def get_backtest(rid: str, uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        r = conn.execute("select * from backtest_runs where id=%s", (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "Backtest not found")
    return ok(r)


@app.get("/api/backtests/{rid}/trades")
def bt_trades(rid: str, strategy: str | None = None, segment: str | None = None, status: str | None = None,
              page: int = 1, page_size: int = 100, uid: str = Depends(user_id)):
    w, a = ["run_id=%s"], [rid]
    for col, v in (("strategy_key", strategy), ("segment", segment), ("status", status)):
        if v:
            w.append(f"{col}=%s")
            a.append(v)
    ws = " and ".join(w)
    with as_user(uid) as conn:
        total = conn.execute(f"select count(*) n from backtest_trades where {ws}", a).fetchone()["n"]
        rows = conn.execute(f"""select id, strategy_key, symbol, segment, signal_date, entry_date, entry_price, stop, target, exit_date, exit_price,
                                exit_reason, shares, gross_pnl, costs, net_pnl, ret_pct, status, flags from backtest_trades where {ws}
                                order by signal_date, symbol limit %s offset %s""", a + [page_size, (page - 1) * page_size]).fetchall()
    return ok({"total": total, "rows": rows})


@app.get("/api/backtests/{rid}/trades/{tid}")
def bt_trade(rid: str, tid: int, as_of: bool = False, uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        t = conn.execute("select * from backtest_trades where run_id=%s and id=%s", (rid, tid)).fetchone()
    if not t:
        raise HTTPException(404, "Trade not found")
    sd = str(t["signal_date"])
    start = (dt.date.fromisoformat(sd) - dt.timedelta(days=400)).isoformat()
    end = None if not t["exit_date"] else (t["exit_date"] + dt.timedelta(days=60)).isoformat()
    c = json.loads(chart(t["symbol"], until=sd if as_of else end, start=start).body)
    return ok({"trade": t, "chart": c, "as_of": as_of})


@app.get("/api/dashboard")
def dashboard(uid: str = Depends(user_id)):
    with as_user(uid) as conn:
        s = conn.execute("""select count(*) filter (where kind='live') live, count(*) filter (where kind='historical') historical,
                            count(*) filter (where status='Open' and action='Buy') open, count(*) filter (where action='Watch') watch,
                            count(*) filter (where status='Target Hit') target, count(*) filter (where status='Stop-Loss Hit') stop
                            from signals""").fetchone()
        recent = conn.execute(f"select {SIGNAL_LIST_COLS} from signals where kind='live' order by signal_date desc, created_at desc limit 10").fetchall()
        jobs = conn.execute("select id, kind, status, progress, message, created_at from jobs order by created_at desc limit 5").fetchall()
        bts = conn.execute("select id, name, created_at, results->'ranking' ranking from backtest_runs order by created_at desc limit 5").fetchall()
    return ok({"signals": s, "recent": recent, "jobs": jobs, "backtests": bts, "data": json.loads(data_status().body)})


WEB_DIST = Path(os.environ.get("WEB_DIST", Path(__file__).resolve().parents[3] / "web" / "dist"))
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = WEB_DIST / path
        return FileResponse(f if path and f.is_file() else WEB_DIST / "index.html")
