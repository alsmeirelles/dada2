import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './auth-context'

export function RequireAuth() {
  const { token, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <div className="centered-status">Loading workspace…</div>
  }

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <Outlet />
}
