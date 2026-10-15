import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { ConsensusQueuePage } from './ConsensusQueuePage'
import { apiError, batch, candidate, classes, json, manager, stubApi, type Route as ApiRoute } from './consensus-fixtures'
import type { ResolutionQueueItem } from './consensus-types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function row(overrides: Partial<ResolutionQueueItem> = {}): ResolutionQueueItem {
  return {
    work_item_id: 'w1', batch_item_id: 'item-1', media_id: 'media-1', relative_path: 'frames/a.png', scope: 'candidate',
    candidate_key: 'c-0123456789abcdef', status: 'review_required', reason: 'geometry_below_threshold', submissions: 2,
    reviews_submitted: 1, reviews_required: 2, resolver: 'two_stage_detection_consensus', resolver_version: '1.0.0',
    class_strategy: 'categorical_vote', metrics: candidate().metrics, lease_holder_id: 'olga',
    lease_expires_at: '2026-10-14T10:20:00Z', created_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
    ...overrides,
  }
}

const common: ApiRoute = ({ path }) => {
  if (path === '/api/v1/projects/p1') return json({ id: 'p1', name: 'Birds', task_type: 'detection' })
  if (path === '/api/v1/projects/p1/classes') return json({ items: classes, next_cursor: null })
  if (path === '/api/v1/projects/p1/members') return json({ items: [{ user_id: 'olga', username: 'olga', display_name: 'Olga', role: 'manager' }], next_cursor: null })
  if (path === '/api/v1/capabilities') return json({ consensus_pipelines: { detection: { class_strategies: [{ id: 'categorical_vote' }, { id: 'dirichlet_vote' }] } } })
  if (path === '/api/v1/projects/p1/batches') return json({ items: [batch({ id: 'quiet', review_required_items: 0 }), batch({ id: 'busy' })], next_cursor: null })
  return undefined
}

function renderPage(route: ApiRoute) {
  const fetch = stubApi((request) => common(request) ?? route(request))
  const context: AuthContextValue = { user: manager, token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn() }
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/projects/p1/consensus']}>
        <Routes><Route path="/projects/:projectId/consensus" element={<ConsensusQueuePage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

function queueRequests(fetch: ReturnType<typeof stubApi>) {
  return fetch.mock.calls
    .map(([url]) => new URL(String(url)))
    .filter((url) => url.pathname.endsWith('/resolutions'))
}

describe('ConsensusQueuePage', () => {
  it('opens the batch with cases waiting and shows aggregate rows without evidence', async () => {
    const fetch = renderPage(({ path }) => path === '/api/v1/projects/p1/batches/busy/resolutions' ? json({ items: [row()], next_cursor: null }) : undefined)

    const item = await screen.findByRole('listitem')
    expect(queueRequests(fetch)[0]!.searchParams.getAll('state')).toEqual(['review_required'])
    expect(within(item).getByText('Geometry agreement below the threshold')).toBeInTheDocument()
    expect(within(item).getByText('2 submissions · 1 of 2 reviews')).toBeInTheDocument()
    expect(within(item).getByText('Decision Cat · support 2/2 (100%) · median IoU 0.410')).toBeInTheDocument()
    expect(within(item).getByText('two_stage_detection_consensus v1.0.0 · categorical_vote')).toBeInTheDocument()
    expect(within(item).getByText('3 h')).toBeInTheDocument()
    expect(within(item).getByText(/Being edited by Olga/)).toBeInTheDocument()
    expect(within(item).getByRole('link', { name: /Open image evidence/ })).toHaveAttribute('href', '/projects/p1/consensus/images/item-1')
    expect(within(item).getByRole('link', { name: /Decide this case/ })).toHaveAttribute('href', '/projects/p1/consensus/work-items/w1?item=item-1')
    expect(fetch.mock.calls.some(([url]) => String(url).includes('/evidence'))).toBe(false)
  })

  it('sends every filter to the server', async () => {
    const fetch = renderPage(({ path }) => path.endsWith('/resolutions') ? json({ items: [], next_cursor: null }) : undefined)
    await screen.findByText('No cases match these filters.')

    fireEvent.click(screen.getByRole('checkbox', { name: 'Waiting for reviewers' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Reason' }), { target: { value: 'class_tie' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Class strategy' }), { target: { value: 'dirichlet_vote' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Age' }), { target: { value: '2' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Batch' }), { target: { value: 'quiet' } })

    await waitFor(() => expect(queueRequests(fetch).at(-1)!.pathname).toBe('/api/v1/projects/p1/batches/quiet/resolutions'))
    const last = queueRequests(fetch).at(-1)!
    expect(last.searchParams.getAll('state')).toEqual(['review_required', 'pending_review'])
    expect(last.searchParams.get('reason')).toBe('class_tie')
    expect(last.searchParams.get('class_strategy')).toBe('dirichlet_vote')
    expect(last.searchParams.get('min_age_seconds')).toBe('86400')
  })

  it('never leaves the state filter empty', async () => {
    renderPage(({ path }) => path.endsWith('/resolutions') ? json({ items: [], next_cursor: null }) : undefined)
    await screen.findByText('No cases match these filters.')

    expect(screen.getByRole('checkbox', { name: 'Needs a decision' })).toBeDisabled()
  })

  it('loads the next page with the server cursor', async () => {
    const fetch = renderPage(({ path, search }) => {
      if (!path.endsWith('/resolutions')) return undefined
      return search.get('cursor') === 'next'
        ? json({ items: [row({ work_item_id: 'w2', relative_path: 'frames/b.png' })], next_cursor: null })
        : json({ items: [row()], next_cursor: 'next' })
    })
    await screen.findByText('frames/a.png')

    fireEvent.click(screen.getByRole('button', { name: 'Load more cases' }))

    await screen.findByText('frames/b.png')
    expect(screen.getByText('frames/a.png')).toBeInTheDocument()
    expect(queueRequests(fetch).at(-1)!.searchParams.get('cursor')).toBe('next')
    expect(screen.queryByRole('button', { name: 'Load more cases' })).not.toBeInTheDocument()
  })

  it('shows a neutral message to members who are not owners or managers', async () => {
    stubApi(({ path }) => {
      if (path === '/api/v1/projects/p1/batches') return apiError(403, 'forbidden')
      return common({ path, method: 'GET', search: new URLSearchParams(), body: undefined })
    })
    const context: AuthContextValue = { user: manager, token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn() }
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthContext.Provider value={context}>
        <MemoryRouter initialEntries={['/projects/p1/consensus']}>
          <Routes><Route path="/projects/:projectId/consensus" element={<ConsensusQueuePage />} /></Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>)

    expect(await screen.findByText('The consensus review queue is available to project owners and managers.')).toBeInTheDocument()
  })
})
