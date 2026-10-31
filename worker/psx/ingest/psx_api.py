"""PSX Data Portal JSON/HTML endpoints: symbol list, index EOD timeseries, company payouts."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.request
from http.cookiejar import CookieJar

from ..config import PSX_BASE, SOURCE_INDEX, USER_AGENT
from ..db import service


class PSXClient:
    """The portal requires a session cookie and the page key sent as X-Req-Id for XHR endpoints."""

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.key = None

    def _open(self, url, data=None, xhr=False):
        headers = {"User-Agent": USER_AGENT, "Referer": PSX_BASE + "/"}
        if xhr:
            if not self.key:
                self.refresh_key()
            headers |= {"X-Req-Id": self.key, "X-Requested-With": "XMLHttpRequest"}
        req = urllib.request.Request(url, data=data.encode() if data else None, headers=headers)
        body = self.opener.open(req, timeout=40).read().decode("utf-8", "replace")
        time.sleep(self.delay)
        return body

    def refresh_key(self):
        html = self._open(PSX_BASE + "/")
        m = re.search(r'"_k":"([^"]+)"', html)
        if not m:
            raise RuntimeError("PSX portal key not found")
        self.key = m.group(1)

    def json(self, path):
        body = self._open(PSX_BASE + path, xhr=True)
        if body.lstrip().startswith("<"):
            self.refresh_key()
            body = self._open(PSX_BASE + path, xhr=True)
        return json.loads(body)

    def symbols(self) -> list[dict]:
        return self.json("/symbols")

    def eod(self, symbol: str) -> list[list]:
        return self.json(f"/timeseries/eod/{symbol}")["data"]

    def payouts_html(self, symbol: str) -> str:
        return self._open(PSX_BASE + "/company/payouts", data=f"symbol={symbol}", xhr=True)


def load_symbols(client: PSXClient | None = None) -> int:
    client = client or PSXClient()
    rows = client.symbols()
    with service() as conn:
        for r in rows:
            conn.execute(
                """insert into symbols(symbol,name,sector_name,is_etf,is_debt) values (%s,%s,%s,%s,%s)
                   on conflict (symbol) do update set name=coalesce(excluded.name, symbols.name), sector_name=excluded.sector_name,
                   is_etf=excluded.is_etf, is_debt=excluded.is_debt, updated_at=now()""",
                (r["symbol"], r.get("name"), r.get("sectorName"), bool(r.get("isETF")), bool(r.get("isDebt"))))
        conn.commit()
    return len(rows)


def load_index(code: str = "KSE100", client: PSXClient | None = None) -> int:
    client = client or PSXClient()
    data = client.eod(code)
    with service() as conn:
        for ts, close, vol, opn in data:
            d = dt.datetime.fromtimestamp(ts, dt.timezone(dt.timedelta(hours=5))).date()
            conn.execute(
                """insert into index_eod(index_code,date,open,close,volume,source) values (%s,%s,%s,%s,%s,%s)
                   on conflict (index_code,date) do update set open=excluded.open, close=excluded.close, volume=excluded.volume""",
                (code, d, opn, close, vol, SOURCE_INDEX))
        conn.execute("insert into data_versions(kind,source,rows_loaded) values ('index_eod',%s,%s)", (SOURCE_INDEX, len(data)))
        conn.commit()
    return len(data)


def load_payouts(symbols: list[str], client: PSXClient | None = None, progress=None) -> int:
    client = client or PSXClient()
    n = 0
    with service() as conn:
        for k, s in enumerate(symbols):
            try:
                html = client.payouts_html(s)
            except Exception:
                continue
            for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
                tds = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                if len(tds) >= 4:
                    conn.execute(
                        """insert into corporate_actions(symbol,announced_at,period,details,book_closure,source)
                           values (%s,%s,%s,%s,%s,'PSX Data Portal - company payouts') on conflict do nothing""",
                        (s, tds[0], tds[1], tds[2], tds[3]))
                    n += 1
            conn.commit()
            if progress:
                progress(k + 1, len(symbols), f"payouts {s}")
    return n
