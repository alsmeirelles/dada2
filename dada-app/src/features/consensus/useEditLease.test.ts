import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiError, json, lease, stubApi } from './consensus-fixtures'
import { LEASE_RENEW_MS, useEditLease } from './useEditLease'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function leaseCalls(fetch: ReturnType<typeof stubApi>, method: string) {
  return fetch.mock.calls.filter(([url, init]) => String(url).endsWith('/resolution-work-items/w1/lease') && (init?.method ?? 'GET') === method)
}

describe('useEditLease', () => {
  it('acquires, renews every five minutes, and releases on unmount', async () => {
    const fetch = stubApi(({ method }) => method === 'POST' ? json(lease()) : new Response(null, { status: 204 }))
    const { result, unmount } = renderHook(() => useEditLease('p1', 'w1', 'token'))

    await act(async () => { await result.current.acquire() })
    expect(result.current.status).toBe('held')
    expect(leaseCalls(fetch, 'POST')).toHaveLength(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(LEASE_RENEW_MS) })
    expect(leaseCalls(fetch, 'POST')).toHaveLength(2)
    expect(result.current.status).toBe('held')

    unmount()
    expect(leaseCalls(fetch, 'DELETE')).toHaveLength(1)
  })

  it('marks the lease lost when a renewal returns a different lease, and gives that one back', async () => {
    let renewals = 0
    const fetch = stubApi(({ method }) => {
      if (method === 'DELETE') return new Response(null, { status: 204 })
      renewals += 1
      return json(lease(renewals > 1 ? { acquired_at: '2026-10-14T11:00:00Z' } : {}))
    })
    const { result } = renderHook(() => useEditLease('p1', 'w1', 'token'))

    await act(async () => { await result.current.acquire() })
    await act(async () => { await vi.advanceTimersByTimeAsync(LEASE_RENEW_MS) })

    expect(result.current.status).toBe('lost')
    expect(result.current.lease).toBeNull()
    expect(leaseCalls(fetch, 'DELETE')).toHaveLength(1)
  })

  it('marks the lease lost when renewal fails, and reacquires explicitly after releasing', async () => {
    let fail = false
    const fetch = stubApi(({ method }) => {
      if (method === 'DELETE') return new Response(null, { status: 204 })
      return fail ? apiError(409, 'lease_cap_reached', 'The lease reached its two-hour limit.') : json(lease())
    })
    const { result } = renderHook(() => useEditLease('p1', 'w1', 'token'))

    await act(async () => { await result.current.acquire() })
    fail = true
    await act(async () => { await vi.advanceTimersByTimeAsync(LEASE_RENEW_MS) })
    expect(result.current.status).toBe('lost')

    fail = false
    await act(async () => { await result.current.acquire() })
    expect(result.current.status).toBe('held')
    expect(leaseCalls(fetch, 'DELETE')).toHaveLength(1)
  })

  it('reports a lease someone else holds without holding one', async () => {
    stubApi(() => apiError(409, 'lease_held', 'Another owner or manager is editing this case.'))
    const { result } = renderHook(() => useEditLease('p1', 'w1', 'token'))

    let acquired = true
    await act(async () => { acquired = await result.current.acquire() })

    expect(acquired).toBe(false)
    expect(result.current.status).toBe('idle')
    expect(result.current.error).toMatchObject({ code: 'lease_held' })
  })
})
