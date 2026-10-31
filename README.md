# PSX Strategy Portal

Pakistan Stock Exchange end-of-day signal scanner and backtester. It uses real PSX data only, with 24 configurable long-only strategies, PSX trading rules, saved per-user history and validation against KSE-100 and random entries.

## Architecture
| Part | Tech | Path |
|---|---|---|
| Database | Postgres / Supabase (Auth + RLS) | `supabase/migrations` |
| Data ingestion | Python | `worker/psx/ingest` |
| Strategy engine | pandas/numpy, causal indicators, confirmed pivots | `worker/psx/engine` |
| Backtester | PSX rules, costs, IS/OOS, walk-forward, benchmarks | `worker/psx/backtest` |
| Background jobs | Postgres job queue (`jobs` table) + worker | `worker/psx/jobs.py` |
| API | FastAPI; every user query runs as `authenticated` role under RLS | `worker/psx/api/app.py` |
| Web | React + TypeScript + lightweight-charts | `web/` |

## Data
- **Prices:** PSX Data Portal daily market summary (`dps.psx.com.pk/download/mkt_summary/YYYY-MM-DD.Z`, a ZIP with pipe-delimited OHLCV, LDCP and XD/XB/XR flags).
- **Adjustment:** on an ex-date PSX publishes LDCP = previous close adjusted for the entitlement. Factor = LDCP / previous close, applied to all earlier bars. Unflagged resets (splits/consolidations) are adjusted the same way and flagged `ADJUSTED_LDCP`. Symbols with history gaps > 10 sessions are marked `UNADJUSTED`.
- **KSE-100:** `dps.psx.com.pk/timeseries/eod/KSE100`, which returns only about 5 years. Earlier benchmark periods show as partial or unavailable.
- Futures (`SYM-MMM`) and debt instruments are excluded from equity scans.
- PSX rate-limits downloads (HTTP 429), so downloads run sequentially with a delay.

## Execution rules
- Entry is at the next session's open after the signal candle. A signal on the latest bar stays pending.
- Same-candle stop and target: the stop is assumed hit first. A gap through the stop exits at the open.
- Close at the lower circuit limit: the exit is marked LOCKED and fills at the next open. Entry bars locked at the upper circuit are skipped.
- One position per stock per strategy. No short selling.
- Costs: brokerage % with a per-share minimum, sales tax on brokerage, CDC and NCCPL/SECP fees, slippage, and CGT per Pakistan tax year (July–June). All are editable; verify current rates.
- Ranking needs at least 30 completed out-of-sample trades, pooled across stocks. Results are compared with KSE-100 buy-and-hold and 100 seeded random-entry runs.

## Run locally
```bash
docker run -d --name psx-pg -e POSTGRES_PASSWORD=postgres -p 54322:5432 postgres:15
psql postgresql://postgres:postgres@localhost:54322/postgres -f supabase/local/00_auth_stub.sql
for f in supabase/migrations/*.sql; do psql postgresql://postgres:postgres@localhost:54322/postgres -f $f; done
python -m venv .venv && . .venv/bin/activate && pip install -r worker/requirements.txt
cd worker
python -c "import datetime as d; from psx.ingest import summary, derive; from psx.ingest.psx_api import PSXClient, load_symbols, load_index; \
  summary.download_range(d.date(2014,1,1), d.date.today()); summary.load_all(); derive.build_adjustments(); derive.refresh_symbols(); \
  c=PSXClient(delay=2); load_symbols(c); load_index('KSE100', c)"
python -m psx.jobs &                                   # background worker
(cd ../web && npm ci && npm run build)
uvicorn psx.api.app:app --port 8000                    # serves API + built web app
```
Daily update: queue an `ingest` job, or call `psx.jobs.daily_update()` from cron after the PSX close.

## Supabase
Apply `supabase/migrations/*` (skip `supabase/local`, which only emulates Supabase auth). Then set:
`DATABASE_URL` (Supabase Postgres connection string), `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET`.
With `SUPABASE_JWT_SECRET` set, the web app signs in through Supabase Auth and the API validates Supabase JWTs.

## Tests
```bash
cd worker && pytest -q          # engine, look-ahead, simulator, costs, API/RLS/persistence
cd web && npm run lint && npm run build
```

## Limitations
- History depth depends on what PSX serves; check the Data status page.
- Corporate-action adjustment uses exchange LDCP and has not been cross-checked against a paid vendor.
- No result here is evidence of future profitability. This is a research tool, not investment advice.
