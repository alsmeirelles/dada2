import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { ProjectSettingsPage } from './ProjectSettingsPage'
import { consensusPipelines } from './resolver-catalog.fixture'

const project = {
  id: 'project-1', name: 'Road defects', description: null, task_type: 'detection', status: 'active', owner_id: 'owner',
  acquisition_strategy: 'random', dataset_layout: 'split', initial_training_size: null, test_set_size: 1,
  test_set_percentage: null, validation_set_size: 1, validation_set_percentage: null, iteration_batch_size: 2,
  dataset_prepared_at: null, version: 1, created_at: '2026-10-15T12:00:00Z', updated_at: '2026-10-15T12:00:00Z',
}
const members = { items: [
  { user_id: 'owner', username: 'owner', display_name: 'Owner', role: 'owner' },
  { user_id: 'ana', username: 'ana', display_name: 'Ana', role: 'annotator' },
  { user_id: 'bruno', username: 'bruno', display_name: 'Bruno', role: 'annotator' },
], next_cursor: null }
const parameters = { class_strategy: { strategy: 'dirichlet_vote', alpha: 0.5, minimum_posterior: 0.95 }, matching_iou: 0.5, box_refinement: { strategy: 'coordinate_median' } }
const thresholds = { minimum_support: { numerator: 3, denominator: 4 }, minimum_median_iou: 0.5 }
const policy = {
  mode: 'consensus', version: 4, annotator_ids: ['owner', 'ana', 'bruno'], required_consensus_annotations: 2,
  required_consensus_reviewers: 1, resolver: 'two_stage_detection_consensus', resolver_version: '1.0.0',
  parameters, review_thresholds: thresholds, require_independent_adjudicator: false,
}

function payload(url: string) {
  if (url.endsWith('/annotation-policy/history')) {
    return { items: [{ version: 4, actor_id: 'owner', actor_name: 'Owner', changed_at: '2026-10-15T12:00:00Z', resolver: 'two_stage_detection_consensus', resolver_version: '1.0.0', changed_fields: { review_thresholds: { before: { minimum_support: { numerator: 2, denominator: 3 }, minimum_median_iou: 0.5 }, after: thresholds } } }], preparing_batches: 2 }
  }
  if (url.endsWith('/annotation-policy')) return policy
  if (url.endsWith('/resolver-eligibility')) {
    return { strategies: [
      { strategy: 'reliability_weighted_vote', eligible: true, missing: [], report: {} },
      { strategy: 'dawid_skene', eligible: false, missing: [{ requirement: 'calibration_items', required: 50, found: 12 }], report: {} },
    ] }
  }
  if (url.endsWith('/members')) return members
  if (url.endsWith('/capabilities')) return { consensus_pipelines: consensusPipelines }
  return project
}

function renderSettings() {
  const fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => Promise.resolve(new Response(
    JSON.stringify(init?.method === 'PUT' ? { ...policy, version: 5 } : payload(url)),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )))
  vi.stubGlobal('fetch', fetch)
  const context: AuthContextValue = {
    user: { id: 'owner', username: 'owner', display_name: 'Owner', is_administrator: false, is_active: true, version: 1, created_at: '2026-10-15T12:00:00Z' },
    token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn(),
  }
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/projects/project-1/settings']}>
        <Routes><Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('default policy settings', () => {
  it('shows the stored configuration, the eligibility, the history, and which batches a change reaches', async () => {
    renderSettings()

    expect(await screen.findByRole('radio', { name: /Dirichlet vote/ })).toBeChecked()
    expect(screen.getByLabelText('Minimum posterior')).toHaveValue(0.95)
    expect(await screen.findByText('Available after this project has 50 resolved images annotated by at least three selected annotators.')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Reliability weighted vote/ })).toBeEnabled()
    expect(screen.getByRole('radio', { name: /Dawid skene/ })).toBeDisabled()
    expect(await screen.findByText(/2 batches are still preparing and keep their current snapshots/)).toBeInTheDocument()
    expect(screen.getByText('Version 4')).toBeInTheDocument()
    expect(screen.getByText(/Minimum support: 2\/3, Minimum median IoU: 0.5 → Minimum support: 3\/4, Minimum median IoU: 0.5/)).toBeInTheDocument()
  })

  it('saves the typed configuration and the independence flag with the read version', async () => {
    const fetch = renderSettings()

    fireEvent.click(await screen.findByLabelText(/Require an independent adjudicator/))
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))

    await waitFor(() => expect(fetch.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')).toBe(true))
    const [, request] = fetch.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')!
    expect(JSON.parse(String((request as RequestInit).body))).toEqual({
      mode: 'consensus',
      annotator_ids: ['owner', 'ana', 'bruno'],
      required_consensus_annotations: 2,
      required_consensus_reviewers: 1,
      resolver: 'two_stage_detection_consensus',
      parameters,
      review_thresholds: thresholds,
      require_independent_adjudicator: true,
      version: 4,
    })
  })
})
