import { useEffect, useState } from 'react'
import { api, type Json } from '../api'
import { Err, useLoad } from '../components/ui'

export default function Settings() {
  const { data, err } = useLoad(() => api('/settings'))
  const [s, setS] = useState<Json>(null)
  const [msg, setMsg] = useState<unknown>(null)
  useEffect(() => { if (data) setS({ ...data.settings, costs: { ...data.defaults.costs, ...data.settings.costs }, rules: { ...data.defaults.rules, ...data.settings.rules } }) }, [data])
  if (err) return <Err e={err} />
  if (!s) return null
  const save = async () => { try { await api('/settings', { method: 'PUT', body: s }); setMsg('Saved') } catch (e) { setMsg(e) } }
  const group = (g: string, title: string, note?: string) => (
    <div className="card"><h2 style={{ marginTop: 0 }}>{title}</h2>{note && <p className="muted">{note}</p>}
      <div className="grid g4">{Object.entries(s[g]).map(([k, v]) => <div key={k} className="field"><label>{k}</label>
        {typeof v === 'boolean' ? <select value={String(v)} onChange={(e) => setS({ ...s, [g]: { ...s[g], [k]: e.target.value === 'true' } })}><option>true</option><option>false</option></select>
          : typeof v === 'string' ? <select value={v} onChange={(e) => setS({ ...s, [g]: { ...s[g], [k]: e.target.value } })}><option value="next_open">next_open</option><option value="next_close">next_close</option></select>
          : <input type="number" step="any" value={v as number} onChange={(e) => setS({ ...s, [g]: { ...s[g], [k]: Number(e.target.value) } })} />}</div>)}</div></div>)
  return (
    <div>
      <h1>Settings</h1>
      {group('liquidity', 'Liquidity filter', '20-day average volume and traded value (PKR), measured before the signal day.')}
      {group('costs', 'Trading costs (PSX)', 'Brokerage % with per-share minimum, sales tax on brokerage, CDC & NCCPL/SECP per share, slippage %, CGT % on net realised gains per tax year. Verify current rates with your broker.')}
      {group('rules', 'Execution rules', 'Circuit limit is used to flag locked entries/exits (verify current PSX limits).')}
      <div className="card grid g4">
        <div className="field"><label>Position amount for signal P/L (PKR)</label><input type="number" value={s.position_amount} onChange={(e) => setS({ ...s, position_amount: Number(e.target.value) })} /></div>
        <div className="field"><label>Unadjusted symbols in scans</label><select value={String(s.include_unadjusted)} onChange={(e) => setS({ ...s, include_unadjusted: e.target.value === 'true' })}><option value="true">Include (flagged)</option><option value="false">Exclude</option></select></div>
        <div className="field"><label>Live scan: signals from last N sessions</label><input type="number" min={1} value={s.live_lookback_bars} onChange={(e) => setS({ ...s, live_lookback_bars: Number(e.target.value) })} /></div>
      </div>
      <div className="row"><button onClick={save}>Save settings</button>{typeof msg === 'string' ? <span className="pos">{msg}</span> : <Err e={msg} />}</div>
    </div>
  )
}
