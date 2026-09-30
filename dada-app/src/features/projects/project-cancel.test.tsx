import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { DraftProjectSetupPage } from './DraftProjectSetupPage'
import { NewProjectPage } from './NewProjectPage'
import { loadSetup, saveSetup } from './setup-recovery'
import type { Project } from './types'

const project: Project = {
  id: 'project-1', name: 'Road defects', description: null, task_type: 'detection',
  status: 'draft', owner_id: 'owner', acquisition_strategy: 'random', dataset_layout: 'split',
  initial_training_size: null, test_set_size: 1, test_set_percentage: null, validation_set_size: 1,
  validation_set_percentage: null, iteration_batch_size: 2, dataset_prepared_at: null, version: 1,
  created_at: '2026-09-30T12:00:00Z', updated_at: '2026-09-30T12:00:00Z',
}

function payload(url: string) {
  if (url.endsWith('/annotation-policy')) return { mode: 'single', version: 1, annotator_ids: [] }
  if (url.endsWith('/members') || url.endsWith('/classes')) return { items: [], next_cursor: null }
  if (url.endsWith('/dataset-layout')) return { dataset_layout: 'split', prepared_at: null, train_size: 0, validation_size: 0, test_size: 0, first_training_batch_size: null, training_pool_size: 0, batch_ids: [], annotation_import_id: null }
  if (url.endsWith('/capabilities')) return { consensus_resolvers: {} }
  return project
}

function renderAt(path: string, page: ReactNode) {
  const fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => Promise.resolve(
    init?.method === 'DELETE'
      ? new Response(null, { status: 204 })
      : new Response(JSON.stringify(payload(url)), { status: 200, headers: { 'Content-Type': 'application/json' } }),
  ))
  vi.stubGlobal('fetch', fetch)
  vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
  const context: AuthContextValue = {
    user: { id: 'owner', username: 'owner', display_name: 'Owner', is_administrator: false, is_active: true, version: 1, created_at: '2026-09-30T12:00:00Z' },
    token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn(),
  }
  render(<QueryClientProvider client={new QueryClient()}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects" element={<p>Projects list</p>} />
          <Route path="/projects/new" element={page} />
          <Route path="/projects/:projectId/setup" element={page} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

beforeEach(() => sessionStorage.clear())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('cancelling project creation', () => {
  it('deletes a draft and forgets its local setup', async () => {
    saveSetup({ projectId: 'project-1', stage: 'policy' })
    const fetch = renderAt('/projects/project-1/setup', <DraftProjectSetupPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Cancel project creation' }))

    expect(await screen.findByText('Projects list')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/v1/projects/project-1'), expect.objectContaining({ method: 'DELETE' }))
    expect(loadSetup()).toBeNull()
  })

  it('discards an unsaved wizard without touching the server or other drafts', async () => {
    saveSetup({ projectId: 'another-draft', stage: 'classes' })
    const fetch = renderAt('/projects/new', <NewProjectPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Cancel project creation' }))

    expect(await screen.findByText('Projects list')).toBeInTheDocument()
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    expect(loadSetup()?.projectId).toBe('another-draft')
  })
})
