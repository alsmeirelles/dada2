import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  type PropsWithChildren,
  useCallback,
  useEffect,
  useState,
} from 'react'

import { ApiError, apiRequest } from '../../api/client'
import type { LoginRequest, TokenResponse, User } from '../../api/types'
import { AuthContext, type AuthContextValue } from './auth-context'
import { authStorage } from './auth-storage'

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient()
  const [token, setToken] = useState(authStorage.get)
  const me = useQuery({
    queryKey: ['auth', 'me', token],
    queryFn: () => apiRequest<User>('/api/v1/auth/me', { token }),
    enabled: token !== null,
    retry: false,
  })

  const logout = useCallback(() => {
    authStorage.clear()
    setToken(null)
    queryClient.removeQueries({ queryKey: ['auth'] })
  }, [queryClient])

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) logout()
  }, [logout, me.error])

  const login = useCallback(
    async (credentials: LoginRequest) => {
      const result = await apiRequest<TokenResponse>('/api/v1/auth/token', {
        method: 'POST',
        body: credentials,
      })
      authStorage.set(result.access_token)
      setToken(result.access_token)
    },
    [],
  )

  const value: AuthContextValue = {
    user: me.data ?? null,
    token,
    isLoading: token !== null && me.isLoading,
    login,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
