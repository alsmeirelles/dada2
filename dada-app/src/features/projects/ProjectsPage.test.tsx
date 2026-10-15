import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { ProjectsPage } from './ProjectsPage'

const project = {
  id: 'project-1', name: 'Road defects', description: null, task_type: 'detection', status: 'active', owner_id: 'owner',
  acquisition_strategy: 'random', dataset_layout: 'split', initial_training_size: null, test_set_size: 1,
  test_set_percentage: null, validation_set_size: 1, validation_set_percentage: null, iteration_batch_size: 2,
  dataset_prepared_at: null, version: 1, created_at: '2026-10-15T12:00:00Z', updated_at: '2026-10-15T12:00:00Z',
}

function renderProjects(batches: { status: number; body: unknown }) {
  const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(
    JSON.stringify(url.endsWith('/batches') ? batches.body : { items: [project], next_cursor: null }),
    { status: url.endsWith('/batches') ? batches.status : 200, headers: { 'Content-Type': 'application/json' } },
  )))
  vi.stubGlobal('fetch', fetch)
  const context: AuthContextValue = {
    user: { id: 'ana', username: 'ana', display_name: 'Ana', is_administrator: false, is_active: true, version: 1, created_at: '2026-10-15T12:00:00Z' },
    token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn(),
  }
  render(<QueryClientProvider client={new QueryClient()}>
    <AuthContext.Provider value={context}><MemoryRouter><ProjectsPage /></MemoryRouter></AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('project card resolution summary', () => {
  it('sums resolved and review-required images over the batches', async () => {
    renderProjects({ status: 200, body: { items: [{ resolved_items: 3, review_required_items: 1 }, { resolved_items: 4, review_required_items: 1 }], next_cursor: null } })

    expect(await screen.findByRole('link', { name: '2 images need review' }, { timeout: 5_000 })).toHaveAttribute('href', '/projects/project-1/consensus')
    expect(screen.getByText('Resolved').nextSibling).toHaveTextContent('7')
  })

  it('hides both for a member who cannot read batches, without retrying', async () => {
    const fetch = renderProjects({ status: 403, body: { error: { code: 'forbidden', message: 'Forbidden.' } } })

    await waitFor(() => expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/batches'))).toHaveLength(1))
    expect(screen.queryByText(/need review/)).not.toBeInTheDocument()
    expect(screen.getByText('Resolved').nextSibling).toHaveTextContent('—')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
