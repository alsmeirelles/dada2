import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { CandidateReviewPage } from './CandidateReviewPage'
import type { ReviewAssignmentDetail } from './review-types'

const project = {
  id: 'project-1', name: 'Road defects', description: null, task_type: 'detection', status: 'active', owner_id: 'owner',
  acquisition_strategy: 'random', dataset_layout: 'split', initial_training_size: null, test_set_size: 1,
  test_set_percentage: null, validation_set_size: 1, validation_set_percentage: null, iteration_batch_size: 2,
  dataset_prepared_at: null, version: 1, created_at: '2026-10-15T12:00:00Z', updated_at: '2026-10-15T12:00:00Z',
}
const classes = { items: [{ id: 'class-1', name: 'Pothole', color: '#E5484D', version: 1, display_order: 0 }], next_cursor: null }

function review(overrides: Partial<ReviewAssignmentDetail> = {}): ReviewAssignmentDetail {
  return {
    id: 'review-1', project_id: 'project-1', work_item_id: 'work-1', source_input_id: 'input-1',
    candidate_key: 'c-1', candidate_ordinal: 0, scope: 'candidate', status: 'pending', version: 1,
    media: { id: 'media-1', relative_path: 'road/0001.jpg', width: 200, height: 100, image_url: '/api/v1/media/media-1/content' },
    candidate_context: { region: [20, 10, 60, 40] }, evidence: {}, draft_saved_at: null, submitted_at: null,
    ...overrides,
  }
}

type Reply = { status: number; body?: unknown }

function json({ status, body }: Reply) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage(details: ReviewAssignmentDetail[], writes: Reply[] = [], taskType = 'detection') {
  const reads = [...details]
  const fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === 'PUT' || init?.method === 'POST') return Promise.resolve(json(writes.shift() ?? { status: 200, body: {} }))
    if (url.endsWith('/review-assignments/review-1')) return Promise.resolve(json({ status: 200, body: reads.length > 1 ? reads.shift() : reads[0] }))
    if (url.endsWith('/classes')) return Promise.resolve(json({ status: 200, body: classes }))
    if (url.endsWith('/projects/project-1')) return Promise.resolve(json({ status: 200, body: { ...project, task_type: taskType } }))
    return Promise.resolve(json({ status: 200, body: { items: [], next_cursor: null, counts: { pending: 0, in_progress: 0, submitted: 0 } } }))
  })
  vi.stubGlobal('fetch', fetch)
  const context: AuthContextValue = {
    user: { id: 'reviewer', username: 'rev', display_name: 'Reviewer', is_administrator: false, is_active: true, version: 1, created_at: '2026-10-15T12:00:00Z' },
    token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn(),
  }
  const view = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/projects/project-1/reviews/review-1']}>
        <Routes><Route path="/projects/:projectId/reviews/:reviewAssignmentId" element={<CandidateReviewPage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return { fetch, view }
}

function writeBody(fetch: ReturnType<typeof vi.fn>, method: string) {
  const call = fetch.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === method)
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined
}

beforeEach(() => {
  sessionStorage.clear()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('CandidateReviewPage', () => {
  it('shows only the image and the region, and records that the region holds no object', async () => {
    const { fetch, view } = renderPage([review(), review({ status: 'submitted', version: 2, evidence: { decision: 'no_object' } })], [{ status: 200, body: { id: 'review-1', status: 'submitted', version: 2 } }])

    fireEvent.click(await screen.findByLabelText('No object'))
    fireEvent.click(screen.getByRole('button', { name: /Submit review/ }))

    await waitFor(() => expect(writeBody(fetch, 'POST')).toEqual({ version: 1, evidence: { decision: 'no_object' } }))
    expect(await screen.findByText('Review submitted. It is read-only.')).toBeInTheDocument()
    expect(view.container.querySelector('rect.review-region')).toHaveAttribute('width', '60')
    expect(fetch.mock.calls.map(([url]) => String(url)).every((url) => !/evidence|resolutions|batches|members/.test(url))).toBe(true)
    expect(screen.queryByText(/candidate_context|votes|submissions/i)).not.toBeInTheDocument()
  })

  it('submits an object drawn earlier with its class and geometry', async () => {
    const geometry = { type: 'rectangle' as const, coordinates: [25, 15, 20, 10] as [number, number, number, number] }
    const { fetch } = renderPage([review({ status: 'in_progress', version: 4, evidence: { decision: 'object', class_id: 'class-1', geometry } })])

    fireEvent.click(await screen.findByRole('button', { name: /Submit review/ }))

    await waitFor(() => expect(writeBody(fetch, 'POST')).toEqual({ version: 4, evidence: { decision: 'object', class_id: 'class-1', geometry } }))
  })

  it('collects the classes of an image-level case', async () => {
    const { fetch } = renderPage([review({ scope: 'image', candidate_context: {} })], [], 'classification')

    fireEvent.click(await screen.findByRole('checkbox', { name: 'Pothole' }))
    fireEvent.click(screen.getByRole('button', { name: /Submit review/ }))

    await waitFor(() => expect(writeBody(fetch, 'POST')).toEqual({ version: 1, evidence: { class_ids: ['class-1'] } }))
  })

  it('keeps the local draft on a stale version and lets the reviewer keep it', async () => {
    const { fetch } = renderPage(
      [review(), review({ status: 'in_progress', version: 3, evidence: { decision: 'object' } })],
      [{ status: 409, body: { error: { code: 'version_conflict', message: 'The review changed since it was read.' } } }],
    )

    fireEvent.click(await screen.findByLabelText('No object'))
    expect(sessionStorage.getItem('dada.review-recovery:project-1:review-1:1')).toContain('no_object')
    fireEvent.click(screen.getByRole('button', { name: /Save draft/ }))

    expect(await screen.findByText(/changed on the server after your unsaved work/)).toBeInTheDocument()
    expect(writeBody(fetch, 'PUT')).toEqual({ version: 1, evidence: { decision: 'no_object' } })
    expect(screen.getByLabelText('No object')).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Keep my version' }))

    expect(screen.getByLabelText('No object')).toBeChecked()
    expect(sessionStorage.getItem('dada.review-recovery:project-1:review-1:3')).toContain('no_object')
    expect(sessionStorage.getItem('dada.review-recovery:project-1:review-1:1')).toBeNull()
  })

  it('shows the API reason when evidence is refused', async () => {
    renderPage([review({ status: 'in_progress', version: 2, evidence: { decision: 'no_object' } })], [{ status: 422, body: { error: { code: 'invalid_review_evidence', message: 'The review evidence does not fit this case.' } } }])

    fireEvent.click(await screen.findByRole('button', { name: /Submit review/ }))

    expect(await screen.findByText('The review evidence does not fit this case.')).toBeInTheDocument()
  })
})
