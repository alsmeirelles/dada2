import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { startDraft } from './adjudication'
import { saveAdjudicationRecovery } from './adjudication-recovery'
import {
  apiError,
  classes,
  evidence,
  json,
  lease,
  manager,
  run,
  stubApi,
  stubResizeObserver,
  workItem,
} from './consensus-fixtures'
import type { ImageEvidence } from './consensus-types'
import { WorkItemPage } from './WorkItemPage'

type Answer = (body: unknown) => Response

let current: ImageEvidence
let answerAdjudication: Answer

beforeEach(() => {
  sessionStorage.clear()
  stubResizeObserver()
  current = evidence()
  answerAdjudication = () => json({ adjudication: { id: 'adj-1' }, resolution: null })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderPage(url = '/projects/p1/consensus/work-items/w1?item=item-1') {
  const fetch = stubApi(({ method, path, body }) => {
    if (path === '/api/v1/projects/p1') return json({ id: 'p1', name: 'Birds', task_type: current.task_type })
    if (path === '/api/v1/projects/p1/classes') return json({ items: classes, next_cursor: null })
    if (path === '/api/v1/projects/p1/members') return json({ items: [{ user_id: 'olga', username: 'olga', display_name: 'Olga', role: 'manager' }], next_cursor: null })
    if (path === '/api/v1/projects/p1/batch-items/item-1/evidence') return json(current)
    if (path === '/api/v1/projects/p1/resolution-work-items/w1/lease') return method === 'POST' ? json(lease()) : new Response(null, { status: 204 })
    if (path === '/api/v1/projects/p1/resolution-work-items/w1/lease/revoke') return new Response(null, { status: 204 })
    if (path === '/api/v1/projects/p1/resolution-work-items/w1/adjudicate') return answerAdjudication(body)
    return undefined
  })
  const context: AuthContextValue = { user: manager, token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn() }
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path="/projects/:projectId/consensus/work-items/:workItemId" element={<WorkItemPage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

function adjudications(fetch: ReturnType<typeof stubApi>) {
  return fetch.mock.calls
    .filter(([url]) => String(url).endsWith('/adjudicate'))
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)))
}

async function startEditing(source: RegExp = /The resolution proposal/) {
  fireEvent.click(await screen.findByRole('radio', { name: source }))
  fireEvent.click(screen.getByRole('button', { name: /Take the lease and start editing/ }))
  await screen.findByText(/You hold the edit lease until/)
}

async function submitWith(rationale: string) {
  fireEvent.click(screen.getByRole('button', { name: /Submit decision/ }))
  const dialog = screen.getByRole('dialog', { name: 'Submit your decision' })
  expect(within(dialog).getByRole('button', { name: 'Submit decision' })).toBeDisabled()
  fireEvent.change(within(dialog).getByRole('textbox', { name: /Rationale/ }), { target: { value: rationale } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Submit decision' }))
}

describe('WorkItemPage', () => {
  it('takes the lease, edits a raw submission, and records the decision with a rationale', async () => {
    answerAdjudication = () => {
      current = evidence({ work_items: [workItem({ status: 'resolved' })] })
      return json({ adjudication: { id: 'adj-1' }, resolution: null })
    }
    const fetch = renderPage()
    await startEditing(/A raw submission/)

    expect(screen.getByRole('heading', { name: 'Editing a raw submission' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1. Cat · Box at 10, 10, 20 × 20 px' })).toBeInTheDocument()
    expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith('/w1/lease') && (init as RequestInit).method === 'POST')).toBe(true)

    await submitWith('Ana drew the tighter box.')

    expect(await screen.findByRole('heading', { name: 'Decision recorded' })).toBeInTheDocument()
    expect(adjudications(fetch)).toEqual([{
      expected_evidence_generation: 1, expected_configuration_fingerprint: 'cfg-1', expected_resolution_version: 0,
      action: 'edit_submission', source_submission_id: 's1', objects: [current.submissions[0]!.objects[0]],
      rationale: 'Ana drew the tighter box.',
    }])
    expect(sessionStorage.length).toBe(0)
  })

  it('keeps the local draft through a version conflict and copies it onto the new version only after confirmation', async () => {
    answerAdjudication = () => {
      current = evidence({
        versions: { evidence_generation: 2, configuration_fingerprint: 'cfg-2', resolution_version: 0 },
        runs: [run(), run({ id: 'run-2', sequence: 2, configuration_fingerprint: 'cfg-2' })],
        work_items: [workItem({ run_id: 'run-2' })],
      })
      return apiError(409, 'version_conflict', 'The evidence or resolution changed since it was read.')
    }
    const fetch = renderPage()
    await startEditing()
    fireEvent.click(screen.getByRole('button', { name: /^1\. Cat/ }))
    fireEvent.click(screen.getByRole('button', { name: /Delete selected/ }))
    expect(Object.keys(sessionStorage)).toEqual(['dada.adjudication-recovery:p1:w1:manager:1.0'])

    await submitWith('Nothing is there.')

    expect(await screen.findByRole('heading', { name: 'The evidence changed since your draft was based on it' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('trace ID trace-version_conflict')
    expect(within(screen.getByRole('region', { name: 'Source' })).getByText('Cat · Box at 10, 10, 21 × 21 px')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Your draft' })).getByText('No objects: nothing exists here.')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'New version' })).getByText(/Evidence generation 2, resolution version 0, new resolver configuration/)).toBeInTheDocument()
    expect(Object.keys(sessionStorage)).toEqual(['dada.adjudication-recovery:p1:w1:manager:1.0'])
    expect(screen.getByRole('button', { name: /Submit decision/ })).toBeDisabled()

    const copy = screen.getByRole('button', { name: 'Copy my draft onto the new version' })
    expect(copy).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: /I compared the new version/ }))
    fireEvent.click(copy)

    expect(screen.queryByRole('heading', { name: /The evidence changed/ })).not.toBeInTheDocument()
    expect(Object.keys(sessionStorage)).toEqual(['dada.adjudication-recovery:p1:w1:manager:2.0'])
    answerAdjudication = () => json({ adjudication: { id: 'adj-1' }, resolution: null })
    await submitWith('Nothing is there.')

    await screen.findByRole('heading', { name: 'Decision recorded' })
    expect(adjudications(fetch).at(-1)).toMatchObject({
      expected_evidence_generation: 2, expected_configuration_fingerprint: 'cfg-2', action: 'edit_proposal', objects: [],
    })
  })

  it('pauses editing and keeps the draft when the lease is lost', async () => {
    answerAdjudication = () => apiError(409, 'lease_required', 'Editing a case requires holding its lease.')
    renderPage()
    await startEditing()

    await submitWith('Tighter box.')

    expect(await screen.findByText(/Your edit lease was lost/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Submit decision/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /^1\. Cat/ })).toBeInTheDocument()
    expect(sessionStorage.length).toBe(1)
    expect(screen.getByRole('button', { name: /Reacquire the lease/ })).toBeInTheDocument()
  })

  it('resumes a draft kept in this tab', async () => {
    saveAdjudicationRecovery('p1', 'w1', 'manager', { ...startDraft(current, current.work_items[0]!, { kind: 'blank' }), objects: [] })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Resume the draft' }))

    expect(await screen.findByRole('heading', { name: 'Writing a replacement' })).toBeInTheDocument()
    await screen.findByText(/You hold the edit lease until/)
    expect(screen.getByText('No objects: the decision is that nothing exists here.')).toBeInTheDocument()
  })

  it('asks a contributor for a rationale even to accept the proposal', async () => {
    current = evidence({ contributors: ['ana', 'manager'] })
    const fetch = renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Accept proposal/ }))
    const dialog = screen.getByRole('dialog', { name: 'Accept the proposal' })
    expect(within(dialog).getByText(/recorded as a conflict/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Accept proposal' })).toBeDisabled()
    fireEvent.change(within(dialog).getByRole('textbox', { name: /Rationale/ }), { target: { value: 'Checked against the image.' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Accept proposal' }))

    await waitFor(() => expect(adjudications(fetch)).toEqual([{
      expected_evidence_generation: 1, expected_configuration_fingerprint: 'cfg-1', expected_resolution_version: 0,
      action: 'accept_proposal', rationale: 'Checked against the image.',
    }]))
  })

  it('lets a plain acceptance go without a note', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Accept proposal/ }))

    const dialog = screen.getByRole('dialog', { name: 'Accept the proposal' })
    expect(within(dialog).getByRole('textbox', { name: 'Note (optional)' })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Accept proposal' })).toBeEnabled()
  })

  it('refuses a contributor when the batch requires an independent adjudicator', async () => {
    current = evidence({ contributors: ['manager'], require_independent_adjudicator: true })
    renderPage()

    expect(await screen.findByText(/requires an independent adjudicator/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Accept proposal/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /start editing/ })).not.toBeInTheDocument()
  })

  it('blocks decisions while someone else holds the lease and revokes it with a reason', async () => {
    current = evidence({ work_items: [workItem({ lease: lease({ holder_id: 'olga' }) })] })
    const fetch = renderPage()

    expect(await screen.findByText(/Olga holds the edit lease/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Accept proposal/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /start editing/ })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Revoke the lease' }))
    const dialog = screen.getByRole('dialog', { name: 'Revoke the edit lease' })
    expect(within(dialog).getByText(/Their unsaved draft stays in their browser/)).toBeInTheDocument()
    fireEvent.change(within(dialog).getByRole('textbox', { name: /Reason/ }), { target: { value: 'Abandoned overnight.' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Revoke lease' }))

    await waitFor(() => {
      const call = fetch.mock.calls.find(([url]) => String(url).endsWith('/lease/revoke'))
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ reason: 'Abandoned overnight.' })
    })
  })

  it('explains a link without its image', async () => {
    renderPage('/projects/p1/consensus/work-items/w1')

    expect(await screen.findByText(/does not say which image the case belongs to/)).toBeInTheDocument()
  })
})
