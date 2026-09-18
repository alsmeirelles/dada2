import { Navigate, Outlet } from 'react-router-dom'

import { useAuth } from './auth-context'

export function RequireAdministrator() {
  const { user } = useAuth()
  return user?.is_administrator ? <Outlet /> : <Navigate to="/projects" replace />
}
