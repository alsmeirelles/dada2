import { beforeEach, describe, expect, it } from 'vitest'

import type { AnnotationDocument } from './types'
import { clearRecovery, loadRecovery, RECOVERY_TTL_MS, saveRecovery } from './recovery'

const document: AnnotationDocument = {
  media_id: 'media-1', task_type: 'detection', version: 2, objects: [],
}

describe('annotation recovery', () => {
  beforeEach(() => sessionStorage.clear())

  it('restores a recent snapshot and clears it after persistence', () => {
    saveRecovery('project-1', document, 1_000)
    expect(loadRecovery('project-1', 'media-1', 2_000)).toEqual(document)
    clearRecovery('project-1', 'media-1')
    expect(loadRecovery('project-1', 'media-1', 2_000)).toBeNull()
  })

  it('discards expired recovery data', () => {
    saveRecovery('project-1', document, 1_000)
    expect(loadRecovery('project-1', 'media-1', 1_000 + RECOVERY_TTL_MS + 1)).toBeNull()
  })
})
