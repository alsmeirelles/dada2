import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { ProjectBatchesPage } from './ProjectBatchesPage'
import { consensusPipelines } from './resolver-catalog.fixture'
import { defaultConfiguration } from './resolver-config'
import type { AnnotationBatch } from './types'

const project = {
  id: 'project-1', name: 'Road defects', description: null, task_type: 'detection', status: 'active', owner_id: 'owner',
  acquisition_strategy: 'random', dataset_layout: 'split', initial_training_size: null, test_set_size: 1,
  test_set_percentage: null, validation_set_size: 1, validation_set_percentage: null, iteration_batch_size: 2,
  dataset_prepared_at: null, version: 1, created_at: '2026-10-15T12:00:00Z', updated_at: '2026-10-15T12:00:00Z',
}
const configuration = defaultConfiguration('detection', consensusPipelines.detection)

function batch(overrides: Partial<AnnotationBatch>): AnnotationBatch {
  return {
    id: 'batch-1', project_id: 'project-1', purpose: 'test', status: 'resolving', mode: 'consensus', annotator_ids: ['owner'],
    required_consensus_annotations: 2, required_consensus_reviewers: 1, resolver: 'two_stage_detection_consensus',
    resolver_version: '1.0.0', ...configuration, require_independent_adjudicator: false, source_policy_version: 1,
    selection_strategy: 'random', selection_seed: 1, selection_input_fingerprint: 'f', requested_size: 10,
    total_items: 10, resolved_items: 3, awaiting_resolution_items: 1, resolving_items: 2, in_review_items: 1,
    review_required_items: 2, cancelled_items: 1, total_assignments: 20, available_assignments: 0,
    in_progress_assignments: 0, submitted_assignments: 20, started_at: '2026-10-15T12:00:00Z',
    created_at: '2026-10-15T12:00:00Z', updated_at: '2026-10-15T12:00:00Z',
    ...overrides,
  }
}

function payload(url: string) {
  if (url.endsWith('/batches')) return { items: [batch({}), batch({ id: 'batch-2', purpose: 'validation', status: 'preparing', total_assignments: 0, submitted_assignments: 0, review_required_items: 0, started_at: null })], next_cursor: null }
  if (url.endsWith('/members')) return { items: [{ user_id: 'owner', username: 'owner', display_name: 'Owner', role: 'owner' }], next_cursor: null }
  if (url.endsWith('/capabilities')) return { consensus_pipelines: consensusPipelines }
  if (url.endsWith('/resolver-eligibility')) return { strategies: [] }
  if (url.endsWith('/dataset-layout')) return { dataset_layout: 'split', prepared_at: null, train_size: 0, validation_size: 0, test_size: 0, first_training_batch_size: null, training_pool_size: 0, batch_ids: [], annotation_import_id: null }
  if (url.endsWith('/annotation-policy')) return { mode: 'single', version: 1, annotator_ids: [] }
  return project
}

function renderBatches() {
  const fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => Promise.resolve(new Response(
    JSON.stringify(init?.method === 'PATCH' ? batch({ id: 'batch-2', status: 'preparing' }) : payload(url)),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )))
  vi.stubGlobal('fetch', fetch)
  const context: AuthContextValue = {
    user: { id: 'owner', username: 'owner', display_name: 'Owner', is_administrator: false, is_active: true, version: 1, created_at: '2026-10-15T12:00:00Z' },
    token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn(),
  }
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/projects/project-1/batches']}>
        <Routes><Route path="/projects/:projectId/batches" element={<ProjectBatchesPage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('batch resolution progress', () => {
  it('shows every resolution count and links to the consensus queue when images need review', async () => {
    renderBatches()

    const progress = await screen.findByLabelText('Image resolution progress')
    expect(progress).toHaveTextContent('3 resolved')
    expect(progress).toHaveTextContent('1 awaiting resolution')
    expect(progress).toHaveTextContent('2 resolving')
    expect(progress).toHaveTextContent('1 in review')
    expect(progress).toHaveTextContent('2 review required')
    expect(progress).toHaveTextContent('1 cancelled')
    expect(screen.getByRole('link', { name: /Review 2 images in the consensus queue/ })).toHaveAttribute('href', '/projects/project-1/consensus')
  })

  it('summarizes a snapshot instead of printing raw settings', async () => {
    renderBatches()

    const details = (await screen.findAllByText('Snapshot and selection details'))[0]!.closest('details')!
    expect(within(details).getByText('Decision rule')).toBeInTheDocument()
    expect(within(details).getAllByText('Supermajority').length).toBeGreaterThan(0)
    expect(details).not.toHaveTextContent('{')
  })

  it('saves a preparing batch\'s typed resolution settings', async () => {
    const fetch = renderBatches()

    fireEvent.change(await screen.findByLabelText('Matching IoU'), { target: { value: '0.6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save batch settings' }))

    await waitFor(() => expect(fetch.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'PATCH')).toBe(true))
    const [url, request] = fetch.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'PATCH')!
    expect(String(url)).toMatch(/\/batches\/batch-2$/)
    expect(JSON.parse(String((request as RequestInit).body))).toEqual({
      mode: 'consensus',
      annotator_ids: ['owner'],
      required_consensus_annotations: 2,
      required_consensus_reviewers: 1,
      resolver: 'two_stage_detection_consensus',
      parameters: { ...configuration.parameters, matching_iou: 0.6 },
      review_thresholds: configuration.review_thresholds,
      require_independent_adjudicator: false,
    })
  })
})
