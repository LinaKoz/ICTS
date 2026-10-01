import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './authContext'
import { ErrorPanel } from '../errors/ErrorPanel'
import { ApiError } from '../errors/ApiError'
import { Logo } from '../components/Logo'
import { SHIFT_INFO } from '../features/roster/names'

function DayHero() {
  return (
    <figure className="login-day" aria-hidden="true">
      <div className="login-day-band">
        {(['A', 'B', 'C'] as const).map((s) => (
          <div key={s} className={`login-day-seg band-${s}`}>
            <span className="login-day-shift">Shift {s}</span>
            <span className="login-day-name">{SHIFT_INFO[s].name}</span>
          </div>
        ))}
      </div>
      <div className="login-day-hours"><span>00:00</span><span>08:00</span><span>16:00</span><span>24:00</span></div>
    </figure>
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
          <p className="login-subtitle">Three shifts a day, every day of the month. Generate the roster, fill the gaps, send it for sign-off.</p>
        </header>
        <DayHero />
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
