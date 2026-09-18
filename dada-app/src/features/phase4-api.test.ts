import { afterEach, describe, expect, it, vi } from 'vitest'

import { changePassword } from './account/account-api'
import { deleteUser, listUsers, updateUser } from './admin/admin-api'
import { updateBatchPolicy } from './projects/batch-api'
import type { AnnotationPolicy } from './projects/types'

afterEach(() => vi.unstubAllGlobals())

function mockJsonResponse(payload: unknown = {}) {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(
    JSON.stringify(payload),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('Phase 4 API clients', () => {
  it('replaces only a preparing batch policy snapshot', async () => {
    const fetch = mockJsonResponse()
    const policy: AnnotationPolicy = {
      mode: 'consensus',
      version: 8,
      annotator_ids: ['annotator-a', 'annotator-b'],
      resolver: 'majority_vote',
      resolver_version: '2.0',
      parameters: { minimum_votes: 2 },
      review_thresholds: { agreement: 0.8 },
    }

    await updateBatchPolicy('project-1', 'batch-1', policy, 'token')

    const [url, request] = fetch.mock.calls[0]!
    expect(url).toMatch(/\/api\/v1\/projects\/project-1\/batches\/batch-1$/)
    expect(request).toMatchObject({ method: 'PATCH' })
    expect(JSON.parse(request.body)).toEqual({
      mode: 'consensus',
      annotator_ids: ['annotator-a', 'annotator-b'],
      resolver: 'majority_vote',
      parameters: { minimum_votes: 2 },
      review_thresholds: { agreement: 0.8 },
    })
  })

  it('preserves the active filter and cursor in the user directory request', async () => {
    const fetch = mockJsonResponse({ items: [] })

    await listUsers('token', false, 'next page')

    expect(fetch.mock.calls[0]![0]).toMatch(/\/api\/v1\/users\?active=false&cursor=next\+page$/)
  })

  it('sends the displayed version for user update and deletion', async () => {
    const fetch = mockJsonResponse()

    await updateUser('user-1', {
      display_name: 'Updated user',
      is_active: true,
      is_administrator: false,
      version: 4,
    }, 'token')
    await deleteUser('user-1', 4, 'token')

    expect(JSON.parse(fetch.mock.calls[0]![1].body).version).toBe(4)
    expect(fetch.mock.calls[1]![1]).toMatchObject({
      method: 'DELETE',
      headers: expect.objectContaining({ 'If-Match': '4' }),
    })
  })

  it('uses the self-service password contract without adding credential fields', async () => {
    const fetch = mockJsonResponse()

    await changePassword('current secret', 'replacement secret', 'token')

    expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual({
      current_password: 'current secret',
      new_password: 'replacement secret',
    })
  })
})
