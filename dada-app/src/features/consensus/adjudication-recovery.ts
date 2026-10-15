import type { EvidenceVersions } from './consensus-types'
import type { AdjudicationDraft } from './adjudication'

const PREFIX = 'dada.adjudication-recovery'
export const ADJUDICATION_RECOVERY_TTL_MS = 24 * 60 * 60 * 1_000

/** An unconfirmed expert edit kept in this tab with the evidence version it was built on. */
export type AdjudicationSnapshot = { savedAt: number; baseVersion: string; draft: AdjudicationDraft }

/** The evidence generation and resolution version a draft is based on, e.g. `2.1`. */
export function baseVersionOf(versions: EvidenceVersions) {
  return `${versions.evidence_generation}.${versions.resolution_version}`
}

export function saveAdjudicationRecovery(
  projectId: string,
  workItemId: string,
  userId: string,
  draft: AdjudicationDraft,
  now = Date.now(),
) {
  try {
    clearAdjudicationRecovery(projectId, workItemId, userId)
    const baseVersion = baseVersionOf(draft.base)
    sessionStorage.setItem(
      `${draftPrefix(projectId, workItemId, userId)}${baseVersion}`,
      JSON.stringify({ savedAt: now, baseVersion, draft } satisfies AdjudicationSnapshot),
    )
  } catch {
    // Storage can be unavailable or full; the server never saw the draft either way.
  }
}

export function loadAdjudicationRecovery(projectId: string, workItemId: string, userId: string, now = Date.now()) {
  try {
    const storageKey = draftKeys(projectId, workItemId, userId)[0]
    const raw = storageKey ? sessionStorage.getItem(storageKey) : null
    if (!storageKey || !raw) return null
    const snapshot = JSON.parse(raw) as Partial<AdjudicationSnapshot>
    if (
      typeof snapshot.savedAt !== 'number' ||
      typeof snapshot.baseVersion !== 'string' ||
      now - snapshot.savedAt > ADJUDICATION_RECOVERY_TTL_MS ||
      !isDraft(snapshot.draft)
    ) {
      sessionStorage.removeItem(storageKey)
      return null
    }
    return snapshot as AdjudicationSnapshot
  } catch {
    clearAdjudicationRecovery(projectId, workItemId, userId)
    return null
  }
}

export function clearAdjudicationRecovery(projectId: string, workItemId: string, userId: string) {
  try {
    for (const storageKey of draftKeys(projectId, workItemId, userId)) sessionStorage.removeItem(storageKey)
  } catch {
    // A blocked storage API leaves nothing to clear.
  }
}

function draftPrefix(projectId: string, workItemId: string, userId: string) {
  return `${PREFIX}:${projectId}:${workItemId}:${userId}:`
}

function draftKeys(projectId: string, workItemId: string, userId: string) {
  const prefix = draftPrefix(projectId, workItemId, userId)
  return Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index))
    .filter((storageKey): storageKey is string => storageKey?.startsWith(prefix) ?? false)
}

function isDraft(value: AdjudicationDraft | undefined): value is AdjudicationDraft {
  return Boolean(
    value &&
    ['edit_proposal', 'edit_submission', 'replace'].includes(value.action) &&
    Array.isArray(value.objects) &&
    Array.isArray(value.sourceObjects) &&
    value.base &&
    typeof value.base.evidence_generation === 'number' &&
    typeof value.base.resolution_version === 'number',
  )
}
