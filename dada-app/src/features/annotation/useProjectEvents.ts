import { useEffect, useState } from 'react'

import { createEventTicket } from './annotation-api'
import { projectWebSocketUrl, reconnectDelay } from './realtime-utils'
import type { ProjectEvent } from './types'

export type RealtimeStatus = 'connecting' | 'live' | 'polling'

export function useProjectEvents(
  projectId: string,
  token: string | null,
  onEvent: (event: ProjectEvent, sequenceGap: boolean) => void,
) {
  const [status, setStatus] = useState<RealtimeStatus>('connecting')

  useEffect(() => {
    if (!projectId || !token) return
    let disposed = false
    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let attempt = 0
    let lastSequence: number | null = null

    async function connect() {
      setStatus(attempt ? 'polling' : 'connecting')
      try {
        const ticket = await createEventTicket(projectId, token!)
        if (disposed) return
        const url = new URL(projectWebSocketUrl(projectId, ticket.websocket_url), window.location.origin)
        url.searchParams.set('ticket', ticket.ticket)
        socket = new WebSocket(url)
        socket.addEventListener('open', () => {
          attempt = 0
          setStatus('live')
        })
        socket.addEventListener('message', (message) => {
          try {
            const event = JSON.parse(String(message.data)) as ProjectEvent
            const gap = lastSequence !== null && event.sequence !== lastSequence + 1
            lastSequence = event.sequence
            onEvent(event, gap)
          } catch {
            // A malformed event is ignored; REST polling remains authoritative.
          }
        })
        socket.addEventListener('close', scheduleReconnect)
        socket.addEventListener('error', () => socket?.close())
      } catch {
        scheduleReconnect()
      }
    }

    function scheduleReconnect() {
      if (disposed || retryTimer !== undefined) return
      setStatus('polling')
      retryTimer = window.setTimeout(() => {
        retryTimer = undefined
        attempt += 1
        void connect()
      }, reconnectDelay(attempt))
    }

    void connect()
    return () => {
      disposed = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      socket?.close()
    }
  }, [onEvent, projectId, token])

  return status
}
