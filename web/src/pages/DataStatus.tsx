import { useState } from 'react'
import { api, fmt, type Json } from '../api'
import { Err, Stat, useLoad } from '../components/ui'

export default function DataStatus() {
  const { data, err } = useLoad(() => api('/data/status'))
  const [kind, setKind] = useState('')
  const issues = useLoad(() => api('/data/issues', { params: { kind, limit: 300 } }), [kind])
  if (err) return <Err e={err} />
  if (!data) return null
  const p = data.prices
  return (
    <div>
      <h1>Data status</h1>
      {!data.configured && <div className="banner warn">{data.message}</div>}
      <div className="grid g6"><Stat k="Symbols" v={fmt(p.symbols, 0)} /><Stat k="Sessions" v={fmt(p.days, 0)} /><Stat k="EOD bars" v={fmt(p.bars, 0)} />
        <Stat k="First date" v={p.first ?? '—'} /><Stat k="Last date" v={p.last ?? '—'} /><Stat k="KSE-100 range" v={<span style={{ fontSize: 14 }}>{data.kse100.first ?? '—'} → {data.kse100.last ?? '—'}</span>} /></div>
      <div className="card"><h2 style={{ marginTop: 0 }}>Sources</h2><p>Prices: {data.sources.prices}<br />Index: {data.sources.index}</p>
        <p className="muted">Adjustment method: on each ex-date PSX publishes the previous close adjusted for the entitlement (LDCP). Factor = LDCP / previous close, applied to all earlier bars. Price resets without an XD/XB/XR flag are adjusted the same way and flagged as ADJUSTED_LDCP. Symbols with long history gaps are marked UNADJUSTED.</p></div>
      <div className="grid g3">
        <div className="card"><h3 style={{ marginTop: 0 }}>Adjustment status</h3><table><tbody>{data.adjustment.map((a: Json, i: number) => <tr key={i}><td>{a.instrument_type}</td><td>{a.adjustment_status}</td><td className="num">{a.n}</td></tr>)}</tbody></table></div>
        <div className="card"><h3 style={{ marginTop: 0 }}>Adjustment events</h3><table><tbody>{data.adjustment_events.map((a: Json) => <tr key={a.kind}><td>{a.kind}</td><td className="num">{a.n}</td></tr>)}</tbody></table></div>
        <div className="card"><h3 style={{ marginTop: 0 }}>Load history</h3><table><tbody>{data.versions.map((v: Json) => <tr key={v.id}><td>#{v.id}</td><td>{v.kind}</td><td className="num">{fmt(v.rows_loaded, 0)}</td><td>{String(v.created_at).slice(0, 16)}</td></tr>)}</tbody></table></div>
      </div>
      <div className="card"><div className="row"><h2 style={{ margin: 0 }}>Data issues</h2><select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All</option>{data.issues.map((i: Json) => <option key={i.kind} value={i.kind}>{i.kind} ({i.n})</option>)}</select></div>
        <div className="scroll"><table><thead><tr><th>Date</th><th>Symbol</th><th>Kind</th><th>Detail</th></tr></thead><tbody>{issues.data?.map((i: Json, k: number) => <tr key={k}><td>{i.date}</td><td>{i.symbol}</td><td>{i.kind}</td><td style={{ whiteSpace: 'normal' }}>{i.detail}</td></tr>)}</tbody></table></div></div>
    </div>
  )
}
