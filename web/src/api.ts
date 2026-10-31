import { createClient, type SupabaseClient } from '@supabase/supabase-js'

export type Json = any // eslint-disable-line @typescript-eslint/no-explicit-any

let supabase: SupabaseClient | null = null
let cfg: { auth_mode: string; supabase_url: string | null; supabase_anon_key: string | null } | null = null
const TOKEN_KEY = 'psx_token'

export async function loadConfig() {
  if (!cfg) {
    cfg = await (await fetch('/api/config')).json()
    if (cfg!.auth_mode === 'supabase' && cfg!.supabase_url && cfg!.supabase_anon_key) supabase = createClient(cfg!.supabase_url, cfg!.supabase_anon_key)
  }
  return cfg!
}

async function token(): Promise<string | null> {
  if (supabase) return (await supabase.auth.getSession()).data.session?.access_token ?? null
  return localStorage.getItem(TOKEN_KEY)
}

export async function signIn(email: string, password: string, register: boolean) {
  await loadConfig()
  if (supabase) {
    const r = register ? await supabase.auth.signUp({ email, password }) : await supabase.auth.signInWithPassword({ email, password })
    if (r.error) throw new Error(r.error.message)
    if (!r.data.session) throw new Error('Check your email to confirm the account, then sign in.')
    localStorage.setItem('psx_email', email)
    return
  }
  const r = await fetch(`/api/auth/${register ? 'register' : 'login'}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) })
  const j = await r.json()
  if (!r.ok) throw new Error(j.detail ?? 'Sign-in failed')
  localStorage.setItem(TOKEN_KEY, j.access_token)
  localStorage.setItem('psx_email', j.email)
}

export async function signOut() {
  if (supabase) await supabase.auth.signOut()
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem('psx_email')
}

export async function isSignedIn() {
  await loadConfig()
  return !!(await token())
}

export class ApiError extends Error {
  status: number
  constructor(status: number, msg: string) { super(msg); this.status = status }
}

export async function api<T = Json>(path: string, opts: { method?: string; body?: unknown; params?: Record<string, unknown> } = {}): Promise<T> {
  const t = await token()
  const q = opts.params ? '?' + new URLSearchParams(Object.entries(opts.params).filter(([, v]) => v !== undefined && v !== '' && v !== null).map(([k, v]) => [k, String(v)])).toString() : ''
  const r = await fetch(`/api${path}${q}`, {
    method: opts.method ?? 'GET',
    headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  if (r.status === 401) { await signOut(); window.location.href = '/login'; throw new ApiError(401, 'Signed out') }
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j))
  return j as T
}

export const fmt = (v: unknown, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('en-PK', { minimumFractionDigits: d, maximumFractionDigits: d }))
export const pct = (v: unknown, d = 2) => (v === null || v === undefined ? '—' : `${Number(v) >= 0 ? '+' : ''}${fmt(v, d)}%`)
export const cls = (v: unknown) => (v === null || v === undefined ? '' : Number(v) > 0 ? 'pos' : Number(v) < 0 ? 'neg' : '')
