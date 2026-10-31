import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, cls, fmt, pct, type Json } from '../api'
import { Err, JobProgress, Tag, useLoad } from '../components/ui'

const STATUSES = ['', 'Open', 'Watch', 'Target Hit', 'Stop-Loss Hit', 'Closed', 'Cancelled']

export default function Signals() {
  const { kind = 'live' } = useParams()
  const nav = useNavigate()
  const [f, setF] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [job, setJob] = useState<string | null>(null)
  const [scan, setScan] = useState({ start: '', end: '', symbols: '' })
  const strategies = useLoad(() => api('/strategies'))
  const { data, err, reload } = useLoad(() => api('/signals', { params: { kind, ...f, page, page_size: 50 } }), [kind, JSON.stringify(f), page])
  const [e2, setE2] = useState<unknown>(null)
  const set = (k: string, v: string) => { setPage(1); setF({ ...f, [k]: v }) }
  const runScan = async () => {
    try {
      const params: Json = { kind }
      if (kind === 'historical') { params.start = scan.start || undefined; params.end = scan.end || undefined }
      if (scan.symbols.trim()) params.symbols = scan.symbols.split(/[\s,]+/).filter(Boolean).map((s) => s.toUpperCase())
      setJob((await api('/jobs', { method: 'POST', body: { kind: 'scan', params } })).id)
    } catch (e) { setE2(e) }
  }
  const st = data?.stats
  return (
    <div>
      <div className="row"><h1>{kind === 'live' ? 'Live signals' : 'Signal history'}</h1><Tag v={kind} /></div>
      <div className="banner info">{kind === 'live'
        ? 'Signals detected on the latest completed PSX session. Entry is assumed at the next session’s open.'
        : 'Historical signals found by scanning past data bar-by-bar (each signal uses only data available on its date). Outcomes follow the backtester rules.'}</div>
      <div className="card row">
        {kind === 'historical' && <><div><label>From</label><input type="date" value={scan.start} onChange={(e) => setScan({ ...scan, start: e.target.value })} /></div>
          <div><label>To</label><input type="date" value={scan.end} onChange={(e) => setScan({ ...scan, end: e.target.value })} /></div></>}
        <div style={{ flex: 1 }}><label>Symbols (blank = all liquid equities)</label><input style={{ width: '100%' }} placeholder="e.g. OGDC, PPL, LUCK" value={scan.symbols} onChange={(e) => setScan({ ...scan, symbols: e.target.value })} /></div>
        <div><label>&nbsp;</label><button onClick={runScan}>{kind === 'live' ? 'Scan latest session' : 'Scan history'}</button></div>
      </div>
      <Err e={e2} />
      {job && <JobProgress id={job} onDone={() => reload()} />}
      <div className="card row">
        <select value={f.strategy ?? ''} onChange={(e) => set('strategy', e.target.value)}><option value="">All strategies</option>
          {strategies.data?.strategies.map((s: Json) => <option key={s.key} value={s.key}>{s.number}. {s.name}</option>)}</select>
        <select value={f.status ?? ''} onChange={(e) => set('status', e.target.value)}>{STATUSES.map((s) => <option key={s} value={s}>{s || 'All statuses'}</option>)}</select>
        <select value={f.action ?? ''} onChange={(e) => set('action', e.target.value)}><option value="">Buy & Watch</option><option>Buy</option><option>Watch</option></select>
        <input placeholder="Symbol" value={f.symbol ?? ''} onChange={(e) => set('symbol', e.target.value)} style={{ width: 110 }} />
        <input type="date" value={f.from ?? ''} onChange={(e) => set('from', e.target.value)} /><input type="date" value={f.to ?? ''} onChange={(e) => set('to', e.target.value)} />
        <div className="spacer" />
        {st && <span className="muted">{st.total} signals · {st.open} open · <span className="pos">{st.target} target</span> · <span className="neg">{st.stop} stop</span> · {st.closed} closed · net (per-signal, after costs) <b className={cls(st.net)}>{fmt(st.net, 0)}</b></span>}
      </div>
      <Err e={err} />
      <div className="card scroll">
        <table><thead><tr><th>Signal date</th><th>Symbol</th><th>Strategy / pattern</th><th>Action</th><th>Confirmed</th><th className="num">Signal px</th><th className="num">Entry</th><th className="num">Stop</th><th className="num">Target</th><th className="num">Latest</th><th className="num">Chg</th><th>Status</th><th className="num">Net P/L</th><th>Data</th></tr></thead>
          <tbody>{data?.rows.map((r: Json) => (
            <tr key={r.id} className="click" onClick={() => nav(`/signal/${r.id}`)}>
              <td>{r.signal_date}</td><td><b>{r.symbol}</b><div className="muted" style={{ fontSize: 11 }}>{(r.company ?? '').slice(0, 24)}</div></td><td>{r.pattern}</td><td><Tag v={r.action} /></td>
              <td>{r.confirmed ? '✓' : <span className="warn">pending</span>}</td><td className="num">{fmt(r.signal_price)}</td>
              <td className="num">{r.entry ? fmt(r.entry) : <span className="muted">next open</span>}</td><td className="num">{fmt(r.stop)}</td><td className="num">{fmt(r.target)}</td>
              <td className="num">{fmt(r.latest_price)}<div className="muted" style={{ fontSize: 11 }}>{r.latest_date}</div></td>
              <td className={`num ${cls(r.spec?.change_pct)}`}>{pct(r.spec?.change_pct)}</td><td><Tag v={r.status} /></td>
              <td className={`num ${cls(r.pnl_pct)}`}>{pct(r.pnl_pct)}</td>
              <td>{r.flags?.length ? <span className="warn" title={r.flags.join('\n')}>⚠ {r.flags.length}</span> : ''}</td>
            </tr>))}</tbody></table>
        {data && data.rows.length === 0 && <p className="muted">No signals match. Run a scan above.</p>}
      </div>
      {data && data.total > 50 && <div className="row"><button className="sec small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button><span className="muted">Page {page} / {Math.ceil(data.total / 50)}</span><button className="sec small" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Next</button></div>}
    </div>
  )
}
