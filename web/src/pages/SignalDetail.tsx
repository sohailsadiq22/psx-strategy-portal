import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, cls, fmt, pct, type Json } from '../api'
import Chart, { type Mark } from '../components/Chart'
import { Err, Tag, useLoad } from '../components/ui'

export function Checklist({ items }: { items: Json[] }) {
  return <div>{items.map((c: Json, i: number) => (
    <div key={i} className="check"><span className="ic">{c.passed ? <span className="pos">✓</span> : <span className={c.required ? 'neg' : 'warn'}>✗</span>}</span>
      <span>{c.name}{!c.required && <span className="muted"> (optional)</span>}<div className="muted" style={{ fontSize: 12 }}>{c.value}</div></span></div>))}</div>
}

export function KV({ obj }: { obj: Json }) {
  return <table><tbody>{Object.entries(obj ?? {}).map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td className="num">{typeof v === 'number' ? fmt(v, 4) : String(v)}</td></tr>)}</tbody></table>
}

export default function SignalDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [asOf, setAsOf] = useState(false)
  const { data, err } = useLoad(() => api(`/signals/${id}`, { params: { as_of: asOf } }), [id, asOf])
  const marks = useMemo<Mark[]>(() => {
    if (!data) return []
    const s = data.signal
    const m: Mark[] = [{ date: s.signal_date, label: `Signal ${s.action}`, color: s.action === 'Buy' ? '#22c55e' : '#f59e0b', shape: 'arrowUp' }]
    if (!asOf && s.entry_date) m.push({ date: s.entry_date, label: 'Entry', color: '#2f81f7', shape: 'circle' })
    if (!asOf && s.exit_date) m.push({ date: s.exit_date, label: s.status, color: s.outcome === 'Win' ? '#22c55e' : '#ef4444', position: 'aboveBar', shape: 'arrowDown' })
    return m
  }, [data, asOf])
  const levels = useMemo(() => data && ({ entry: data.signal.entry ?? null, stop: data.signal.stop, target: data.signal.target, exit: asOf ? null : data.signal.exit_price }), [data, asOf])
  if (err) return <Err e={err} />
  if (!data) return null
  const s = data.signal
  const del = async () => { if (confirm('Delete this saved signal?')) { await api(`/signals/${id}`, { method: 'DELETE' }); nav(-1) } }
  return (
    <div>
      <div className="row"><a href="#" onClick={(e) => { e.preventDefault(); nav(-1) }}>← Back</a></div>
      <div className="row"><h1>{s.symbol} · {s.pattern}</h1><Tag v={s.kind} /><Tag v={s.action} /><Tag v={s.status} />{s.outcome && <Tag v={s.outcome} />}
        <div className="spacer" /><label className="row" style={{ margin: 0 }}><input type="checkbox" checked={asOf} onChange={(e) => setAsOf(e.target.checked)} /> Show only data known on signal date</label>
        <button className="sec small" onClick={del}>Delete</button></div>
      <p>{s.reason}</p>
      {s.flags?.length > 0 && <div className="banner warn">{s.flags.join(' · ')}</div>}
      <div className="grid g6">
        <div className="card stat"><div className="k">Signal date / price</div><div className="v">{fmt(s.signal_price)}</div><div className="muted">{s.signal_date}</div></div>
        <div className="card stat"><div className="k">Entry (next open)</div><div className="v">{s.entry ? fmt(s.entry) : '—'}</div><div className="muted">{s.entry_date ?? 'awaiting next session'}</div></div>
        <div className="card stat"><div className="k">Stop-loss</div><div className="v neg">{fmt(s.stop)}</div></div>
        <div className="card stat"><div className="k">Target</div><div className="v pos">{s.target ? fmt(s.target) : 'indicator exit'}</div></div>
        <div className="card stat"><div className="k">Latest ({s.latest_date})</div><div className="v">{fmt(s.latest_price)}</div><div className={cls(s.spec?.change_pct)}>{pct(s.spec?.change_pct)} day</div></div>
        <div className="card stat"><div className="k">Outcome (after costs)</div><div className={`v ${cls(s.pnl_pct)}`}>{pct(s.pnl_pct)}</div><div className="muted">{s.exit_reason ?? (s.entry ? 'open, marked at latest close' : '')}</div></div>
      </div>
      <div className="card"><Chart data={data.chart} geometry={s.geometry} levels={levels ?? undefined} marks={marks} cutoff={asOf ? s.signal_date : undefined} /></div>
      <div className="grid g3">
        <div className="card"><h2 style={{ marginTop: 0 }}>Confirmation checklist</h2><Checklist items={s.checklist} />
          <p className="muted">{s.confirmed ? 'All required conditions passed.' : 'Required conditions not all met — shown as Watch.'}</p></div>
        <div className="card"><h2 style={{ marginTop: 0 }}>Status history</h2>
          <table><tbody>{data.history.map((h: Json, i: number) => <tr key={i}><td>{h.at_date}</td><td><Tag v={h.status} /></td><td className="num">{fmt(h.price)}</td><td className="muted" style={{ whiteSpace: 'normal' }}>{h.note}</td></tr>)}</tbody></table>
          <h3>Indicators at signal</h3><KV obj={s.indicators} /></div>
        <div className="card"><h2 style={{ marginTop: 0 }}>Parameters</h2><KV obj={s.params} />
          <p className="muted" style={{ fontSize: 12 }}>Parameter hash {s.param_hash}<br />Source: {s.data_source}<br />Data version #{s.data_version_id}, updated {String(s.data_updated_at).slice(0, 16)}</p></div>
      </div>
    </div>
  )
}
