import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '../../api/client'
import { AuthProvider } from './AuthProvider'
import { useAuth } from './auth-context'
import { authStorage } from './auth-storage'
import { LoginPage } from './LoginPage'
import { RequireAuth } from './RequireAuth'

afterEach(() => {
  cleanup()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

function Projects() {
  const { token } = useAuth()
  useEffect(() => {
    void apiRequest('/api/v1/projects', { token }).catch(() => undefined)
  }, [token])
  return <h1>Projects</h1>
}

describe('I7-05: a request refused with 401', () => {
  it('signs out and returns to the login page with a notice', async () => {
    authStorage.set('expired-token')
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith('/auth/me')
      ? new Response(JSON.stringify({ id: 'u1', username: 'ana', display_name: 'Ana', is_administrator: false, is_active: true, version: 1, created_at: '2026-11-25T10:00:00Z' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      : new Response(JSON.stringify({ error: { code: 'unauthenticated', message: 'Expired.' } }), { status: 401, headers: { 'Content-Type': 'application/json' } }))))

    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/projects']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}><Route path="/projects" element={<Projects />} /></Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>)

    expect(await screen.findByText('Your session ended. Sign in again to continue.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(authStorage.get()).toBeNull()
  })
})
