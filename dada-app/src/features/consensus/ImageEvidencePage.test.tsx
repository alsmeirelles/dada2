import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { consensusPipelines } from '../projects/resolver-catalog.fixture'
import { classes, evidence, json, manager, polygon, run, stubApi, stubResizeObserver } from './consensus-fixtures'
import type { ImageEvidence } from './consensus-types'
import { ImageEvidencePage } from './ImageEvidencePage'

const originalWidth = window.innerWidth

beforeEach(() => stubResizeObserver())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
})

function renderPage(data: ImageEvidence, width = 1400) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  const fetch = stubApi(({ method, path }) => {
    if (path === '/api/v1/projects/p1') return json({ id: 'p1', name: 'Birds', task_type: data.task_type })
    if (path === '/api/v1/projects/p1/classes') return json({ items: classes, next_cursor: null })
    if (path === '/api/v1/projects/p1/members') return json({ items: [], next_cursor: null })
    if (path === '/api/v1/capabilities') return json({ consensus_pipelines: consensusPipelines })
    if (path === '/api/v1/projects/p1/resolver-eligibility') return json({ strategies: [] })
    if (path === '/api/v1/projects/p1/batch-items/item-1/evidence') return json(data)
    if (method === 'POST' && path === '/api/v1/projects/p1/batch-items/item-1/resolve') return json({ ...run({ id: 'run-2', sequence: 2, status: 'queued', proposal: null }) }, 202)
    return undefined
  })
  const context: AuthContextValue = { user: manager, token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn() }
  const view = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/projects/p1/consensus/images/item-1']}>
        <Routes><Route path="/projects/:projectId/consensus/images/:batchItemId" element={<ImageEvidencePage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return { fetch, container: view.container }
}

function shapesOf(container: HTMLElement, sourceId?: string) {
  return container.querySelectorAll(sourceId ? `[data-source="${sourceId}"]` : '[data-source]')
}

