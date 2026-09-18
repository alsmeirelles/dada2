import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { ChangePasswordPage } from './ChangePasswordPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ChangePasswordPage', () => {
  it('clears every credential field after a successful change', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    const context: AuthContextValue = {
      user: {
        id: 'user-1', username: 'ana', display_name: 'Ana',
        is_administrator: false, is_active: true, version: 1,
        created_at: '2026-09-15T12:00:00Z',
      },
      token: 'token',
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
    }
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}>
      <AuthContext.Provider value={context}><ChangePasswordPage /></AuthContext.Provider>
    </QueryClientProvider>)

    const current = screen.getByLabelText('Current password')
    const replacement = screen.getByLabelText(/^New password/)
    const confirmation = screen.getByLabelText('Confirm new password')
    await user.type(current, 'old password')
    await user.type(replacement, 'new password')
    await user.type(confirmation, 'new password')
    await user.click(screen.getByRole('button', { name: 'Change password' }))

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Password changed'))
    expect(current).toHaveValue('')
    expect(replacement).toHaveValue('')
    expect(confirmation).toHaveValue('')
  })
})
