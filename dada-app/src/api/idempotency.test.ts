import { describe, expect, it } from 'vitest'

import { requestKey } from './idempotency'

describe('requestKey', () => {
  it('repeats for an identical retry', async () => {
    const body = { version: 2, objects: [{ id: 'o1' }] }

    expect(await requestKey('submit:a1', body)).toBe(await requestKey('submit:a1', { ...body }))
  })

  it('changes when the body or scope changes', async () => {
    const key = await requestKey('submit:a1', { version: 2, objects: [] })

    expect(await requestKey('submit:a1', { version: 2, objects: [{ id: 'o1' }] })).not.toBe(key)
    expect(await requestKey('submit:a2', { version: 2, objects: [] })).not.toBe(key)
  })

  it('stays within the length the API accepts', async () => {
    const key = await requestKey(`adjudicate:${'f'.repeat(36)}`, { action: 'replace' })

    expect(key.length).toBeGreaterThanOrEqual(8)
    expect(key.length).toBeLessThanOrEqual(128)
  })
})
