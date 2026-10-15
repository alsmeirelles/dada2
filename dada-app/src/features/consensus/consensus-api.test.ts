import { afterEach, describe, expect, it, vi } from 'vitest'

import { config } from '../../config/env'
import {
  acquireLease,
  adjudicate,
  expectedVersions,
  getImageEvidence,
  listResolutionQueue,
  retryResolution,
} from './consensus-api'

afterEach(() => vi.unstubAllGlobals())

function stubFetch(payload: unknown = {}) {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(payload), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

const versions = { evidence_generation: 2, configuration_fingerprint: 'cfg', resolution_version: 1 }

describe('consensus client', () => {
  it('sends every queue filter, repeating the states', async () => {
    const fetch = stubFetch({ items: [], next_cursor: null })

    await listResolutionQueue('p1', 'b1', {
      state: ['review_required', 'pending_review'], reason: 'class_tie', classStrategy: 'categorical_vote', minAgeSeconds: 60,
    }, 'token', 'next')

    const url = new URL(String(fetch.mock.calls[0]![0]))
    expect(url.pathname).toBe('/api/v1/projects/p1/batches/b1/resolutions')
    expect(url.searchParams.getAll('state')).toEqual(['review_required', 'pending_review'])
    expect(Object.fromEntries([...url.searchParams].filter(([name]) => name !== 'state'))).toEqual({
      reason: 'class_tie', class_strategy: 'categorical_vote', min_age_seconds: '60', cursor: 'next',
    })
  })

  it('omits the query string without filters', async () => {
    const fetch = stubFetch({ items: [], next_cursor: null })

    await listResolutionQueue('p1', 'b1', {}, 'token')

    expect(String(fetch.mock.calls[0]![0])).toBe(`${config.apiBaseUrl}/api/v1/projects/p1/batches/b1/resolutions`)
  })

  it('resolves the signed image path against the API origin', async () => {
    stubFetch({ media: { id: 'm1', relative_path: 'a.png', width: 4, height: 3, image_url: '/api/v1/media/m1/content?x=1' } })

    const evidence = await getImageEvidence('p1', 'i1', 'token')

    expect(evidence.media.image_url).toBe(`${config.apiBaseUrl}/api/v1/media/m1/content?x=1`)
  })

  it('maps evidence versions to the expected-version fields', () => {
    expect(expectedVersions(versions)).toEqual({
      expected_evidence_generation: 2, expected_configuration_fingerprint: 'cfg', expected_resolution_version: 1,
    })
  })

  it('replays an identical retry and keys a changed decision anew', async () => {
    const fetch = stubFetch()
    const retry = { ...expectedVersions(versions), rationale: 'Rerun.' }
    const accept = { ...expectedVersions(versions), action: 'accept_proposal' as const }

    await retryResolution('p1', 'i1', retry, 'token')
    await retryResolution('p1', 'i1', { ...retry }, 'token')
    await adjudicate('p1', 'w1', accept, 'token')
    await adjudicate('p1', 'w1', { ...accept, rationale: 'Checked.' }, 'token')

    const keys = fetch.mock.calls.map(([, init]) => (init as RequestInit & { headers: Record<string, string> }).headers['Idempotency-Key'])
    expect(keys[0]).toBe(keys[1])
    expect(keys[2]).not.toBe(keys[3])
    expect(keys[2]!.startsWith('adjudicate:w1:')).toBe(true)
  })

  it('acquires a lease without a body', async () => {
    const fetch = stubFetch({ work_item_id: 'w1' })

    await acquireLease('p1', 'w1', 'token')

    const init = fetch.mock.calls[0]![1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
  })
})
