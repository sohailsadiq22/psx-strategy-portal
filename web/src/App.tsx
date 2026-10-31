import { useEffect, useState, type ReactNode } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { isSignedIn, signOut } from './api'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Signals from './pages/Signals'
import SignalDetail from './pages/SignalDetail'
import Backtests from './pages/Backtests'
import BacktestDetail from './pages/BacktestDetail'
import TradeDetail from './pages/TradeDetail'
import Strategies from './pages/Strategies'
import Settings from './pages/Settings'
import DataStatus from './pages/DataStatus'

function Shell({ children }: { children: ReactNode }) {
  const nav = useNavigate()
  const [ok, setOk] = useState<boolean | null>(null)
  useEffect(() => { isSignedIn().then(setOk) }, [])
  if (ok === null) return null
  if (!ok) return <Navigate to="/login" replace />
  return (
    <div className="layout">
      <aside className="side">
        <div className="brand">PSX Strategy Portal<small>EOD signals & backtests</small></div>
        <NavLink to="/" end>Dashboard</NavLink>
        <NavLink to="/signals/live">Live signals</NavLink>
        <NavLink to="/signals/historical">Signal history</NavLink>
        <NavLink to="/backtests">Backtests</NavLink>
        <NavLink to="/strategies">Strategies</NavLink>
        <NavLink to="/settings">Settings</NavLink>
        <NavLink to="/data">Data status</NavLink>
        <div className="foot">{localStorage.getItem('psx_email')}<br /><a href="#" onClick={async (e) => { e.preventDefault(); await signOut(); nav('/login') }}>Sign out</a>
          <p>Research tool. Not investment advice. Past results do not guarantee future returns.</p></div>
      </aside>
      <main className="main">{children}</main>
    </div>
  )
}

export default function App() {
  const s = (el: ReactNode) => <Shell>{el}</Shell>
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={s(<Dashboard />)} />
        <Route path="/signals/:kind" element={s(<Signals />)} />
        <Route path="/signal/:id" element={s(<SignalDetail />)} />
        <Route path="/backtests" element={s(<Backtests />)} />
        <Route path="/backtests/:id" element={s(<BacktestDetail />)} />
        <Route path="/backtests/:id/trades/:tid" element={s(<TradeDetail />)} />
        <Route path="/strategies" element={s(<Strategies />)} />
        <Route path="/settings" element={s(<Settings />)} />
        <Route path="/data" element={s(<DataStatus />)} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  )
}
