import { useCallback, useEffect, useRef, useState } from 'react'

import { acquireLease, releaseLease } from './consensus-api'
import type { LeaseView } from './consensus-types'

export const LEASE_RENEW_MS = 5 * 60_000

export type EditLeaseStatus = 'idle' | 'acquiring' | 'held' | 'lost'

/**
 * The caller's edit lease on one work item: acquired on request, renewed every
 * five minutes while held, released on request and on unmount. A renewal that
 * fails, or that returns a different lease than the one held (it expired or was
 * revoked), marks the lease lost; editing stops until it is reacquired.
 */
export function useEditLease(projectId: string, workItemId: string, token: string | null) {
  const [lease, setLease] = useState<LeaseView | null>(null)
  const [status, setStatus] = useState<EditLeaseStatus>('idle')
  const [error, setError] = useState<unknown>(null)
  const leaseRef = useRef<LeaseView | null>(null)
  const statusRef = useRef<EditLeaseStatus>('idle')
  const tokenRef = useRef(token)
  tokenRef.current = token

  const set = useCallback((value: LeaseView | null, next: EditLeaseStatus, failure: unknown = null) => {
    leaseRef.current = value
    statusRef.current = next
    setLease(value)
    setStatus(next)
    setError(failure)
  }, [])

  const markLost = useCallback((failure: unknown) => set(null, 'lost', failure), [set])

  const acquire = useCallback(async () => {
    if (!token) return false
    const previous = statusRef.current
    set(leaseRef.current, 'acquiring')
    try {
      if (previous === 'lost') await releaseLease(projectId, workItemId, token).catch(() => undefined)
      set(await acquireLease(projectId, workItemId, token), 'held')
      return true
    } catch (failure) {
      set(null, previous === 'lost' ? 'lost' : 'idle', failure)
      return false
    }
  }, [projectId, set, token, workItemId])

  const release = useCallback(async () => {
    const owned = leaseRef.current || statusRef.current === 'lost'
    set(null, 'idle')
    if (owned && token) await releaseLease(projectId, workItemId, token).catch(() => undefined)
  }, [projectId, set, token, workItemId])

  useEffect(() => {
    if (status !== 'held' || !token) return
    const timer = window.setInterval(() => {
      const held = leaseRef.current
      void acquireLease(projectId, workItemId, token).then(async (renewed) => {
        if (held && renewed.acquired_at !== held.acquired_at) {
          await releaseLease(projectId, workItemId, token).catch(() => undefined)
          markLost(new Error('Your edit lease ended before it was renewed. Reacquire it to keep editing.'))
          return
        }
        set(renewed, 'held')
      }, markLost)
    }, LEASE_RENEW_MS)
    return () => window.clearInterval(timer)
  }, [markLost, projectId, set, status, token, workItemId])

  useEffect(() => () => {
    if (leaseRef.current && tokenRef.current) void releaseLease(projectId, workItemId, tokenRef.current).catch(() => undefined)
  }, [projectId, workItemId])

  return { lease, status, error, acquire, release, markLost }
}
