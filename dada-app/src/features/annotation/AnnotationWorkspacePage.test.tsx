import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { apiError, box, classes, json, manager, stubApi, stubResizeObserver, type Route as ApiRoute } from '../consensus/consensus-fixtures'
import { AnnotationWorkspacePage } from './AnnotationWorkspacePage'
import type { AnnotationObject, AssignmentDetail, AssignmentTarget } from './types'

beforeEach(() => {
  sessionStorage.clear()
  stubResizeObserver()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const target: AssignmentTarget = {
  geometry: { type: 'rectangle', coordinates: [160, 120, 320, 240] },
  region: [112, 84, 416, 312],
}

function detail(objects: AnnotationObject[]): AssignmentDetail {
  return {
    id: 'a1', project_id: 'p1', batch_id: 'b1', batch_purpose: 'acquisition', task_type: 'detection',
    status: 'in_progress', version: 3,
    media: { id: 'm1', relative_path: 'belt/frame-0001.png', width: 640, height: 480, image_url: '/api/v1/media/m1/content?expires=1&signature=s' },
    objects, seeded_from_import: false, draft_saved_at: null, revision: null, submitted_at: null, resolution: null, target,
  }
}

function renderWorkspace(objects: AnnotationObject[], assist: ApiRoute) {
  const fetch = stubApi((request) => {
    const { path, method } = request
    if (path === '/api/v1/projects/p1') return json({ id: 'p1', name: 'Belt', task_type: 'detection' })
    if (path === '/api/v1/projects/p1/classes') return json({ items: classes, next_cursor: null })
    if (path === '/api/v1/projects/p1/assignments') {
      return json({ items: [{ ...detail(objects), media_id: 'm1', relative_path: 'belt/frame-0001.png', width: 640, height: 480, updated_at: '2026-11-25T10:00:00Z' }], next_cursor: null, counts: { pending: 0, in_progress: 1, submitted: 0 } })
    }
    if (path === '/api/v1/projects/p1/assignments/a1' && method === 'GET') return json(detail(objects))
    if (path === '/api/v1/projects/p1/events/ticket') return apiError(404, 'not_found')
    if (path === '/api/v1/inference/sam-predict') return assist(request)
    return undefined
  })
  const context: AuthContextValue = { user: manager, token: 'token', isLoading: false, sessionExpired: false, login: vi.fn(), logout: vi.fn() }
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={context}>
      <MemoryRouter initialEntries={['/projects/p1/annotate']}>
        <Routes><Route path="/projects/:projectId/annotate" element={<AnnotationWorkspacePage />} /></Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
  return fetch
}

async function openTarget() {
  fireEvent.click(await screen.findByRole('button', { name: /frame-0001\.png/ }))
  await screen.findByText(/asks about the highlighted object only/)
}

function objectList() {
  return within(screen.getByRole('complementary', { name: 'Classes' })).queryAllByRole('button', { name: /^\d+\./ })
}

describe('object targets and assisted segmentation (D16, A7-03)', () => {
  it('outlines the target and its region without adding them to the document', async () => {
    renderWorkspace([], () => undefined)
    await openTarget()

    expect(document.querySelector('.target-region')).toHaveAttribute('width', '416')
    expect(document.querySelector('.target-cue')).toHaveAttribute('x', '160')
    expect(objectList()).toHaveLength(0)
  })

  it('previews a suggestion for the target and adds it only when accepted', async () => {
    const fetch = renderWorkspace([], ({ body }) => json({
      request_id: (body as { request_id: string }).request_id, assignment_id: 'a1', status: 'suggestion',
      geometry: { type: 'rectangle', coordinates: [170, 130, 300, 220] }, score: 0.91, model: {},
    }))
    await openTarget()

    fireEvent.click(screen.getByRole('button', { name: 'Assist segmentation' }))
    expect(await screen.findByText(/Suggestion · confidence 0.91/)).toBeInTheDocument()
    const [, request] = fetch.mock.calls.find(([url]) => String(url).endsWith('/sam-predict'))!
    expect(JSON.parse(String((request as RequestInit).body))).toMatchObject({
      project_id: 'p1', assignment_id: 'a1', prompts: [{ type: 'box', coordinates: [160, 120, 320, 240] }],
    })
    expect(objectList()).toHaveLength(0)
    expect(document.querySelector('.assist-suggestion')).toHaveAttribute('width', '300')

    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))

    expect(objectList()).toHaveLength(1)
    expect(document.querySelector('.assist-suggestion')).toBeNull()
    expect(fetch.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')).toBe(false)
  })

  it('leaves the draft unchanged when the model times out or is unavailable', async () => {
    let answer = apiError(503, 'assistance_timeout')
    renderWorkspace([box('kept', 'cat', [10, 10, 40, 40])], () => answer)
    await openTarget()

    fireEvent.click(screen.getByRole('button', { name: 'Assist segmentation' }))
    expect(await screen.findByText('The model did not answer in time. Your draft is unchanged.')).toBeInTheDocument()
    expect(objectList()).toHaveLength(1)

    answer = json({ error: { code: 'assistance_unavailable', message: 'x', details: { reason: 'no_target_model' }, trace_id: 't' } }, 409)
    fireEvent.click(screen.getByRole('button', { name: 'Assist segmentation' }))
    expect(await screen.findByText('Assistance is not available yet: this project has no trained target model.')).toBeInTheDocument()
    expect(objectList()).toHaveLength(1)
  })

  it('keeps a target document to one object', async () => {
    renderWorkspace([box('kept', 'cat', [10, 10, 40, 40])], ({ body }) => json({
      request_id: (body as { request_id: string }).request_id, assignment_id: 'a1', status: 'suggestion',
      geometry: { type: 'rectangle', coordinates: [170, 130, 300, 220] }, score: null, model: {},
    }))
    await openTarget()

    fireEvent.click(screen.getByRole('button', { name: 'Assist segmentation' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }))

    expect(screen.getByText(/Delete the current one first/)).toBeInTheDocument()
    await waitFor(() => expect(objectList()).toHaveLength(1))
  })
})
