import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Json } from '../api'
import { Err, JobProgress, useLoad } from '../components/ui'

export default function Backtests() {
  const nav = useNavigate()
  const list = useLoad(() => api('/backtests'))
  const st = useLoad(() => api('/strategies'))
  const set = useLoad(() => api('/settings'))
  const ds = useLoad(() => api('/data/status'))
  const [f, setF] = useState<Json>({ name: '', symbols: '', start: '', end: '', capital: 1000000, mode: 'separate', sizing_mode: 'pct_equity', pct_equity: 10, fixed_amount: 100000, risk_pct: 1,
    oos_split: 0.7, walk_forward_folds: 0, random_runs: 100, seed: 42, min_trades: 30, max_open: 0, include_unadjusted: true })
  const [sel, setSel] = useState<string[]>([])
  const [costs, setCosts] = useState<Json | null>(null)
  const [job, setJob] = useState<string | null>(null)
  const [e, setE] = useState<unknown>(null)
  const c = costs ?? set.data?.defaults.costs
  const run = async () => {
    setE(null)
    try {
      const body = { name: f.name || `Backtest ${new Date().toISOString().slice(0, 16)}`, symbols: f.symbols.split(/[\s,]+/).filter(Boolean).map((s: string) => s.toUpperCase()),
        start: f.start || null, end: f.end || null, strategies: sel, capital: +f.capital, mode: f.mode, max_open: +f.max_open,
        sizing: { mode: f.sizing_mode, pct_equity: +f.pct_equity, fixed_amount: +f.fixed_amount, risk_pct: +f.risk_pct }, costs: c,
        rules: set.data?.settings.rules ?? {}, liquidity: set.data?.settings.liquidity, oos_split: +f.oos_split, walk_forward_folds: +f.walk_forward_folds,
        random_runs: +f.random_runs, seed: +f.seed, min_trades: +f.min_trades, include_unadjusted: f.include_unadjusted,
        params: Object.fromEntries((st.data?.strategies ?? []).filter((s: Json) => sel.includes(s.key)).map((s: Json) => [s.key, s.params])) }
      setJob((await api('/jobs', { method: 'POST', body: { kind: 'backtest', params: body } })).id)
    } catch (x) { setE(x) }
  }
  const inp = (k: string, label: string, type = 'number', step?: string) => <div className="field"><label>{label}</label><input type={type} step={step} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
  return (
    <div>
      <h1>Backtests</h1>
      {ds.data && <div className="banner info">Available data: {ds.data.prices.first} → {ds.data.prices.last} ({ds.data.prices.days} sessions). The first {Math.round(f.oos_split * 100)}% of the range is in-sample, the rest out-of-sample. A strategy is ranked only with ≥ {f.min_trades} out-of-sample trades (pooled across stocks).</div>}
      <div className="card">
        <h2 style={{ marginTop: 0 }}>New backtest</h2>
        <div className="grid g4">
          {inp('name', 'Name', 'text')}
          <div className="field" style={{ gridColumn: 'span 3' }}><label>Symbols (blank = all liquid equities)</label><input value={f.symbols} placeholder="OGDC, PPL, LUCK …" onChange={(e) => setF({ ...f, symbols: e.target.value })} /></div>
          {inp('start', 'Start date', 'date')}{inp('end', 'End date', 'date')}{inp('capital', 'Initial capital (PKR)')}
          <div className="field"><label>Mode</label><select value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option value="separate">Separate capital per strategy</option><option value="combined">Combined portfolio</option></select></div>
          <div className="field"><label>Position sizing</label><select value={f.sizing_mode} onChange={(e) => setF({ ...f, sizing_mode: e.target.value })}><option value="pct_equity">% of equity</option><option value="fixed_amount">Fixed amount</option><option value="risk">Risk % per trade</option></select></div>
          {f.sizing_mode === 'pct_equity' && inp('pct_equity', '% of equity per trade')}{f.sizing_mode === 'fixed_amount' && inp('fixed_amount', 'Amount per trade (PKR)')}{f.sizing_mode === 'risk' && inp('risk_pct', 'Risk % of equity', 'number', '0.1')}
          {inp('max_open', 'Max open positions (0 = no limit)')}{inp('oos_split', 'In-sample fraction', 'number', '0.05')}{inp('walk_forward_folds', 'Walk-forward windows (0 = off)')}
          {inp('random_runs', 'Random-entry runs')}{inp('seed', 'Random seed')}{inp('min_trades', 'Min trades to rank')}
          <div className="field"><label>Unadjusted symbols</label><select value={String(f.include_unadjusted)} onChange={(e) => setF({ ...f, include_unadjusted: e.target.value === 'true' })}><option value="true">Include (with warning)</option><option value="false">Exclude</option></select></div>
        </div>
        {c && <><h3>Costs (editable)</h3><div className="grid g6">{Object.entries(c).map(([k, v]) => <div key={k} className="field"><label>{k}</label><input type="number" step="0.001" value={v as number} onChange={(e) => setCosts({ ...c, [k]: +e.target.value })} /></div>)}</div></>}
        <h3>Strategies ({sel.length} selected) <a href="#" onClick={(e) => { e.preventDefault(); setSel(st.data.strategies.filter((s: Json) => s.enabled).map((s: Json) => s.key)) }}>select enabled</a> · <a href="#" onClick={(e) => { e.preventDefault(); setSel([]) }}>clear</a></h3>
        <div className="grid g4">{st.data?.strategies.map((s: Json) => <label key={s.key} className="row" style={{ margin: 0, color: 'var(--text)' }}><input type="checkbox" checked={sel.includes(s.key)} onChange={(e) => setSel(e.target.checked ? [...sel, s.key] : sel.filter((x) => x !== s.key))} />{s.number}. {s.name}</label>)}</div>
        <p className="muted">Uses each strategy's saved parameters from the Strategies page. Entry: next session open. Same-candle stop & target: stop first. Gap below stop: exit at open.</p>
        <button disabled={!sel.length} onClick={run}>Run backtest in background</button>
      </div>
      <Err e={e} />
      {job && <JobProgress id={job} onDone={(j) => { list.reload(); if (j.status === 'done' && j.result_ref) nav(`/backtests/${j.result_ref}`) }} />}
      <div className="card"><h2 style={{ marginTop: 0 }}>Saved runs</h2>
        <table><thead><tr><th>Name</th><th>Created</th><th>Strategies</th><th>Symbols</th><th>Ranked</th><th>Result hash</th></tr></thead>
          <tbody>{list.data?.map((b: Json) => <tr key={b.id} className="click" onClick={() => nav(`/backtests/${b.id}`)}><td>{b.name}</td><td>{b.created_at.slice(0, 16).replace('T', ' ')}</td><td>{b.strategies?.length}</td><td>{b.symbols_tested}</td><td>{b.ranking?.length ? b.ranking.join(', ') : <span className="muted">none (insufficient sample)</span>}</td><td className="muted">{b.results_hash?.slice(0, 12)}</td></tr>)}</tbody></table>
        {list.data?.length === 0 && <p className="muted">No backtests yet.</p>}</div>
    </div>
  )
}