describe('ImageEvidencePage', () => {
  it('overlays every visible source and toggles each one, the regions, and all at once', async () => {
    const { container } = renderPage(evidence())
    await screen.findByRole('group', { name: 'Evidence view: 3 sources overlaid' })

    expect(shapesOf(container, 'proposal:proposal-1')).toHaveLength(1)
    expect(shapesOf(container, 'submission:s1')).toHaveLength(2)
    expect(container.querySelectorAll('[data-region]')).toHaveLength(2)

    fireEvent.click(screen.getByRole('checkbox', { name: /^Ana, submission revision 1/ }))
    expect(shapesOf(container, 'submission:s1')).toHaveLength(0)
    expect(screen.getByRole('group', { name: 'Evidence view: 2 sources overlaid' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Hide all sources' }))
    expect(shapesOf(container)).toHaveLength(0)
    expect(container.querySelectorAll('[data-region]')).toHaveLength(0)
    expect(screen.getByRole('checkbox', { name: /^Candidate regions/ })).not.toBeChecked()
  })

  it('switches to side by side, one view per visible source', async () => {
    renderPage(evidence())
    await screen.findByRole('group', { name: 'Evidence view: 3 sources overlaid' })

    fireEvent.click(screen.getByRole('radio', { name: 'Side by side' }))

    expect(screen.getAllByRole('group', { name: /^Evidence view:/ }).map((group) => group.getAttribute('aria-label'))).toEqual([
      'Evidence view: Proposal from run 1',
      'Evidence view: Ana, submission revision 1',
      'Evidence view: Bruno, submission revision 1',
    ])
  })

  it('starts side by side on a narrow screen', async () => {
    renderPage(evidence(), 1000)

    expect(await screen.findByRole('radio', { name: 'Side by side' })).toBeChecked()
    expect(screen.getAllByRole('group', { name: /^Evidence view:/ })).toHaveLength(3)
  })

  it('fills segmentation masks with an adjustable opacity', async () => {
    const mask = polygon('m1', 'cat', [10, 10, 40, 10, 40, 40])
    const { container } = renderPage(evidence({
      task_type: 'segmentation',
      runs: [run({ proposal: { ...run().proposal!, objects: [], candidates: [] } })],
      submissions: [{ ...evidence().submissions[0]!, objects: [mask] }],
    }))
    await screen.findByRole('group', { name: /Evidence view/ })

    expect(shapesOf(container, 'submission:s1')[0]).toHaveAttribute('fill-opacity', '0.35')
    fireEvent.change(screen.getByRole('slider', { name: /Mask opacity/ }), { target: { value: '0.8' } })
    expect(shapesOf(container, 'submission:s1')[0]).toHaveAttribute('fill-opacity', '0.8')
  })

  it('always lists every source, object, candidate decision, and metric as text', async () => {
    renderPage(evidence())
    const table = await screen.findByRole('table', { name: 'Every evidence source and its objects' })

    expect(within(table).getByRole('rowheader', { name: /Ana, submission revision 1/ })).toBeInTheDocument()
    expect(within(table).getByText('Box at 10, 10, 20 × 20 px')).toBeInTheDocument()
    expect(within(table).getAllByText('long dashes')).toHaveLength(1)
    const firstCase = screen.getByRole('article', { name: 'Object 1' })
    expect(within(firstCase).getByText('Geometry agreement below the threshold')).toBeInTheDocument()
    expect(within(firstCase).getByText('Ana · object a1 · Cat')).toBeInTheDocument()
    expect(within(firstCase).getByText('Median pairwise IoU').nextSibling).toHaveTextContent('0.410')
  })

  it('retries only after a confirmed rationale and sends the expected versions', async () => {
    const { fetch } = renderPage(evidence())
    fireEvent.click(await screen.findByRole('button', { name: /Retry resolution/ }))

    const dialog = screen.getByRole('dialog', { name: 'Retry resolution' })
    expect(within(dialog).getByText(/queues a new resolver run/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Queue a new run' })).toBeDisabled()
    fireEvent.change(within(dialog).getByRole('textbox', { name: /Rationale/ }), { target: { value: 'Reviewers finished.' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Queue a new run' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const call = fetch.mock.calls.find(([url]) => String(url).endsWith('/resolve'))!
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
      expected_evidence_generation: 1, expected_configuration_fingerprint: 'cfg-1', expected_resolution_version: 0,
      rationale: 'Reviewers finished.',
    })
    expect(screen.getByText(/Run 2 was queued/)).toBeInTheDocument()
  })

  it('retries with an explicit configuration that starts from the latest run', async () => {
    const { fetch } = renderPage(evidence())
    fireEvent.click(await screen.findByRole('button', { name: /Retry resolution/ }))
    const dialog = screen.getByRole('dialog', { name: 'Retry resolution' })

    const override = within(dialog).getByRole('checkbox', { name: /Use a different configuration/ })
    await waitFor(() => expect(override).toBeEnabled())
    fireEvent.click(override)
    const iou = await within(dialog).findByRole('spinbutton', { name: /Matching IoU/ })
    expect(iou).toHaveValue(0.5)
    expect(within(dialog).queryByRole('checkbox', { name: /independent adjudicator/ })).not.toBeInTheDocument()
    fireEvent.change(iou, { target: { value: '0.6' } })
    fireEvent.change(within(dialog).getByRole('textbox', { name: /Rationale/ }), { target: { value: 'Stricter matching.' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Queue a new run' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const call = fetch.mock.calls.find(([url]) => String(url).endsWith('/resolve'))!
    const body = JSON.parse(String((call[1] as RequestInit).body))
    expect(body.rationale).toBe('Stricter matching.')
    expect(body.configuration.parameters).toMatchObject({
      class_strategy: { strategy: 'categorical_vote', decision_rule: 'supermajority' },
      matching_iou: 0.6,
      box_refinement: { strategy: 'coordinate_median' },
    })
    expect(body.configuration.review_thresholds).toEqual({ minimum_support: { numerator: 2, denominator: 3 }, minimum_median_iou: 0.5 })
  })
})
