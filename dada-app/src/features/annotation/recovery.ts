import type { AnnotationDocument } from './types'

const PREFIX = 'dada.annotation-recovery'
export const RECOVERY_TTL_MS = 24 * 60 * 60 * 1_000

type RecoverySnapshot = { savedAt: number; document: AnnotationDocument }

export function saveRecovery(projectId: string, assignmentId: string, document: AnnotationDocument, now = Date.now()) {
  try {
    sessionStorage.setItem(
      key(projectId, assignmentId),
      JSON.stringify({ savedAt: now, document } satisfies RecoverySnapshot),
    )
  } catch {
    // Storage can be unavailable or full; API autosave remains authoritative.
  }
}

export function loadRecovery(projectId: string, assignmentId: string, mediaId: string, now = Date.now()) {
  try {
    const storageKey = key(projectId, assignmentId)
    const raw = sessionStorage.getItem(storageKey)
    if (!raw) return null
    const snapshot = JSON.parse(raw) as Partial<RecoverySnapshot>
    if (
      typeof snapshot.savedAt !== 'number' ||
      now - snapshot.savedAt > RECOVERY_TTL_MS ||
      !isAnnotationDocument(snapshot.document, mediaId)
    ) {
      sessionStorage.removeItem(storageKey)
      return null
    }
    return snapshot.document
  } catch {
    clearRecovery(projectId, assignmentId)
    return null
  }
}

export function clearRecovery(projectId: string, assignmentId: string) {
  try {
    sessionStorage.removeItem(key(projectId, assignmentId))
  } catch {
    // A blocked storage API does not affect server persistence.
  }
}

function key(projectId: string, assignmentId: string) {
  return `${PREFIX}:${projectId}:${assignmentId}`
}

function isAnnotationDocument(
  value: RecoverySnapshot['document'] | undefined,
  mediaId: string,
): value is AnnotationDocument {
  return Boolean(
    value &&
    value.media_id === mediaId &&
    typeof value.version === 'number' &&
    Array.isArray(value.objects) &&
    ['classification', 'detection', 'segmentation'].includes(value.task_type),
  )
}
