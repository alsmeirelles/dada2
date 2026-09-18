import { KeyRound, LogOut, Users } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../../features/auth/auth-context'
import { Button } from '../ui/Button'

export function AppShell() {
  const { user, logout } = useAuth()

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="app-header">
        <NavLink className="brand" to="/projects" aria-label="DADA projects">
          <span className="brand-mark brand-mark--small" aria-hidden="true">D</span>
          <span>DADA</span>
        </NavLink>
        <nav aria-label="Primary navigation">
          <NavLink to="/projects">Projects</NavLink>
          {user?.is_administrator && <NavLink to="/admin/users"><Users size={16} aria-hidden="true" /> Users</NavLink>}
        </nav>
        <div className="account">
          <NavLink to="/account/password"><KeyRound size={15} aria-hidden="true" />{user?.display_name ?? user?.username ?? 'Account'}</NavLink>
          <Button variant="ghost" onClick={logout} aria-label="Sign out">
            <LogOut size={18} aria-hidden="true" />
          </Button>
        </div>
      </header>
      <div id="main-content" tabIndex={-1}><Outlet /></div>
    </div>
  )
}
