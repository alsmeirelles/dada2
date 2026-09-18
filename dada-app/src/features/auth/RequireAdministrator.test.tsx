import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { User } from '../../api/types'
import { AuthContext, type AuthContextValue } from './auth-context'
import { RequireAdministrator } from './RequireAdministrator'

afterEach(cleanup)

const user: User = {
  id: 'user-1',
  username: 'ana',
  display_name: 'Ana',
  is_administrator: false,
  is_active: true,
  version: 1,
  created_at: '2026-09-15T12:00:00Z',
}

function renderRoute(isAdministrator: boolean) {
  const context: AuthContextValue = {
    user: { ...user, is_administrator: isAdministrator },
    token: 'token',
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }
  render(
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/admin/users']}>
        <Routes>
          <Route element={<RequireAdministrator />}>
            <Route path="/admin/users" element={<div>Global user controls</div>} />
          </Route>
          <Route path="/projects" element={<div>Projects</div>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('RequireAdministrator', () => {
  it('renders global user controls for administrators', () => {
    renderRoute(true)
    expect(screen.getByText('Global user controls')).toBeInTheDocument()
  })

  it('redirects a non-administrator away from global user controls', () => {
    renderRoute(false)
    expect(screen.getByText('Projects')).toBeInTheDocument()
    expect(screen.queryByText('Global user controls')).not.toBeInTheDocument()
  })
})
