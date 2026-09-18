import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { UsersPage } from './UsersPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('UsersPage', () => {
  it('clears both initial-password fields after user creation', async () => {
    const created = {
      id: 'user-2', username: 'bruno', display_name: 'Bruno',
      is_administrator: false, is_active: true, version: 1,
      created_at: '2026-09-15T12:00:00Z',
    }
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, request) => {
      const payload = request?.method === 'POST' ? created : { items: [], next_cursor: null }
      return Promise.resolve(new Response(JSON.stringify(payload), {
        status: request?.method === 'POST' ? 201 : 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    }))
    const context: AuthContextValue = {
      user: { ...created, id: 'admin-1', username: 'admin', is_administrator: true },
      token: 'token',
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
    }
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}>
      <AuthContext.Provider value={context}><UsersPage /></AuthContext.Provider>
    </QueryClientProvider>)

    await screen.findByText('Select a user')
    const initialPassword = screen.getByLabelText('Initial password')
    const confirmation = screen.getByLabelText('Confirm password')
    await user.type(screen.getByLabelText('Username'), 'bruno')
    await user.type(screen.getByLabelText('Display name'), 'Bruno')
    await user.type(initialPassword, 'temporary password')
    await user.type(confirmation, 'temporary password')
    await user.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('User created'))
    expect(initialPassword).toHaveValue('')
    expect(confirmation).toHaveValue('')
  })
})
