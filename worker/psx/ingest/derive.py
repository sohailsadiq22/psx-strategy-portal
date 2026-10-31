"""Derived market data: symbol coverage, adjustment events (from exchange LDCP), data-quality issues,
and the adjusted OHLCV loader used by the engine."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..db import service

RATIO_EPS = 0.0005


def build_adjustments(circuit_pct: float = 7.5) -> dict:
    """On an ex-date PSX publishes LDCP = previous close adjusted for the entitlement.
    factor = LDCP_t / close_(t-1). Applied cumulatively to all bars before the ex-date."""
    with service() as conn:
        df = pd.DataFrame(conn.execute(
            "select symbol, date, close::float8 close, ldcp::float8 ldcp, name_flag from prices_eod order by symbol, date").fetchall())
        if df.empty:
            return {"events": 0}
        df["prev_close"] = df.groupby("symbol")["close"].shift(1)
        cal = {d: i for i, d in enumerate(sorted(df["date"].unique()))}
        df["cal_i"] = df["date"].map(cal)
        df["gap"] = df["cal_i"] - df.groupby("symbol")["cal_i"].shift(1)
        df["ratio"] = df["ldcp"] / df["prev_close"]
        ev = df[df["prev_close"].notna() & df["ldcp"].notna() & ((df["ratio"] - 1).abs() > RATIO_EPS)].copy()
        conn.execute("delete from adjustment_events")
        conn.execute("delete from data_issues where kind in ('unexplained_ldcp','large_gap','history_gap')")
        for r in df[df["gap"] > 10].itertuples():
            conn.execute("insert into data_issues(symbol,date,kind,detail) values (%s,%s,'history_gap',%s) on conflict do nothing",
                         (r.symbol, r.date, f"No bars for {int(r.gap) - 1} market days before this date"))
        n_app = 0
        for r in ev.itertuples():
            kind = r.name_flag if r.name_flag else "LDCP_RESET"
            conn.execute(
                "insert into adjustment_events(symbol,ex_date,prev_close,adjusted_prev_close,factor,kind,applied) values (%s,%s,%s,%s,%s,%s,true)",
                (r.symbol, r.date, r.prev_close, r.ldcp, float(r.ratio), kind))
            n_app += 1
            if not r.name_flag:
                conn.execute("insert into data_issues(symbol,date,kind,detail) values (%s,%s,'unexplained_ldcp',%s) on conflict do nothing",
                             (r.symbol, r.date, f"Exchange LDCP {r.ldcp} differs from prev close {r.prev_close} without XD/XB/XR flag "
                                                f"(split/consolidation or unflagged entitlement); adjusted using exchange LDCP"))
        # large moves vs LDCP beyond circuit breaker (possible data error or circuit-free day)
        df["move"] = (df["close"] / df["ldcp"] - 1).abs() * 100
        big = df[df["move"] > circuit_pct * 1.5 + 1]
        for r in big.itertuples():
            conn.execute("insert into data_issues(symbol,date,kind,detail) values (%s,%s,'large_gap',%s) on conflict do nothing",
                         (r.symbol, r.date, f"close {r.close} vs LDCP {r.ldcp} ({r.move:.1f}%)"))
        conn.commit()
    return {"events": len(ev), "applied": n_app}


def refresh_symbols() -> int:
    with service() as conn:
        last = conn.execute("select max(date) d from prices_eod").fetchone()["d"]
        conn.execute("""
            insert into symbols(symbol, first_date, last_date, bars)
            select symbol, min(date), max(date), count(*) from prices_eod group by symbol
            on conflict (symbol) do update set first_date=excluded.first_date, last_date=excluded.last_date, bars=excluded.bars, updated_at=now()""")
        conn.execute("update symbols set status = case when last_date < %s::date - 10 then 'delisted' else 'listed' end where last_date is not null", (last,))
        conn.execute(r"""update symbols set instrument_type = case
                          when symbol ~ '-(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]?$' then 'future'
                          when coalesce(is_debt,false) then 'debt'
                          when coalesce(is_etf,false) then 'etf'
                          else 'equity' end""")
        conn.execute("""update symbols s set adjustment_status = case
                          when exists (select 1 from adjustment_events e where e.symbol=s.symbol and e.kind='LDCP_RESET') then 'ADJUSTED_LDCP'
                          else 'ADJUSTED' end,
                        adjustment_note = case
                          when exists (select 1 from adjustment_events e where e.symbol=s.symbol and e.kind='LDCP_RESET')
                          then 'Adjusted with exchange LDCP; includes price resets without an XD/XB/XR flag (verify against PSX notices)'
                          else 'Adjusted with exchange LDCP on ex-dates (dividends, bonus, rights)' end
                        where s.bars > 0""")
        conn.execute("""update symbols s set adjustment_status='UNADJUSTED',
                          adjustment_note='Price history has gaps over 10 trading days in loaded data; corporate actions inside gaps cannot be verified'
                        where exists (select 1 from data_issues d where d.symbol=s.symbol and d.kind='history_gap')""")
        n = conn.execute("select count(*) n from symbols where bars > 0").fetchone()["n"]
        conn.commit()
    return n


def set_names_from_files(names: dict[str, tuple[str, str]]):
    with service() as conn:
        for s, (name, sector) in names.items():
            conn.execute("update symbols set name=coalesce(name,%s), sector_code=coalesce(sector_code,%s) where symbol=%s", (name, sector, s))
        conn.commit()


def load_ohlcv(symbol: str, start=None, end=None, adjusted: bool = True, conn=None) -> pd.DataFrame:
    """Return OHLCV (adjusted for corporate actions by default). Columns: date, open, high, low, close, volume, ldcp."""
    own = conn is None
    if own:
        cm = service()
        conn = cm.__enter__()
    try:
        rows = conn.execute(
            """select date, open::float8 open, high::float8 high, low::float8 low, close::float8 close, volume::float8 volume, ldcp::float8 ldcp
               from prices_eod where symbol=%s and (%s::date is null or date>=%s::date) and (%s::date is null or date<=%s::date) order by date""",
            (symbol, start, start, end, end)).fetchall()
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "ldcp"])
        if df.empty or not adjusted:
            return df
        ev = conn.execute("select ex_date, factor from adjustment_events where symbol=%s and applied order by ex_date", (symbol,)).fetchall()
    finally:
        if own:
            cm.__exit__(None, None, None)
    return apply_adjustments(df, [(e["ex_date"], e["factor"]) for e in ev])


def apply_adjustments(df: pd.DataFrame, events: list[tuple]) -> pd.DataFrame:
    if not events:
        return df
    df = df.copy()
    f = np.ones(len(df))
    dates = pd.to_datetime(df["date"]).dt.date.to_numpy()
    for ex, fac in events:
        f[dates < ex] *= fac
    for k in ("open", "high", "low", "close", "ldcp"):
        df[k] = df[k] * f
    df["volume"] = df["volume"] / f
    return df


def load_index_series(code: str = "KSE100", conn=None) -> pd.DataFrame:
    own = conn is None
    if own:
        cm = service()
        conn = cm.__enter__()
    try:
        rows = conn.execute("select date, open::float8 open, close::float8 close from index_eod where index_code=%s order by date", (code,)).fetchall()
    finally:
        if own:
            cm.__exit__(None, None, None)
    return pd.DataFrame(rows, columns=["date", "open", "close"])
