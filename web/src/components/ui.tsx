import { useEffect, useRef, useState } from 'react'
import { api, type Json } from '../api'

export const Tag = ({ v }: { v?: string | null }) => (v ? <span className={`tag ${v.replace(/\s+/g, '-')}`}>{v}</span> : null)

export function Stat({ k, v, c }: { k: string; v: React.ReactNode; c?: string }) {
  return <div className="card stat"><div className="k">{k}</div><div className={`v ${c ?? ''}`}>{v}</div></div>
}

export function Err({ e }: { e: unknown }) {
  if (!e) return null
  const m = e instanceof Error ? e.message : String(e)
  return <div className={`banner ${m.includes('CONFIGURATION REQUIRED') ? 'warn' : 'err'}`}>{m}</div>
}

export function useLoad<T = Json>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    setLoading(true)
    fn().then((d) => { if (live) { setData(d); setErr(null) } }).catch((e) => live && setErr(e)).finally(() => live && setLoading(false))
    return () => { live = false }
  }, [...deps, tick]) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, err, loading, reload: () => setTick((t) => t + 1) }
}

/** Polls a background job until it finishes. */
export function JobProgress({ id, onDone }: { id: string; onDone?: (j: Json) => void }) {
  const [job, setJob] = useState<Json>(null)
  const done = useRef(false)
  useEffect(() => {
    done.current = false
    const tick = async () => {
      const j = await api(`/jobs/${id}`)
      setJob(j)
      if ((j.status === 'done' || j.status === 'error') && !done.current) { done.current = true; onDone?.(j) }
    }
    tick()
    const h = setInterval(() => { if (!done.current) tick() }, 1500)
    return () => clearInterval(h)
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!job) return null
  return (
    <div className="card">
      <div className="row"><b>{job.kind} job</b><Tag v={job.status} /><span className="muted">{job.message}</span></div>
      {job.status !== 'error' && <div className="progress" style={{ marginTop: 8 }}><div style={{ width: `${job.status === 'done' ? 100 : job.progress}%` }} /></div>}
      {job.status === 'queued' && <div className="muted" style={{ marginTop: 6 }}>Waiting for the background worker…</div>}
      {job.status === 'error' && <div className="banner err" style={{ marginTop: 8 }}>{job.message}</div>}
    </div>
  )
}
