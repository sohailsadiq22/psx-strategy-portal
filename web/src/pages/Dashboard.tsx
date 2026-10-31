import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, fmt, pct, cls } from '../api'
import { Err, JobProgress, Stat, Tag, useLoad } from '../components/ui'

export default function Dashboard() {
  const { data, err, reload } = useLoad(() => api('/dashboard'))
  const [job, setJob] = useState<string | null>(null)
  const [e2, setE2] = useState<unknown>(null)
  const nav = useNavigate()
  const run = async (kind: string, params: object = {}) => { try { setJob((await api('/jobs', { method: 'POST', body: { kind, params } })).id) } catch (e) { setE2(e) } }
  if (err) return <Err e={err} />
  if (!data) return null
  const d = data.data
  return (
    <div>
      <div className="row"><h1>Dashboard</h1><div className="spacer" />
        <button onClick={() => run('scan', { kind: 'live' })}>Scan latest session</button>
        <button className="sec" onClick={() => run('status_update')}>Update signal statuses</button></div>
      {!d.configured && <div className="banner warn">{d.message}</div>}
      {d.configured && <div className="banner info">Data: {d.prices.symbols} symbols, {d.prices.days} sessions, {d.prices.first} → <b>{d.prices.last}</b> (PSX daily market summary). KSE-100: {d.kse100.first ?? '—'} → {d.kse100.last ?? '—'}.</div>}
      <Err e={e2} />
      {job && <JobProgress id={job} onDone={() => reload()} />}
      <div className="grid g6">
        <Stat k="Live signals" v={data.signals.live} /><Stat k="Historical signals" v={data.signals.historical} />
        <Stat k="Open (Buy)" v={data.signals.open} /><Stat k="Watch" v={data.signals.watch} />
        <Stat k="Target hit" v={data.signals.target} c="pos" /><Stat k="Stop-loss hit" v={data.signals.stop} c="neg" />
      </div>
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Latest live signals</h2><div className="spacer" /><Link to="/signals/live">All live signals →</Link></div>
        {data.recent.length === 0 ? <p className="muted">No live signals yet. Run “Scan latest session”.</p> :
          <table><thead><tr><th>Date</th><th>Symbol</th><th>Strategy</th><th>Action</th><th className="num">Signal</th><th className="num">Stop</th><th className="num">Target</th><th className="num">Latest</th><th className="num">Chg</th><th>Status</th></tr></thead>
            <tbody>{data.recent.map((r: any) => (// eslint-disable-line @typescript-eslint/no-explicit-any
              <tr key={r.id} className="click" onClick={() => nav(`/signal/${r.id}`)}><td>{r.signal_date}</td><td><b>{r.symbol}</b></td><td>{r.pattern}</td><td><Tag v={r.action} /></td>
                <td className="num">{fmt(r.signal_price)}</td><td className="num">{fmt(r.stop)}</td><td className="num">{fmt(r.target)}</td><td className="num">{fmt(r.latest_price)}</td>
                <td className={`num ${cls(r.spec?.change_pct)}`}>{pct(r.spec?.change_pct)}</td><td><Tag v={r.status} /></td></tr>))}</tbody></table>}
      </div>
      <div className="grid g2">
        <div className="card"><h2 style={{ marginTop: 0 }}>Recent jobs</h2>
          <table><tbody>{data.jobs.map((j: any) => <tr key={j.id}><td>{j.kind}</td><td><Tag v={j.status} /></td><td className="muted" style={{ whiteSpace: 'normal' }}>{(j.message ?? '').slice(0, 90)}</td><td>{j.created_at.slice(0, 16).replace('T', ' ')}</td></tr>)}</tbody></table></div>{/* eslint-disable-line @typescript-eslint/no-explicit-any */}
        <div className="card"><h2 style={{ marginTop: 0 }}>Recent backtests</h2>
          {data.backtests.length === 0 ? <p className="muted">None yet. <Link to="/backtests">Run a backtest</Link></p> :
            <table><tbody>{data.backtests.map((b: any) => <tr key={b.id} className="click" onClick={() => nav(`/backtests/${b.id}`)}><td>{b.name || 'Backtest'}</td><td>{b.created_at.slice(0, 16).replace('T', ' ')}</td><td className="muted">{b.ranking?.length ? `${b.ranking.length} ranked` : 'no strategy met sample size'}</td></tr>)}</tbody></table>}{/* eslint-disable-line @typescript-eslint/no-explicit-any */}
        </div>
      </div>
    </div>
  )
}
