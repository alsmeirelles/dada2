import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { apiError, json, manager, stubApi, type Route as ApiRoute } from '../consensus/consensus-fixtures'
import { learningCatalog } from '../projects/learning-catalog.fixture'
import type { Iteration, QualityReport } from './types'
import { ProjectActivityPage } from './ProjectActivityPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const project = {
  id: 'p1', name: 'Birds', task_type: 'detection', status: 'active', dataset_layout: 'split',
  acquisition_strategy: 'active_learning', learning_solution: 'deterministic', completion_reason: null,
}

function iteration(overrides: Partial<Iteration> = {}): Iteration {
  return {
    id: 'run-1', number: 1, purpose: 'selection', status: 'annotating', stage: null, strategy: 'active_learning',
    attempt: 1, solution: 'deterministic', solution_version: '1.0.0', batch_id: 'batch-1', requested_size: 2,
    selected_count: 2, shortfall_reason: null, stop_reason: null, failure_code: null, failure_detail: null,
    total_count: 2, resolved_count: 1, review_required_count: 0, available_count: 1, total_assignment_count: 2,
    submitted_assignment_count: 1, eta_seconds: null, metrics: {}, evaluations: [],
    started_at: '2026-11-25T10:00:00Z', completed_at: null,
    ...overrides,
  }
}

function quality(overrides: Partial<QualityReport> = {}): QualityReport {
  return {
    task_type: 'detection', total_items: 40, resolved_items: 32, minimum_decisions: 30, minimum_cell: 5,
    suppressed: false, review_rate: 0.125, resolution_rate: 0.8,
    agreement: [{ metric: 'box_iou', observations: 3, median: null }],
    ...overrides,
  }
}

function renderActivity(current: Iteration | null, role: string, route: ApiRoute = () => undefined) {
  const fetch = stubApi((request) => route(request) ?? (({ path, method }) => {
    if (path === '/api/v1/projects/p1') return json(project)
    if (path === '/api/v1/projects/p1/iterations') return json({ items: current ? [current] : [], current_iteration: current, next_cursor: null })
    if (path === '/api/v1/projects/p1/statistics') {
      return json({
        project_id: 'p1', acquisition_strategy: 'active_learning', max_acquisition_iterations: 5, completed_iterations: 0,
        completion_reason: null, evaluation_metric: 'map50', metric_target: null,
        evaluations: [{ iteration: 1, split: 'validation', metric: 'map50', value: 0.42, metrics: { map50: 0.42 }, model: {}, created_at: '2026-11-25T11:00:00Z' }],
      })
    }
    if (path === '/api/v1/projects/p1/members') return json({ items: [{ user_id: manager.id, username: manager.username, display_name: manager.display_name, role }], next_cursor: null })
    if (path === '/api/v1/capabilities') return json(learningCatalog)
    if (path === '/api/v1/projects/p1/quality') return json(quality())
    if (path === '/api/v1/projects/p1/events/ticket' && method === 'POST') return apiError(404, 'not_found')
    return undefined
  })(request))
  const context: AuthContextValue = { user: manager, token: 'token', isLoading: false, sessionExpired: false, login: vi.fn(), logout: vi.fn() }
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/projects/p1/activity']}>
        <Routes><Route path="/projects/:projectId/activity" element={<ProjectActivityPage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

describe('the activity card (A7-01)', () => {
  it('names the stage the worker reports and whether images or objects are chosen', async () => {
    renderActivity(iteration({ status: 'training', stage: 'selecting', batch_id: null }), 'manager')

    expect(await screen.findByRole('heading', { name: 'Selecting objects' })).toBeInTheDocument()
    expect(screen.queryByText(/Estimated time/)).not.toBeInTheDocument()
  })

  it('says a random iteration is selecting randomly', async () => {
    renderActivity(iteration({ status: 'training', strategy: 'random', batch_id: null }), 'manager')

    expect(await screen.findByRole('heading', { name: 'Selecting randomly' })).toBeInTheDocument()
  })

  it('shows the API reason of a failure and lets a manager retry it', async () => {
    const fetch = renderActivity(
      iteration({ status: 'failed', batch_id: null, failure_code: 'worker_failed', failure_detail: 'No result within the timeout.' }),
      'manager',
      ({ path, method }) => path === '/api/v1/projects/p1/iterations/run-1/retry' && method === 'POST' ? json(iteration({ status: 'training', attempt: 2 }), 202) : undefined,
    )

    expect(await screen.findByRole('heading', { name: 'Iteration failed' })).toBeInTheDocument()
    expect(screen.getByText('No result within the timeout.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Retry iteration/ }))

    await waitFor(() => expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith('/iterations/run-1/retry') && (init as RequestInit).method === 'POST')).toBe(true))
  })

  it('gives an annotator the reason but neither the retry, the quality, nor the export', async () => {
    renderActivity(iteration({ status: 'failed', batch_id: null, failure_code: 'validation_unavailable' }), 'annotator')

    expect(await screen.findByText('validation_unavailable')).toBeInTheDocument()
    expect(screen.getByText('An owner or manager can retry this iteration.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Retry iteration/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Quality' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Dataset export' })).not.toBeInTheDocument()
  })
})

describe('quality and export for managers (A7-02, D19)', () => {
  it('shows the measures as a table and hidden values as Not enough data', async () => {
    renderActivity(iteration(), 'owner')

    const table = await screen.findByRole('table', { name: 'Annotation quality' })
    const rows = within(table).getAllByRole('row').map((row) => row.textContent)
    expect(rows[1]).toContain('Review rate12.5%')
    expect(rows[2]).toContain('Resolution rate80.0%')
    expect(rows[3]).toContain('AgreementNot enough dataMedian pairwise box IoU, over 3 first-round candidates')
    expect(screen.queryByText(/Mia/)).not.toBeInTheDocument()
  })

  it('downloads the dataset in the chosen format', async () => {
    const save = vi.fn(() => 'blob:dataset')
    Object.assign(URL, { createObjectURL: save, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const fetch = renderActivity(iteration(), 'manager', ({ path }) => path === '/api/v1/projects/p1/export'
      ? new Response('zip', { status: 200, headers: { 'Content-Type': 'application/zip', 'Content-Disposition': 'attachment; filename="Birds-yolo.zip"' } })
      : undefined)

    fireEvent.change(await screen.findByRole('combobox', { name: 'Format' }), { target: { value: 'yolo' } })
    fireEvent.click(screen.getByRole('button', { name: /Download dataset/ }))

    await waitFor(() => expect(click).toHaveBeenCalled())
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe('Birds-yolo.zip')
    click.mockRestore()
    expect(fetch.mock.calls.map(([url]) => String(url)).filter((url) => url.includes('/export'))).toEqual([
      'http://localhost:8000/api/v1/projects/p1/export?format=yolo',
    ])
  })
})
