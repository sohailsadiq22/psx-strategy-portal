alter table symbols add column if not exists instrument_type text not null default 'equity';
create index if not exists symbols_instrument_type_idx on symbols(instrument_type);
alter table signals add column if not exists spec jsonb;
alter table signals add column if not exists segment text;
create index if not exists signals_user_kind_idx on signals(user_id, kind, signal_date desc);
create index if not exists jobs_status_idx on jobs(status, created_at);
create index if not exists bt_trades_run_idx on backtest_trades(run_id, strategy_key);
