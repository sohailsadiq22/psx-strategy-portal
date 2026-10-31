import { useState } from 'react'
import { api, type Json } from '../api'
import { Err, useLoad } from '../components/ui'

function Editor({ s, onSaved }: { s: Json; onSaved: () => void }) {
  const [p, setP] = useState<Json>(s.params)
  const [msg, setMsg] = useState<unknown>(null)
  const save = async (body: Json) => { try { await api(`/strategies/${s.key}`, { method: 'PUT', body }); setMsg('Saved'); onSaved() } catch (e) { setMsg(e) } }
  return (
    <div>
      <div className="grid g4">{Object.entries(p).map(([k, v]) => (
        <div key={k} className="field"><label>{k}{s.defaults[k] !== v && <span className="warn"> (default {String(s.defaults[k])})</span>}</label>
          {typeof s.defaults[k] === 'boolean' ? <select value={String(v)} onChange={(e) => setP({ ...p, [k]: e.target.value === 'true' })}><option value="true">true</option><option value="false">false</option></select>
            : <input type="number" step="any" value={v as number} onChange={(e) => setP({ ...p, [k]: e.target.value === '' ? '' : Number(e.target.value) })} />}</div>))}</div>
      <div className="row"><button className="small" onClick={() => save({ params: p })}>Save parameters</button><button className="sec small" onClick={() => { setP(s.defaults); save({ params: s.defaults }) }}>Reset to defaults</button>
        {typeof msg === 'string' ? <span className="pos">{msg}</span> : <Err e={msg} />}</div>
    </div>
  )
}

export default function Strategies() {
  const { data, err, reload } = useLoad(() => api('/strategies'))
  const [open, setOpen] = useState<string | null>(null)
  if (err) return <Err e={err} />
  if (!data) return null
  const toggle = async (key: string, enabled: boolean) => { await api(`/strategies/${key}`, { method: 'PUT', body: { enabled } }); reload() }
  return (
    <div>
      <h1>Strategies</h1>
      <p className="muted">24 long-only EOD strategies. Pivots are confirmed only after {data.global_defaults.pivot_n} bars on both sides; no strategy uses future bars. Changing parameters changes the parameter hash, so saved signals and runs keep the exact set used.</p>
      {data.strategies.map((s: Json) => (
        <div key={s.key} className="card">
          <div className="row"><label className="row" style={{ margin: 0, color: 'var(--text)' }}><input type="checkbox" checked={s.enabled} onChange={(e) => toggle(s.key, e.target.checked)} /><b>{s.number}. {s.name}</b></label>
            <span className="tag">{s.category}</span><span className="tag">tier {s.tier}</span>{!s.enabled && <span className="muted">disabled</span>}<div className="spacer" />
            <button className="sec small" onClick={() => setOpen(open === s.key ? null : s.key)}>{open === s.key ? 'Close' : 'Rules & parameters'}</button></div>
          {open === s.key && <div style={{ marginTop: 10 }}>
            <table><tbody>{[['Entry', s.entry_rule], ['Confirmation', s.confirmation_rule], ['Exit', s.exit_rule], ['Invalidation', s.invalidation_rule]].map(([k, v]) => <tr key={k}><td className="muted" style={{ width: 110 }}>{k}</td><td style={{ whiteSpace: 'normal' }}>{v}</td></tr>)}</tbody></table>
            <h3>Parameters</h3><Editor s={s} onSaved={reload} /></div>}
        </div>))}
    </div>
  )
}
