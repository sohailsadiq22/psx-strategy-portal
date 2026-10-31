"""API + persistence against the local Postgres: auth, RLS isolation, dedupe, settings persistence, CONFIGURATION REQUIRED."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from psx.db import service

try:
    with service() as _c:
        _c.execute("select 1 from prices_eod limit 1")
    DB = True
except Exception:  # noqa: BLE001
    DB = False

pytestmark = pytest.mark.skipif(not DB, reason="local Postgres with schema not available")


@pytest.fixture(scope="module")
def client():
    from psx.api.app import app
    return TestClient(app)


def _user(client):
    email = f"t{uuid.uuid4().hex[:10]}@test.pk"
    r = client.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_auth_required(client):
    assert client.get("/api/signals").status_code == 401
    assert client.get("/api/signals", headers={"Authorization": "Bearer bad"}).status_code == 401


def test_settings_and_strategy_persist(client):
    h = _user(client)
    assert client.put("/api/strategies/hammer", headers=h, json={"enabled": False}).status_code == 200
    assert client.put("/api/strategies/donchian", headers=h, json={"params": {"bogus": 1}}).status_code == 400
    st = {s["key"]: s for s in client.get("/api/strategies", headers=h).json()["strategies"]}
    assert st["hammer"]["enabled"] is False and st["donchian"]["enabled"] is True
    client.put("/api/settings", headers=h, json={"position_amount": 250000})
    assert client.get("/api/settings", headers=h).json()["settings"]["position_amount"] == 250000


def test_scan_dedupe_and_rls_isolation(client):
    from psx.jobs import scan
    h1, h2 = _user(client), _user(client)
    uid1 = client.get("/api/me", headers=h1).json()["user_id"]
    with service() as c:
        sym = c.execute("""select symbol from symbols where instrument_type='equity' and bars > 60 order by bars desc, symbol limit 1""").fetchone()["symbol"]
    a = scan(uid1, "historical", [sym])
    b = scan(uid1, "historical", [sym])
    assert b["new_signals"] == 0 and b["signals_found"] == a["signals_found"]
    s1 = client.get("/api/signals", headers=h1, params={"kind": "historical"}).json()
    assert s1["total"] == a["new_signals"]
    assert client.get("/api/signals", headers=h2).json()["total"] == 0
    if s1["rows"]:
        sid = s1["rows"][0]["id"]
        assert client.get(f"/api/signals/{sid}", headers=h2).status_code == 404
        assert client.delete(f"/api/signals/{sid}", headers=h2).status_code == 404
        d = client.get(f"/api/signals/{sid}", headers=h1, params={"as_of": True}).json()
        assert d["chart"]["dates"][-1] <= d["signal"]["signal_date"], "as-of chart must not include later bars"
        assert d["history"][0]["status"] == "Detected"


def test_backtest_job_persist_and_reproducible(client):
    from psx.jobs import claim_job, run_job
    h = _user(client)
    with service() as c:
        syms = [r["symbol"] for r in c.execute("select symbol from symbols where instrument_type='equity' order by bars desc, symbol limit 3").fetchall()]
    body = {"kind": "backtest", "params": {"symbols": syms, "strategies": ["donchian"], "random_runs": 5, "seed": 7}}
    hashes = []
    for _ in range(2):
        jid = client.post("/api/jobs", headers=h, json=body).json()["id"]
        deadline = time.time() + 180
        while time.time() < deadline:
            j = claim_job()
            if j:
                run_job(j)
            if client.get(f"/api/jobs/{jid}", headers=h).json()["status"] in ("done", "error"):
                break
            if not j:
                time.sleep(0.5)
        job = client.get(f"/api/jobs/{jid}", headers=h).json()
        assert job["status"] == "done", job
        run = client.get(f"/api/backtests/{job['result_ref']}", headers=h).json()
        hashes.append(run["results_hash"])
    assert hashes[0] == hashes[1]


def test_unknown_strategy_rejected(client):
    h = _user(client)
    assert client.post("/api/jobs", headers=h, json={"kind": "backtest", "params": {"strategies": ["nope"]}}).status_code == 400


def test_configuration_required_message():
    from psx.backtest.runner import ConfigurationRequired, run_backtest
    with pytest.raises(ConfigurationRequired):
        run_backtest({"symbols": ["NO_SUCH_SYMBOL"], "strategies": ["donchian"]})
