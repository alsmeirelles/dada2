import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BatchAssignment } from '../annotation/types'
import { AuthContext, type AuthContextValue } from '../auth/auth-context'
import { BatchAssignmentsPanel } from './BatchAssignmentsPanel'
import type { ProjectMember } from './project-api'
import type { AnnotationBatch, BatchPurpose } from './types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const members: ProjectMember[] = [
  { user_id: 'ana', username: 'ana', display_name: 'Ana', role: 'annotator' },
  { user_id: 'bruno', username: 'bruno', display_name: 'Bruno', role: 'annotator' },
  { user_id: 'viv', username: 'viv', display_name: 'Viv', role: 'viewer' },
]

const submitted: BatchAssignment = {
  id: 'assignment-1', batch_item_id: 'item-1', item_status: 'pending', media_id: 'media-1',
  relative_path: 'frame-1.png', annotator_id: 'ana', status: 'submitted', version: 2,
  updated_at: '2026-09-30T12:00:00Z',
}

function batch(purpose: BatchPurpose): AnnotationBatch {
  return {
    id: 'batch-1', project_id: 'project-1', purpose, status: 'annotating', mode: 'single', annotator_ids: [],
    resolver: null, resolver_version: null, parameters: {}, review_thresholds: {}, source_policy_version: 1,
    selection_strategy: 'random', selection_seed: 1, selection_input_fingerprint: 'f', requested_size: 1,
    total_items: 1, resolved_items: 0, awaiting_resolution_items: 0, cancelled_items: 0, total_assignments: 1,
    available_assignments: 0, in_progress_assignments: 0, submitted_assignments: 1, started_at: null,
    created_at: '2026-09-30T12:00:00Z', updated_at: '2026-09-30T12:00:00Z',
  }
}

async function renderPanel(purpose: BatchPurpose) {
  const fetch = vi.fn().mockImplementation((_url: string, init?: RequestInit) => Promise.resolve(
    init?.method === 'POST' && String(_url).endsWith('/cancel')
      ? new Response(null, { status: 204 })
      : new Response(JSON.stringify(init?.method === 'POST' ? submitted : { items: [submitted], next_cursor: null }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }),
  ))
  vi.stubGlobal('fetch', fetch)
  const context: AuthContextValue = {
    user: { id: 'owner', username: 'owner', display_name: 'Owner', is_administrator: false, is_active: true, version: 1, created_at: '2026-09-30T12:00:00Z' },
    token: 'token', isLoading: false, login: vi.fn(), logout: vi.fn(),
  }
  const { container } = render(<QueryClientProvider client={new QueryClient()}>
    <AuthContext.Provider value={context}>
      <BatchAssignmentsPanel projectId="project-1" batch={batch(purpose)} members={members} />
    </AuthContext.Provider>
  </QueryClientProvider>)
  const details = container.querySelector('details')!
  details.open = true
  fireEvent(details, new Event('toggle'))
  await screen.findByText('frame-1.png')
  return fetch
}

describe('BatchAssignmentsPanel', () => {
  it('lists assignments with names and reopens submitted work', async () => {
    const fetch = await renderPanel('test')

    expect(screen.getByText('Ana')).toBeInTheDocument()
    expect(screen.getByText('Submitted')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel image' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reopen' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/assignments/assignment-1/reopen'),
      expect.objectContaining({ method: 'POST' }),
    ))
  })

  it('reassigns only to other members allowed to annotate', async () => {
    const fetch = await renderPanel('test')
    const select = screen.getByRole('combobox', { name: 'Reassign frame-1.png' })

    expect([...select.querySelectorAll('option')].map((option) => option.textContent)).toEqual(['Reassign to…', 'Bruno'])
    fireEvent.change(select, { target: { value: 'bruno' } })
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/assignments/assignment-1/reassign'),
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ annotator_id: 'bruno' }) }),
    ))
  })

  it('cancels a training image after warning that it returns to the pool', async () => {
    const confirm = vi.fn().mockReturnValue(true)
    vi.stubGlobal('confirm', confirm)
    const fetch = await renderPanel('initial_training')

    fireEvent.click(screen.getByRole('button', { name: 'Cancel image' }))

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('returns to the unlabeled training pool'))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/batch-items/item-1/cancel'),
      expect.objectContaining({ method: 'POST' }),
    ))
  })
})
