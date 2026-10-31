-- PSX Strategy Testing Portal schema (Supabase compatible).
-- Market data tables are shared and read-only for users; user tables are protected by RLS.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- market data
create table if not exists data_versions (
  id bigserial primary key,
  created_at timestamptz not null default now(),
  kind text not null,
  source text not null,
  rows_loaded bigint not null default 0,
  first_date date,
  last_date date,
  checksum text,
  notes text
);

create table if not exists symbols (
  symbol text primary key,
  name text,
  sector_code text,
  sector_name text,
  is_etf boolean default false,
  is_debt boolean default false,
  status text not null default 'listed',          -- listed | delisted (no longer in latest file)
  first_date date,
  last_date date,
  bars integer default 0,
  adjustment_status text not null default 'UNADJUSTED', -- ADJUSTED | UNADJUSTED
  adjustment_note text,
  updated_at timestamptz not null default now()
);

create table if not exists prices_eod (
  symbol text not null,
  date date not null,
  open numeric(14,4) not null,
  high numeric(14,4) not null,
  low numeric(14,4) not null,
  close numeric(14,4) not null,
  volume bigint not null,
  ldcp numeric(14,4),
  name_flag text,                -- XD / XB / XR / XA suffix from the exchange file
  source text not null,
  data_version_id bigint references data_versions(id),
  primary key (symbol, date)
);
create index if not exists prices_eod_date_idx on prices_eod(date);

-- Adjustment events derived from the exchange's own LDCP (adjusted previous close) on ex-dates.
create table if not exists adjustment_events (
  symbol text not null,
  ex_date date not null,
  prev_close numeric(14,4) not null,
  adjusted_prev_close numeric(14,4) not null,
  factor double precision not null,  -- multiply prices before ex_date by this
  kind text not null,                -- XD | XB | XR | XA | UNEXPLAINED
  applied boolean not null default true,
  primary key (symbol, ex_date)
);

create table if not exists corporate_actions (
  id bigserial primary key,
  symbol text not null,
  announced_at text,
  period text,
  details text,
  book_closure text,
  source text not null,
  fetched_at timestamptz not null default now(),
  unique (symbol, announced_at, details)
);

create table if not exists index_eod (
  index_code text not null,
  date date not null,
  open numeric(14,4),
  close numeric(14,4) not null,
  volume bigint,
  source text not null,
  primary key (index_code, date)
);

create table if not exists data_issues (
  id bigserial primary key,
  symbol text,
  date date,
  kind text not null,
  detail text,
  created_at timestamptz not null default now(),
  unique (symbol, date, kind)
);

-- ---------------------------------------------------------------- user data
create table if not exists user_settings (
  user_id uuid primary key default auth.uid(),
  settings jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists strategy_settings (
  user_id uuid not null default auth.uid(),
  strategy_key text not null,
  enabled boolean not null default true,
  params jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (user_id, strategy_key)
);

create table if not exists signals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid(),
  kind text not null check (kind in ('live','historical')),
  symbol text not null,
  company text,
  strategy_key text not null,
  pattern text not null,
  action text not null check (action in ('Buy','Sell','Watch')),
  signal_date date not null,
  signal_price numeric(14,4) not null,
  entry numeric(14,4),
  entry_date date,
  stop numeric(14,4),
  target numeric(14,4),
  status text not null default 'Open' check (status in ('Open','Target Hit','Stop-Loss Hit','Closed','Cancelled','Watch')),
  checklist jsonb not null,
  confirmed boolean not null,
  indicators jsonb,
  geometry jsonb,
  reason text not null,
  params jsonb not null,
  param_hash text not null,
  data_source text not null,
  data_version_id bigint,
  data_updated_at timestamptz,
  latest_price numeric(14,4),
  latest_date date,
  exit_price numeric(14,4),
  exit_date date,
  exit_reason text,
  outcome text,
  pnl_net numeric(16,4),
  pnl_pct double precision,
  flags jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, symbol, strategy_key, signal_date, param_hash)
);
create index if not exists signals_user_date_idx on signals(user_id, signal_date desc);

create table if not exists signal_status_history (
  id bigserial primary key,
  signal_id uuid not null references signals(id) on delete cascade,
  user_id uuid not null default auth.uid(),
  status text not null,
  at_date date,
  price numeric(14,4),
  note text,
  created_at timestamptz not null default now()
);

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid(),
  kind text not null,                -- scan | backtest | ingest
  status text not null default 'queued', -- queued | running | done | error
  progress integer not null default 0,
  total integer not null default 0,
  message text,
  params jsonb not null default '{}'::jsonb,
  result_ref text,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);

create table if not exists backtest_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid(),
  job_id uuid references jobs(id) on delete set null,
  name text,
  inputs jsonb not null,
  param_hashes jsonb not null,
  data_version_id bigint,
  seed integer not null,
  results jsonb,
  results_hash text,
  created_at timestamptz not null default now()
);

create table if not exists backtest_trades (
  id bigserial primary key,
  run_id uuid not null references backtest_runs(id) on delete cascade,
  user_id uuid not null default auth.uid(),
  strategy_key text not null,
  symbol text not null,
  segment text not null,            -- train | test
  signal_date date not null,
  entry_date date,
  entry_price numeric(14,4),
  stop numeric(14,4),
  target numeric(14,4),
  exit_date date,
  exit_price numeric(14,4),
  exit_reason text,
  shares bigint,
  gross_pnl numeric(16,4),
  costs numeric(16,4),
  net_pnl numeric(16,4),
  ret_pct double precision,
  status text not null,             -- closed | open | skipped
  flags jsonb not null default '[]'::jsonb,
  signal jsonb
);
create index if not exists backtest_trades_run_idx on backtest_trades(run_id, strategy_key);

-- ---------------------------------------------------------------- RLS
do $$
declare t text;
begin
  foreach t in array array['user_settings','strategy_settings','signals','signal_status_history','jobs','backtest_runs','backtest_trades'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists own_rows on %I', t);
    execute format('create policy own_rows on %I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
    execute format('grant select, insert, update, delete on %I to authenticated', t);
  end loop;
  foreach t in array array['data_versions','symbols','prices_eod','adjustment_events','corporate_actions','index_eod','data_issues'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists read_all on %I', t);
    execute format('create policy read_all on %I for select to authenticated, anon using (true)', t);
    execute format('revoke insert, update, delete on %I from authenticated, anon', t);
    execute format('grant select on %I to authenticated, anon', t);
  end loop;
end $$;
grant usage on all sequences in schema public to authenticated;
