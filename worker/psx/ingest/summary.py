"""Load PSX daily market summary files (all symbols OHLCV + LDCP) into prices_eod.

File format (pipe separated): DATE|SYMBOL|SECTOR|NAME|OPEN|HIGH|LOW|CLOSE|VOLUME|LDCP|...
The exchange publishes LDCP already adjusted on ex-dates, which is used to derive adjustment events.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from ..config import PSX_BASE, RAW_SUMMARY_DIR, SOURCE_SUMMARY, USER_AGENT
from ..db import service

FLAG_RE = re.compile(r"(XD|XB|XR|XA|XI)$")


def download(day: dt.date, out_dir: Path = RAW_SUMMARY_DIR, delay: float = 1.5) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{day.isoformat()}.zip"
    if p.exists() or Path(str(p) + ".404").exists():
        return "skip"
    back = 30
    for _ in range(8):
        try:
            req = urllib.request.Request(f"{PSX_BASE}/download/mkt_summary/{day.isoformat()}.Z", headers={"User-Agent": USER_AGENT})
            b = urllib.request.urlopen(req, timeout=40).read()
            time.sleep(delay)
            if b[:2] == b"PK":
                p.write_bytes(b)
                return "ok"
            if b"Too Many" in b[:800]:
                raise urllib.error.HTTPError("", 429, "", None, None)
            Path(str(p) + ".404").write_text("")
            return "nf"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                Path(str(p) + ".404").write_text("")
                return "nf"
            time.sleep(back)
            back *= 2
    return "err"


def download_range(start: dt.date, end: dt.date, progress=None) -> dict:
    days = [start + dt.timedelta(d) for d in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    counts: dict[str, int] = {}
    for k, d in enumerate(days):
        r = download(d)
        counts[r] = counts.get(r, 0) + 1
        if progress:
            progress(k + 1, len(days), f"downloaded {d}")
    return counts


def parse_file(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        txt = z.read(z.namelist()[0]).decode("latin-1")
    rows = []
    for line in txt.splitlines():
        f = line.split("|")
        if len(f) < 10:
            continue
        try:
            name = f[3].strip()
            m = FLAG_RE.search(name)
            rows.append({
                "date": dt.datetime.strptime(f[0].strip(), "%d%b%Y").date(),
                "symbol": f[1].strip(), "sector_code": f[2].strip(),
                "name": FLAG_RE.sub("", name).strip(), "name_flag": m.group(1) if m else None,
                "open": float(f[4]), "high": float(f[5]), "low": float(f[6]), "close": float(f[7]),
                "volume": int(float(f[8])), "ldcp": float(f[9]) if f[9].strip() else None,
            })
        except ValueError:
            continue
    return pd.DataFrame(rows)


def load_all(raw_dir: Path = RAW_SUMMARY_DIR, progress=None) -> dict:
    files = sorted(raw_dir.glob("*.zip"))
    if not files:
        raise RuntimeError("CONFIGURATION REQUIRED: no market summary files downloaded")
    h = hashlib.sha256()
    with service() as conn:
        loaded = {r["d"] for r in conn.execute("select distinct date as d from prices_eod").fetchall()}
        todo = [f for f in files if dt.date.fromisoformat(f.stem) not in loaded]
        if not todo:
            return {"files": 0, "rows": 0}
        dv = conn.execute(
            "insert into data_versions(kind, source, notes) values ('prices_eod', %s, %s) returning id",
            (SOURCE_SUMMARY, f"{len(todo)} daily files"),
        ).fetchone()["id"]
        total, names = 0, {}
        for k, f in enumerate(todo):
            df = parse_file(f)
            if df.empty:
                continue
            h.update(f.read_bytes())
            bad = df[(df.high < df.low) | (df.close <= 0) | (df.open <= 0)]
            for r in bad.itertuples():
                conn.execute("insert into data_issues(symbol,date,kind,detail) values (%s,%s,'invalid_ohlc',%s) on conflict do nothing",
                             (r.symbol, r.date, f"O{r.open} H{r.high} L{r.low} C{r.close}"))
            df = df.drop(bad.index)
            for r in df[["symbol", "name", "sector_code"]].itertuples(index=False):
                names[r.symbol] = (r.name, r.sector_code)
            with conn.cursor().copy("copy prices_eod(symbol,date,open,high,low,close,volume,ldcp,name_flag,source,data_version_id) from stdin") as cp:
                for r in df.itertuples():
                    cp.write_row((r.symbol, r.date, r.open, r.high, r.low, r.close, r.volume, r.ldcp, r.name_flag, "psx_mkt_summary", dv))
            total += len(df)
            if progress:
                progress(k + 1, len(todo), f"loaded {f.stem}")
            if k % 200 == 0:
                conn.commit()
        for sym, (nm, sec) in names.items():
            conn.execute("""insert into symbols(symbol,name,sector_code) values (%s,%s,%s)
                            on conflict (symbol) do update set name=excluded.name, sector_code=excluded.sector_code""", (sym, nm, sec))
        rng = conn.execute("select min(date) a, max(date) b from prices_eod").fetchone()
        conn.execute("update data_versions set rows_loaded=%s, checksum=%s, first_date=%s, last_date=%s where id=%s",
                     (total, h.hexdigest()[:16], rng["a"], rng["b"], dv))
        conn.commit()
    return {"files": len(todo), "rows": total, "data_version": dv}
