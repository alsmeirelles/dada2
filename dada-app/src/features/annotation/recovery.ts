import type { AnnotationDocument } from './types'

const PREFIX = 'dada.annotation-recovery'
export const RECOVERY_TTL_MS = 24 * 60 * 60 * 1_000

/** Unsaved work kept in this tab, and the server version it was built on. */
export type RecoverySnapshot = { savedAt: number; baseVersion: number; document: AnnotationDocument }

export function saveRecovery(
  projectId: string,
  assignmentId: string,
  baseVersion: number,
  document: AnnotationDocument,
  now = Date.now(),
) {
  try {
    clearRecovery(projectId, assignmentId)
    sessionStorage.setItem(
      `${assignmentPrefix(projectId, assignmentId)}${baseVersion}`,
      JSON.stringify({ savedAt: now, baseVersion, document } satisfies RecoverySnapshot),
    )
  } catch {
    // Storage can be unavailable or full; the server draft remains authoritative.
  }
}

export function loadRecovery(projectId: string, assignmentId: string, mediaId: string, now = Date.now()) {
  try {
    const storageKey = assignmentKeys(projectId, assignmentId)[0]
    const raw = storageKey ? sessionStorage.getItem(storageKey) : null
    if (!storageKey || !raw) return null
    const snapshot = JSON.parse(raw) as Partial<RecoverySnapshot>
    if (
      typeof snapshot.savedAt !== 'number' ||
      typeof snapshot.baseVersion !== 'number' ||
      now - snapshot.savedAt > RECOVERY_TTL_MS ||
      !isAnnotationDocument(snapshot.document, mediaId)
    ) {
      sessionStorage.removeItem(storageKey)
      return null
    }
    return snapshot as RecoverySnapshot
  } catch {
    clearRecovery(projectId, assignmentId)
    return null
  }
}

export function clearRecovery(projectId: string, assignmentId: string) {
  try {
    for (const storageKey of assignmentKeys(projectId, assignmentId)) sessionStorage.removeItem(storageKey)
  } catch {
    // A blocked storage API does not affect server persistence.
  }
}

function assignmentPrefix(projectId: string, assignmentId: string) {
  return `${PREFIX}:${projectId}:${assignmentId}:`
}

function assignmentKeys(projectId: string, assignmentId: string) {
  const prefix = assignmentPrefix(projectId, assignmentId)
  return Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index))
    .filter((storageKey): storageKey is string => storageKey?.startsWith(prefix) ?? false)
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
