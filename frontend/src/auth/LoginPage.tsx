import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './authContext'
import { ErrorPanel } from '../errors/ErrorPanel'
import { ApiError } from '../errors/ApiError'
import { Logo } from '../components/Logo'

const ART_SHIFTS: [number, number, string][] = [
  [0, 0, '#3b82f6'], [1, 0, '#8b5cf6'], [2, 0, '#14b8a6'], [4, 0, '#3b82f6'],
  [0, 1, '#14b8a6'], [1, 1, '#3b82f6'], [3, 1, '#8b5cf6'], [4, 1, '#14b8a6'], [5, 1, '#3b82f6'],
  [1, 2, '#14b8a6'], [2, 2, '#8b5cf6'], [3, 2, '#3b82f6'], [5, 2, '#8b5cf6'], [6, 2, '#14b8a6'],
  [0, 3, '#8b5cf6'], [2, 3, '#3b82f6'], [4, 3, '#14b8a6'], [6, 3, '#3b82f6'],
]

function RosterArt() {
  return (
    <svg className="login-art" viewBox="0 0 420 290" aria-hidden="true">
      <rect x="0.5" y="0.5" width="419" height="289" rx="16" fill="#0f1218" stroke="#2e303a" />
      {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => (
        <text key={i} x={38 + i * 52} y="34" textAnchor="middle" fontSize="11" fill="#9ca3af">{d}</text>
      ))}
      <rect x="116" y="46" width="44" height="216" rx="8" fill="#60a5fa" opacity="0.1" />
      {ART_SHIFTS.map(([col, row, fill], i) => (
        <rect key={i} x={16 + col * 52} y={52 + row * 52} width="44" height="40" rx="8" fill={fill} opacity="0.85" />
      ))}
    </svg>
  )
}

export function LoginPage() {
  const { login, status } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const from = (loc.state as { from?: string } | null)?.from ?? '/'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authenticated') return <Navigate to={from} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      nav(from, { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login">
      <aside className="login-brand">
        <header className="login-header">
          <h1>
            <Logo />
          </h1>
          <p className="login-subtitle">Plan shifts, manage availability, and review monthly rosters.</p>
        </header>
        <RosterArt />
      </aside>
      <section className="login-main">
      <form onSubmit={submit} className="login-form" aria-busy={busy}>
        <h2>Sign in</h2>
        <div className="login-fields">
          <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus disabled={busy} /></label>
          <label>Password
            <span className="password-field">
              <input type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required disabled={busy} />
              <button
                type="button"
                className={`eye-toggle${showPassword ? ' is-visible' : ''}`}
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-pressed={showPassword}
              >
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path className="eye-outline" d="M1.5 12S5.5 5 12 5s10.5 7 10.5 7-4 7-10.5 7S1.5 12 1.5 12z" />
                  <circle className="eye-pupil" cx="12" cy="12" r="3" />
                  <line className="eye-slash" x1="3" y1="3" x2="21" y2="21" />
                </svg>
              </button>
            </span>
          </label>
        </div>
        {error != null && (error instanceof ApiError && error.status === 401
          ? <div className="login-error" role="alert"><strong>Sign-in failed.</strong> Incorrect username or password.</div>
          : <ErrorPanel error={error} />)}
        <button type="submit" className="login-submit" disabled={busy}>
          {busy && <span className="spinner" aria-hidden="true" />}
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      </section>
    </main>
  )
}
