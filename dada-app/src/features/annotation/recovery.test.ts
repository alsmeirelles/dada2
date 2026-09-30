import { beforeEach, describe, expect, it } from 'vitest'

import type { AnnotationDocument } from './types'
import { clearRecovery, loadRecovery, RECOVERY_TTL_MS, saveRecovery } from './recovery'

const document: AnnotationDocument = {
  media_id: 'media-1', task_type: 'detection', version: 2, objects: [],
}

describe('annotation recovery', () => {
  beforeEach(() => sessionStorage.clear())

  it('restores a recent snapshot with its base version and clears it after persistence', () => {
    saveRecovery('project-1', 'assignment-1', 2, document, 1_000)
    expect(loadRecovery('project-1', 'assignment-1', 'media-1', 2_000)).toEqual({
      savedAt: 1_000, baseVersion: 2, document,
    })
    clearRecovery('project-1', 'assignment-1')
    expect(loadRecovery('project-1', 'assignment-1', 'media-1', 2_000)).toBeNull()
  })

  it('keys the snapshot by project, assignment, and base version', () => {
    saveRecovery('project-1', 'assignment-1', 4, document, 1_000)
    expect(Object.keys(sessionStorage)).toEqual(['dada.annotation-recovery:project-1:assignment-1:4'])
  })

  it('keeps only the newest snapshot of an assignment', () => {
    saveRecovery('project-1', 'assignment-1', 2, document, 1_000)
    saveRecovery('project-1', 'assignment-1', 3, { ...document, version: 3 }, 1_500)

    expect(sessionStorage.length).toBe(1)
    expect(loadRecovery('project-1', 'assignment-1', 'media-1', 2_000)?.baseVersion).toBe(3)
  })

  it('discards expired recovery data', () => {
    saveRecovery('project-1', 'assignment-1', 2, document, 1_000)
    expect(loadRecovery('project-1', 'assignment-1', 'media-1', 1_000 + RECOVERY_TTL_MS + 1)).toBeNull()
  })

  it('keeps independent assignments for the same media isolated', () => {
    saveRecovery('project-1', 'assignment-a', 2, document, 1_000)
    const second = { ...document, version: 3, objects: [{ id: 'object-1', class_id: 'class-1', geometry: { type: 'rectangle' as const, coordinates: [1, 2, 3, 4] as [number, number, number, number] }, attributes: {} }] }
    saveRecovery('project-1', 'assignment-b', 3, second, 1_000)

    expect(loadRecovery('project-1', 'assignment-a', 'media-1', 2_000)?.document).toEqual(document)
    expect(loadRecovery('project-1', 'assignment-b', 'media-1', 2_000)?.document).toEqual(second)
  })
})
