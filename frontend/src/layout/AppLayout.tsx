import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/authContext'

export function AppLayout() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  return (
    <div className="app">
      <header className="topbar">
        <strong>ICTS Rostering</strong>
        <nav>
          <NavLink to="/roster">Roster</NavLink>
          <NavLink to="/workers">Workers</NavLink>
          <NavLink to="/imports">Import</NavLink>
        </nav>
        <span className="spacer" />
        <span className="muted">{user?.display_name} ({user?.app_role.toLowerCase()})</span>
        <button onClick={() => logout().then(() => nav('/login'))}>Sign out</button>
      </header>
      <main className="content"><Outlet /></main>
    </div>
  )
}
