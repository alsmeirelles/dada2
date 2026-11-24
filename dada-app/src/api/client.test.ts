import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest, onUnauthorized } from './client'

afterEach(() => {
  onUnauthorized(null)
  vi.unstubAllGlobals()
})

function respond(status: number) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'unauthenticated', message: 'Expired.' } }), { status, headers: { 'Content-Type': 'application/json' } })))
}

describe('I7-05: an ended session', () => {
  it('reports a 401 to a request made with an access token', async () => {
    const handler = vi.fn()
    onUnauthorized(handler)
    respond(401)

    await expect(apiRequest('/api/v1/projects', { token: 'expired' })).rejects.toMatchObject({ status: 401 })
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('leaves a failed login and other errors alone', async () => {
    const handler = vi.fn()
    onUnauthorized(handler)
    respond(401)
    await expect(apiRequest('/api/v1/auth/token', { method: 'POST', body: {} })).rejects.toMatchObject({ status: 401 })
    respond(403)
    await expect(apiRequest('/api/v1/projects', { token: 'valid' })).rejects.toMatchObject({ status: 403 })

    expect(handler).not.toHaveBeenCalled()
  })
})
