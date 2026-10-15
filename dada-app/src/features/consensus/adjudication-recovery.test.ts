import { beforeEach, describe, expect, it } from 'vitest'

import { startDraft } from './adjudication'
import {
  ADJUDICATION_RECOVERY_TTL_MS,
  clearAdjudicationRecovery,
  loadAdjudicationRecovery,
  saveAdjudicationRecovery,
} from './adjudication-recovery'
import { evidence, workItem } from './consensus-fixtures'

const draft = startDraft(evidence(), workItem(), { kind: 'proposal' })

describe('adjudication recovery', () => {
  beforeEach(() => sessionStorage.clear())

  it('keys the draft by project, work item, actor, and base version', () => {
    saveAdjudicationRecovery('p1', 'w1', 'manager', draft, 1_000)

    expect(Object.keys(sessionStorage)).toEqual(['dada.adjudication-recovery:p1:w1:manager:1.0'])
    expect(loadAdjudicationRecovery('p1', 'w1', 'manager', 2_000)).toEqual({ savedAt: 1_000, baseVersion: '1.0', draft })
  })

  it('keeps drafts of other actors and work items isolated', () => {
    const other = { ...draft, objects: [] }
    saveAdjudicationRecovery('p1', 'w1', 'manager', draft, 1_000)
    saveAdjudicationRecovery('p1', 'w1', 'owner', other, 1_000)
    saveAdjudicationRecovery('p1', 'w2', 'manager', other, 1_000)

    expect(loadAdjudicationRecovery('p1', 'w1', 'manager', 2_000)?.draft).toEqual(draft)
    expect(loadAdjudicationRecovery('p1', 'w1', 'owner', 2_000)?.draft).toEqual(other)
    clearAdjudicationRecovery('p1', 'w2', 'manager')
    expect(loadAdjudicationRecovery('p1', 'w1', 'manager', 2_000)).not.toBeNull()
    expect(loadAdjudicationRecovery('p1', 'w2', 'manager', 2_000)).toBeNull()
  })

  it('moves the draft to its new base version instead of keeping both', () => {
    saveAdjudicationRecovery('p1', 'w1', 'manager', draft, 1_000)
    saveAdjudicationRecovery('p1', 'w1', 'manager', { ...draft, base: { ...draft.base, evidence_generation: 2, resolution_version: 1 } }, 1_500)

    expect(Object.keys(sessionStorage)).toEqual(['dada.adjudication-recovery:p1:w1:manager:2.1'])
  })

  it('discards expired or malformed drafts', () => {
    saveAdjudicationRecovery('p1', 'w1', 'manager', draft, 1_000)
    expect(loadAdjudicationRecovery('p1', 'w1', 'manager', 1_000 + ADJUDICATION_RECOVERY_TTL_MS + 1)).toBeNull()

    sessionStorage.setItem('dada.adjudication-recovery:p1:w1:manager:1.0', JSON.stringify({ savedAt: 1_000, baseVersion: '1.0', draft: { action: 'delete' } }))
    expect(loadAdjudicationRecovery('p1', 'w1', 'manager', 2_000)).toBeNull()
    expect(sessionStorage.length).toBe(0)
  })
})
