import { createContext, useContext } from 'react'

import type { LoginRequest, User } from '../../api/types'

export type AuthContextValue = {
  user: User | null
  token: string | null
  isLoading: boolean
  /** True after a request was refused because the session ended, until the next login. */
  sessionExpired: boolean
  login: (credentials: LoginRequest) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider.')
  return context
}
