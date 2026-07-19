import { describe, expect, it } from 'vitest'

import { projectWebSocketUrl, reconnectDelay } from './realtime-utils'

describe('project realtime utilities', () => {
  it('uses a server-provided websocket URL when present', () => {
    expect(projectWebSocketUrl('project', 'wss://events.example.test/socket')).toBe(
      'wss://events.example.test/socket',
    )
  })

  it('caps exponential reconnect delay', () => {
    expect(reconnectDelay(0)).toBe(1_000)
    expect(reconnectDelay(9)).toBe(30_000)
  })
})
