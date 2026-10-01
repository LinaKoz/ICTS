import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/authContext'
import { LogoMark } from '../components/Logo'

const ICON = { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }

const NAV = [
  { to: '/roster', label: 'Roster', icon: <svg {...ICON}><rect x="3.5" y="5" width="17" height="15" rx="2" /><path d="M3.5 10h17M8 3v4M16 3v4M8 14h3M13 14h3M8 17h3" /></svg> },
  { to: '/workers', label: 'Workers', icon: <svg {...ICON}><circle cx="9" cy="8.5" r="3.2" /><path d="M3.5 19c.6-3 2.8-4.6 5.5-4.6s4.9 1.6 5.5 4.6" /><path d="M15.5 5.6a3.1 3.1 0 0 1 0 6M17.4 14.6c1.6.6 2.7 2 3.1 4.4" /></svg> },
  { to: '/imports', label: 'Import', icon: <svg {...ICON}><path d="M12 3.5v11M7.5 10l4.5 4.5 4.5-4.5" /><path d="M4.5 15.5v3a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-3" /></svg> },
]

export function AppLayout() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  return (
    <div className="app">
      <header className="rail">
        <span className="rail-mark" title="ICTS Rostering"><LogoMark size={36} /></span>
        <nav className="rail-nav" aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className="rail-link">{n.icon}<span>{n.label}</span></NavLink>
          ))}
        </nav>
        <div className="rail-user">
          <span className="rail-name">{user?.display_name}<span className="rail-role">{user?.app_role.toLowerCase()}</span></span>
          <button className="rail-signout" onClick={() => logout().then(() => nav('/login'))}>Sign out</button>
        </div>
      </header>
      <main className="content"><Outlet /></main>
    </div>
  )
}
