import { readDraft } from './review-draft'
import type { ReviewAssignmentDetail, ReviewDraft } from './review-types'

const PREFIX = 'dada.review-recovery'
export const REVIEW_RECOVERY_TTL_MS = 24 * 60 * 60 * 1_000

/** Unsaved review work kept in this tab, and the server version it was built on. */
export type ReviewRecovery = { savedAt: number; baseVersion: number; evidence: ReviewDraft }

export function saveReviewRecovery(
  projectId: string,
  reviewAssignmentId: string,
  baseVersion: number,
  evidence: ReviewDraft,
  now = Date.now(),
) {
  try {
    clearReviewRecovery(projectId, reviewAssignmentId)
    sessionStorage.setItem(
      `${reviewPrefix(projectId, reviewAssignmentId)}${baseVersion}`,
      JSON.stringify({ savedAt: now, baseVersion, evidence } satisfies ReviewRecovery),
    )
  } catch {
    // Storage can be unavailable or full; the server draft remains authoritative.
  }
}

export function loadReviewRecovery(projectId: string, reviewAssignmentId: string, now = Date.now()) {
  try {
    const storageKey = storedKeys(projectId, reviewAssignmentId)[0]
    const raw = storageKey ? sessionStorage.getItem(storageKey) : null
    if (!storageKey || !raw) return null
    const snapshot = JSON.parse(raw) as Partial<ReviewRecovery>
    if (
      typeof snapshot.savedAt !== 'number' ||
      typeof snapshot.baseVersion !== 'number' ||
      now - snapshot.savedAt > REVIEW_RECOVERY_TTL_MS ||
      typeof snapshot.evidence !== 'object' || snapshot.evidence === null
    ) {
      sessionStorage.removeItem(storageKey)
      return null
    }
    return { savedAt: snapshot.savedAt, baseVersion: snapshot.baseVersion, evidence: readDraft(snapshot.evidence) }
  } catch {
    clearReviewRecovery(projectId, reviewAssignmentId)
    return null
  }
}

export function clearReviewRecovery(projectId: string, reviewAssignmentId: string) {
  try {
    for (const storageKey of storedKeys(projectId, reviewAssignmentId)) sessionStorage.removeItem(storageKey)
  } catch {
    // A blocked storage API does not affect server persistence.
  }
}

export type OpenedReview = { evidence: ReviewDraft; dirty: boolean; conflict: ReviewRecovery | null; notice: string | null }

/**
 * Decides what the reviewer sees when a review opens: local work built on the
 * current version is restored; local work built on an older version means the
 * server changed meanwhile, so the reviewer chooses which one to keep.
 */
export function openReview(review: ReviewAssignmentDetail, local: ReviewRecovery | null): OpenedReview {
  const server = readDraft(review.evidence)
  const savedAt = local ? new Date(local.savedAt).toLocaleTimeString() : ''
  if (review.status === 'submitted') return { evidence: server, dirty: false, conflict: null, notice: 'Review submitted. It is read-only.' }
  if (review.status === 'cancelled') {
    return { evidence: server, dirty: false, conflict: null, notice: `This review was cancelled.${local ? ' Your unsaved work stays in this browser.' : ''}` }
  }
  if (local && local.baseVersion === review.version) {
    return { evidence: local.evidence, dirty: true, conflict: null, notice: `Recovered unsaved work from this browser, saved at ${savedAt}.` }
  }
  if (local) {
    return { evidence: server, dirty: false, conflict: local, notice: `This review changed on the server after your unsaved work from ${savedAt}. Choose which version to keep.` }
  }
  return { evidence: server, dirty: false, conflict: null, notice: null }
}

function reviewPrefix(projectId: string, reviewAssignmentId: string) {
  return `${PREFIX}:${projectId}:${reviewAssignmentId}:`
}

function storedKeys(projectId: string, reviewAssignmentId: string) {
  const prefix = reviewPrefix(projectId, reviewAssignmentId)
  return Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index))
    .filter((storageKey): storageKey is string => storageKey?.startsWith(prefix) ?? false)
}
