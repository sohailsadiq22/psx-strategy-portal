import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, cls, fmt, pct } from '../api'
import Chart, { type Mark } from '../components/Chart'
import { Err, Tag, useLoad } from '../components/ui'
import { Checklist, KV } from './SignalDetail'

export default function TradeDetail() {
  const { id, tid } = useParams()
  const nav = useNavigate()
  const [asOf, setAsOf] = useState(false)
  const { data, err } = useLoad(() => api(`/backtests/${id}/trades/${tid}`, { params: { as_of: asOf } }), [id, tid, asOf])
  const t = data?.trade
  const marks = useMemo<Mark[]>(() => {
    if (!t) return []
    const m: Mark[] = [{ date: t.signal_date, label: 'Signal', color: '#22c55e' }]
    if (!asOf && t.entry_date) m.push({ date: t.entry_date, label: 'Entry', color: '#2f81f7', shape: 'circle' })
    if (!asOf && t.exit_date) m.push({ date: t.exit_date, label: 'Exit', color: Number(t.net_pnl) > 0 ? '#22c55e' : '#ef4444', position: 'aboveBar', shape: 'arrowDown' })
    return m
  }, [t, asOf])
  const levels = useMemo(() => t && { entry: t.entry_price, stop: t.stop, target: t.target, exit: asOf ? null : t.exit_price }, [t, asOf])
  if (err) return <Err e={err} />
  if (!t) return null
  const s = t.signal ?? {}
  const cd = s.cost_detail
  return (
    <div>
      <div className="row"><a href="#" onClick={(e) => { e.preventDefault(); nav(-1) }}>← Back to backtest</a></div>
      <div className="row"><h1>{t.symbol} · {s.pattern ?? t.strategy_key}</h1><Tag v={t.status} /><Tag v={t.segment === 'out_of_sample' ? 'Out-of-sample' : 'In-sample'} />
        <div className="spacer" /><label className="row" style={{ margin: 0 }}><input type="checkbox" checked={asOf} onChange={(e) => setAsOf(e.target.checked)} /> Show only data known on signal date</label></div>
      <p>{s.reason}</p>
      {t.flags?.length > 0 && <div className="banner warn">{t.flags.join(' · ')}</div>}
      <div className="grid g6">
        <div className="card stat"><div className="k">Signal</div><div className="v">{t.signal_date}</div></div>
        <div className="card stat"><div className="k">Entry (incl. slippage)</div><div className="v">{fmt(t.entry_price)}</div><div className="muted">{t.entry_date}</div></div>
        <div className="card stat"><div className="k">Stop / target</div><div className="v"><span className="neg">{fmt(t.stop)}</span> / <span className="pos">{fmt(t.target)}</span></div></div>
        <div className="card stat"><div className="k">Exit</div><div className="v">{fmt(t.exit_price)}</div><div className="muted">{t.exit_date} · {t.exit_reason}</div></div>
        <div className="card stat"><div className="k">Shares · costs</div><div className="v">{fmt(t.shares, 0)}</div><div className="muted">costs PKR {fmt(t.costs, 0)}</div></div>
        <div className="card stat"><div className="k">Net P/L after costs</div><div className={`v ${cls(t.net_pnl)}`}>{fmt(t.net_pnl, 0)}</div><div className={cls(t.ret_pct)}>{pct(t.ret_pct)}</div></div>
      </div>
      <div className="card"><Chart data={data.chart} geometry={s.geometry} levels={levels ?? undefined} marks={marks} cutoff={asOf ? t.signal_date : undefined} /></div>
      <div className="grid g3">
        <div className="card"><h2 style={{ marginTop: 0 }}>Confirmation checklist</h2><Checklist items={s.checks ?? []} /></div>
        <div className="card"><h2 style={{ marginTop: 0 }}>Indicators at signal</h2><KV obj={s.indicators} /></div>
        <div className="card"><h2 style={{ marginTop: 0 }}>Cost detail</h2>{cd ? <KV obj={cd} /> : <p className="muted">Gross P/L {fmt(t.gross_pnl, 0)} − costs {fmt(t.costs, 0)} = net {fmt(t.net_pnl, 0)} (CGT applied per tax year at portfolio level).</p>}</div>
      </div>
    </div>
  )
}
