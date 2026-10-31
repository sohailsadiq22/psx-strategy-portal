import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, LineStyle, type IChartApi, type SeriesMarker, type Time, CrosshairMode } from 'lightweight-charts'
import type { Json } from '../api'

export type Levels = { entry?: number | null; stop?: number | null; target?: number | null; exit?: number | null }
export type Mark = { date: string; label: string; color: string; position?: 'aboveBar' | 'belowBar'; shape?: 'arrowUp' | 'arrowDown' | 'circle' | 'square' }

const OVERLAYS = [
  ['sma20', '#f59e0b', 'SMA20'], ['sma50', '#a78bfa', 'SMA50'], ['sma200', '#ec4899', 'SMA200'],
  ['bb_up', '#64748b', 'BB'], ['st_line', '#14b8a6', 'Supertrend'],
] as const

export default function Chart({ data, geometry, levels, marks, height = 460, defaultOverlays = ['sma20', 'sma200'], cutoff }:
  { data: Json; geometry?: Json; levels?: Levels; marks?: Mark[]; height?: number; defaultOverlays?: string[]; cutoff?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const sub = useRef<HTMLDivElement>(null)
  const [on, setOn] = useState<string[]>(defaultOverlays)
  const [lower, setLower] = useState<'rsi14' | 'macd' | 'volume'>('volume')

  useEffect(() => {
    if (!ref.current || !data?.dates?.length) return
    const base = { layout: { background: { type: ColorType.Solid, color: '#121a24' }, textColor: '#8a9bb0' }, grid: { vertLines: { color: '#1b2533' }, horzLines: { color: '#1b2533' } },
      crosshair: { mode: CrosshairMode.Normal }, rightPriceScale: { borderColor: '#253244' }, timeScale: { borderColor: '#253244' } }
    const chart: IChartApi = createChart(ref.current, { ...base, height, width: ref.current.clientWidth })
    const t = (d: string) => d as Time
    const dates: string[] = data.dates
    const cs = chart.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#ef4444' })
    cs.setData(dates.map((d, i) => ({ time: t(d), open: data.open[i], high: data.high[i], low: data.low[i], close: data.close[i] })))
    const line = (vals: (number | null)[], color: string, width = 1, style = LineStyle.Solid) => {
      const s = chart.addLineSeries({ color, lineWidth: width as 1, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
      s.setData(dates.map((d, i) => (vals[i] == null ? { time: t(d) } : { time: t(d), value: vals[i] as number })))
      return s
    }
    for (const [k, c] of OVERLAYS) if (on.includes(k)) {
      if (k === 'bb_up') { line(data.bb_up, c, 1, LineStyle.Dotted); line(data.bb_lo, c, 1, LineStyle.Dotted); line(data.bb_mid, c, 1, LineStyle.Dashed) }
      else line(data[k], c)
    }
    const inRange = (d: string) => d >= dates[0] && d <= dates[dates.length - 1]
    // pattern geometry: lines, polylines, points, boxes
    for (const g of geometry?.lines ?? []) {
      const a = g.from?.date, b = g.to?.date
      if (!a || !b || !inRange(a) || !inRange(b)) continue
      const s = chart.addLineSeries({ color: '#38bdf8', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: g.label })
      s.setData(a === b ? [{ time: t(a), value: g.from.price }] : [{ time: t(a), value: g.from.price }, { time: t(b), value: g.to.price }])
    }
    if (geometry?.polyline?.length) {
      const pts = geometry.polyline.filter((p: Json) => p.date && inRange(p.date))
      const s = chart.addLineSeries({ color: '#38bdf8', lineWidth: 2, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false })
      s.setData(pts.map((p: Json) => ({ time: t(p.date), value: p.price })))
    }
    if (geometry?.box?.from && inRange(geometry.box.from)) {
      for (const v of [geometry.box.low, geometry.box.high]) {
        const s = chart.addLineSeries({ color: '#94a3b8', lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false })
        s.setData(geometry.box.from === geometry.box.to ? [{ time: t(geometry.box.from), value: v }] : [{ time: t(geometry.box.from), value: v }, { time: t(geometry.box.to), value: v }])
      }
    }
    const mk: SeriesMarker<Time>[] = []
    for (const p of geometry?.points ?? []) if (p.date && inRange(p.date)) mk.push({ time: t(p.date), position: 'belowBar', color: '#38bdf8', shape: 'circle', text: p.label })
    for (const m of marks ?? []) if (inRange(m.date)) mk.push({ time: t(m.date), position: m.position ?? 'belowBar', color: m.color, shape: m.shape ?? 'arrowUp', text: m.label })
    mk.sort((a, b) => String(a.time).localeCompare(String(b.time)))
    cs.setMarkers(mk)
    const pl = (price: number | null | undefined, color: string, title: string, style = LineStyle.Dashed) => { if (price != null) cs.createPriceLine({ price: Number(price), color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }) }
    pl(levels?.entry, '#2f81f7', 'Entry'); pl(levels?.stop, '#ef4444', 'Stop'); pl(levels?.target, '#22c55e', 'Target'); pl(levels?.exit, '#e5ecf4', 'Exit', LineStyle.Dotted)
    chart.timeScale().fitContent()

    let lowerChart: IChartApi | null = null
    if (sub.current) {
      lowerChart = createChart(sub.current, { ...base, height: 130, width: sub.current.clientWidth })
      if (lower === 'volume') {
        const v = lowerChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceLineVisible: false })
        v.setData(dates.map((d, i) => ({ time: t(d), value: data.volume[i], color: data.close[i] >= data.open[i] ? '#1f6b3a' : '#7a2a2a' })))
        const a = lowerChart.addLineSeries({ color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
        a.setData(dates.map((d, i) => (data.vol_avg20[i] == null ? { time: t(d) } : { time: t(d), value: data.vol_avg20[i] })))
      } else if (lower === 'rsi14') {
        const r = lowerChart.addLineSeries({ color: '#a78bfa', lineWidth: 1, priceLineVisible: false })
        r.setData(dates.map((d, i) => (data.rsi14[i] == null ? { time: t(d) } : { time: t(d), value: data.rsi14[i] })))
        r.createPriceLine({ price: 70, color: '#64748b', lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: '' })
        r.createPriceLine({ price: 30, color: '#64748b', lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: '' })
      } else {
        const h = lowerChart.addHistogramSeries({ priceLineVisible: false })
        h.setData(dates.map((d, i) => (data.macd_hist[i] == null ? { time: t(d) } : { time: t(d), value: data.macd_hist[i], color: data.macd_hist[i] >= 0 ? '#1f6b3a' : '#7a2a2a' })))
        const m = lowerChart.addLineSeries({ color: '#2f81f7', lineWidth: 1, priceLineVisible: false }); m.setData(dates.map((d, i) => (data.macd[i] == null ? { time: t(d) } : { time: t(d), value: data.macd[i] })))
        const s = lowerChart.addLineSeries({ color: '#f59e0b', lineWidth: 1, priceLineVisible: false }); s.setData(dates.map((d, i) => (data.macd_signal[i] == null ? { time: t(d) } : { time: t(d), value: data.macd_signal[i] })))
      }
      lowerChart.timeScale().fitContent()
      const lc = lowerChart
      chart.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) lc.timeScale().setVisibleLogicalRange(r) })
    }
    const onResize = () => { if (ref.current) chart.applyOptions({ width: ref.current.clientWidth }); if (sub.current && lowerChart) lowerChart.applyOptions({ width: sub.current.clientWidth }) }
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); chart.remove(); lowerChart?.remove() }
  }, [data, geometry, levels, marks, height, on, lower])

  if (!data?.dates?.length) return <div className="banner warn">No price data available for this chart.</div>
  return (
    <div>
      <div className="row" style={{ marginBottom: 6 }}>
        <div className="legend">
          {OVERLAYS.map(([k, c, n]) => (
            <label key={k}><input type="checkbox" checked={on.includes(k)} onChange={(e) => setOn(e.target.checked ? [...on, k] : on.filter((x) => x !== k))} /><span style={{ color: c }}>{n}</span></label>
          ))}
          <span>| geometry <span style={{ color: '#38bdf8' }}>blue</span> · entry <span style={{ color: '#2f81f7' }}>—</span> stop <span className="neg">—</span> target <span className="pos">—</span></span>
        </div>
        <div className="spacer" />
        <select value={lower} onChange={(e) => setLower(e.target.value as 'volume')}><option value="volume">Volume</option><option value="rsi14">RSI 14</option><option value="macd">MACD</option></select>
      </div>
      {cutoff && <div className="banner info">As-of view: chart ends on {cutoff}; no later bars are shown.</div>}
      <div ref={ref} />
      <div ref={sub} style={{ marginTop: 4 }} />
      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{data.adjusted ? 'Prices adjusted with exchange LDCP' : 'Unadjusted prices'} · {data.info?.adjustment_status ?? ''}</div>
    </div>
  )
}
