import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './authContext'

export function RequireAuth() {
  const { status } = useAuth()
  const loc = useLocation()
  if (status === 'loading') return <div className="center muted">Loading…</div>
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />
  return <Outlet />
}
