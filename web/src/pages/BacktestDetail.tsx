import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { createChart, ColorType, type Time } from 'lightweight-charts'
import { api, cls, fmt, pct, type Json } from '../api'
import { Err, Tag, useLoad } from '../components/ui'

function Equity({ curves }: { curves: { name: string; color: string; pts: Json[] }[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const ch = createChart(ref.current, { height: 240, width: ref.current.clientWidth, layout: { background: { type: ColorType.Solid, color: '#121a24' }, textColor: '#8a9bb0' }, grid: { vertLines: { color: '#1b2533' }, horzLines: { color: '#1b2533' } } })
    for (const c of curves) if (c.pts?.length) ch.addLineSeries({ color: c.color, lineWidth: 2, title: c.name }).setData(c.pts.map((p) => ({ time: p.date as Time, value: p.equity })))
    ch.timeScale().fitContent()
    return () => ch.remove()
  }, [curves])
  return <div ref={ref} />
}

const ROWS: [string, string, (v: Json) => string][] = [
  ['total_signals', 'Signals', (v) => fmt(v, 0)], ['trades_taken', 'Trades taken', (v) => fmt(v, 0)], ['completed_trades', 'Completed', (v) => fmt(v, 0)], ['open_trades', 'Open at end', (v) => fmt(v, 0)],
  ['skipped', 'Skipped', (v) => fmt(v, 0)], ['wins', 'Wins', (v) => fmt(v, 0)], ['losses', 'Losses', (v) => fmt(v, 0)], ['win_rate', 'Win rate', (v) => pct(v).replace('+', '')],
  ['gross_pnl', 'Gross P/L', (v) => fmt(v, 0)], ['costs', 'Costs', (v) => fmt(v, 0)], ['cgt', 'CGT', (v) => fmt(v, 0)], ['net_profit', 'Net profit (after costs & CGT)', (v) => fmt(v, 0)],
  ['return_pct', 'Net return', (v) => pct(v)], ['unrealised_open_pnl', 'Unrealised (open)', (v) => fmt(v, 0)], ['profit_factor', 'Profit factor', (v) => fmt(v)], ['max_drawdown_pct', 'Max drawdown', (v) => pct(v)],
  ['avg_win', 'Avg win', (v) => fmt(v, 0)], ['avg_loss', 'Avg loss', (v) => fmt(v, 0)], ['reward_risk', 'Avg win / avg loss', (v) => fmt(v)], ['expectancy', 'Expectancy / trade', (v) => fmt(v, 0)],
  ['expectancy_r', 'Expectancy (R)', (v) => fmt(v)], ['avg_holding_days', 'Avg holding (days)', (v) => fmt(v, 1)],
]

