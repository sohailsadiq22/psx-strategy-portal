import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { signIn } from '../api'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [reg, setReg] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await signIn(email, password, reg); nav('/') } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="login card">
      <h1>PSX Strategy Portal</h1>
      <p className="muted">Real PSX end-of-day data. Signals, history and backtests are saved to your account.</p>
      <form onSubmit={submit}>
        <div className="field"><label>Email</label><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
        <div className="field"><label>Password (min 8 characters)</label><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} /></div>
        {err && <div className="banner err">{err}</div>}
        <div className="row"><button disabled={busy}>{reg ? 'Create account' : 'Sign in'}</button><div className="spacer" />
          <a href="#" onClick={(e) => { e.preventDefault(); setReg(!reg) }}>{reg ? 'Have an account? Sign in' : 'New here? Create account'}</a></div>
      </form>
    </div>
  )
}