export default function BacktestDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const { data, err } = useLoad(() => api(`/backtests/${id}`), [id])
  const [g, setG] = useState<string>('')
  const [seg, setSeg] = useState('')
  const [page, setPage] = useState(1)
  const res = data?.results
  const key = g || (res ? Object.keys(res.results)[0] : '')
  const trades = useLoad(() => (key ? api(`/backtests/${id}/trades`, { params: { strategy: res?.config.mode === 'combined' ? undefined : key, segment: seg, page, page_size: 100 } }) : Promise.resolve(null)), [id, key, seg, page])
  if (err) return <Err e={err} />
  if (!res) return null
  const r = res.results[key]
  const S = r.segments
  return (
    <div>
      <div className="row"><a href="#" onClick={(e) => { e.preventDefault(); nav('/backtests') }}>← Backtests</a></div>
      <h1>{data.name}</h1>
      <div className="banner info">{res.symbols_tested} symbols · {res.start} → {res.end} · in-sample until {res.split_date}, out-of-sample after · capital PKR {fmt(res.config.capital, 0)} · {res.config.mode} mode · seed {data.seed} · data version #{res.data_version.id} (to {res.data_version.max_date}) · result hash <code>{data.results_hash.slice(0, 16)}</code></div>
      {res.n_warnings > 0 && <div className="banner warn">{res.n_warnings} warnings, e.g. {res.warnings.slice(0, 3).join('; ')}</div>}
      <div className="card"><h2 style={{ marginTop: 0 }}>Strategy comparison (out-of-sample)</h2>
        <table><thead><tr><th>Strategy</th><th className="num">OOS trades</th><th className="num">Win rate</th><th className="num">OOS net return</th><th className="num">KSE-100</th><th className="num">Random mean / p95</th><th className="num">IS net return</th><th>Verdict</th></tr></thead>
          <tbody>{Object.entries(res.results).map(([k, v]: [string, Json]) => { const o = v.segments.out_of_sample; return (
            <tr key={k} className="click" onClick={() => { setG(k); setPage(1) }} style={k === key ? { background: 'var(--panel2)' } : {}}>
              <td><b>{k}</b> {res.ranking.includes(k) && <Tag v={`#${res.ranking.indexOf(k) + 1}`} />}</td><td className="num">{o.completed_trades}</td><td className="num">{pct(o.win_rate).replace('+', '')}</td>
              <td className={`num ${cls(o.return_pct)}`}>{pct(o.return_pct)}</td><td className={`num ${cls(o.kse100?.return_pct)}`}>{pct(o.kse100?.return_pct)}</td>
              <td className="num">{pct(o.random?.mean_return_pct)} / {pct(o.random?.p95_return_pct)}</td><td className={`num ${cls(v.segments.in_sample.return_pct)}`}>{pct(v.segments.in_sample.return_pct)}</td>
              <td className="muted" style={{ whiteSpace: 'normal', maxWidth: 420 }}>{v.verdict}</td></tr>) })}</tbody></table></div>
      <h2>{key}</h2>
      <div className={`banner ${r.eligible ? 'info' : 'warn'}`}>{r.verdict}</div>
      <div className="grid g2">
        <div className="card"><table><thead><tr><th>Metric</th><th className="num">In-sample</th><th className="num">Out-of-sample</th><th className="num">Full</th></tr></thead>
          <tbody>{ROWS.map(([k, n, f]) => <tr key={k}><td className="muted">{n}</td>{['in_sample', 'out_of_sample', 'full'].map((s) => <td key={s} className={`num ${['net_profit', 'return_pct', 'gross_pnl'].includes(k) ? cls(S[s][k]) : ''}`}>{f(S[s][k])}</td>)}</tr>)}
            <tr><td className="muted">KSE-100 buy & hold</td>{['in_sample', 'out_of_sample', 'full'].map((s) => <td key={s} className="num" title={S[s].kse100?.note}>{pct(S[s].kse100?.return_pct)}{S[s].kse100?.coverage && S[s].kse100.coverage !== 'full' ? ' *' : ''}</td>)}</tr>
            <tr><td className="muted">Random entries mean (p5 … p95)</td>{['in_sample', 'out_of_sample'].map((s) => <td key={s} className="num">{pct(S[s].random?.mean_return_pct)} ({pct(S[s].random?.p5_return_pct)} … {pct(S[s].random?.p95_return_pct)})</td>)}<td /></tr>
          </tbody></table>
          <p className="muted" style={{ fontSize: 12 }}>{S.out_of_sample.random?.method} {S.out_of_sample.kse100?.coverage && S.out_of_sample.kse100.coverage !== 'full' ? `* KSE-100 coverage ${S.out_of_sample.kse100.coverage}` : ''}</p></div>
        <div>
          <div className="card"><h3 style={{ marginTop: 0 }}>Equity (mark-to-market)</h3><Equity curves={[{ name: 'In-sample', color: '#a78bfa', pts: S.in_sample.equity_curve }, { name: 'Out-of-sample', color: '#2f81f7', pts: S.out_of_sample.equity_curve }]} /></div>
          <div className="grid g2">
            <div className="card"><h3 style={{ marginTop: 0 }}>By year</h3><table><tbody>{Object.entries(S.full.by_year).map(([y, b]: [string, Json]) => <tr key={y}><td>{y}</td><td className="num">{b.trades} tr</td><td className="num">{pct(b.win_rate).replace('+', '')}</td><td className={`num ${cls(b.net_pnl)}`}>{fmt(b.net_pnl, 0)}</td></tr>)}</tbody></table></div>
            <div className="card"><h3 style={{ marginTop: 0 }}>By market regime (KSE-100 vs 200-day MA)</h3><table><tbody>{Object.entries(S.full.by_regime).map(([y, b]: [string, Json]) => <tr key={y}><td>{y}</td><td className="num">{b.trades} tr</td><td className="num">{pct(b.win_rate).replace('+', '')}</td><td className={`num ${cls(b.net_pnl)}`}>{fmt(b.net_pnl, 0)}</td></tr>)}</tbody></table></div>
          </div>
          {r.walk_forward && <div className="card"><h3 style={{ marginTop: 0 }}>Walk-forward windows</h3><table><thead><tr><th>From</th><th>To</th><th className="num">Trades</th><th className="num">Win</th><th className="num">Return</th><th className="num">Max DD</th></tr></thead><tbody>{r.walk_forward.map((w: Json) => <tr key={w.fold}><td>{w.from}</td><td>{w.to}</td><td className="num">{w.completed_trades}</td><td className="num">{pct(w.win_rate).replace('+', '')}</td><td className={`num ${cls(w.return_pct)}`}>{pct(w.return_pct)}</td><td className="num">{pct(w.max_drawdown_pct)}</td></tr>)}</tbody></table></div>}
        </div>
      </div>
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Trades</h2><select value={seg} onChange={(e) => { setSeg(e.target.value); setPage(1) }}><option value="">All segments</option><option value="in_sample">In-sample</option><option value="out_of_sample">Out-of-sample</option></select>
          <span className="muted">{trades.data?.total ?? 0} rows (closed, open and skipped)</span></div>
        <div className="scroll"><table><thead><tr><th>Signal</th><th>Symbol</th><th>Seg</th><th>Entry date</th><th className="num">Entry</th><th className="num">Stop</th><th className="num">Target</th><th>Exit date</th><th className="num">Exit</th><th>Reason</th><th className="num">Shares</th><th className="num">Costs</th><th className="num">Net P/L</th><th className="num">Ret</th><th>Status</th></tr></thead>
          <tbody>{trades.data?.rows.map((t: Json) => <tr key={t.id} className="click" onClick={() => nav(`/backtests/${id}/trades/${t.id}`)}><td>{t.signal_date}</td><td><b>{t.symbol}</b>{res.config.mode === 'combined' && <div className="muted">{t.strategy_key}</div>}</td><td className="muted">{t.segment === 'out_of_sample' ? 'OOS' : 'IS'}</td>
            <td>{t.entry_date}</td><td className="num">{fmt(t.entry_price)}</td><td className="num">{fmt(t.stop)}</td><td className="num">{fmt(t.target)}</td><td>{t.exit_date}</td><td className="num">{fmt(t.exit_price)}</td>
            <td className="muted" title={(t.flags ?? []).join('\n')}>{t.exit_reason ?? (t.flags?.[0] ?? '')}</td><td className="num">{fmt(t.shares, 0)}</td><td className="num">{fmt(t.costs, 0)}</td><td className={`num ${cls(t.net_pnl)}`}>{fmt(t.net_pnl, 0)}</td><td className={`num ${cls(t.ret_pct)}`}>{pct(t.ret_pct)}</td><td><Tag v={t.status} /></td></tr>)}</tbody></table></div>
        {trades.data && trades.data.total > 100 && <div className="row"><button className="sec small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button><span className="muted">Page {page}</span><button className="sec small" disabled={page * 100 >= trades.data.total} onClick={() => setPage(page + 1)}>Next</button></div>}
      </div>
      <div className="card"><h3 style={{ marginTop: 0 }}>Exact inputs (reproducible)</h3><pre>{JSON.stringify(data.inputs, null, 2)}</pre></div>
    </div>
  )
}
