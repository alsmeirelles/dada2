import type { PolygonGeometry, RectangleGeometry } from '../annotation/types'
import type { CandidateReviewEvidence, ImageReviewEvidence, ReviewDraft } from './review-types'

/** `[x, y, width, height]` in original-image pixels. */
export type Region = [number, number, number, number]

/** Keeps only the parts of saved or recovered evidence that a review can hold. */
export function readDraft(value: unknown): ReviewDraft {
  if (!isRecord(value)) return {}
  const draft: ReviewDraft = {}
  if (Array.isArray(value.class_ids) && value.class_ids.every((id) => typeof id === 'string')) draft.class_ids = value.class_ids
  if (value.decision === 'object' || value.decision === 'no_object') draft.decision = value.decision
  if (typeof value.class_id === 'string') draft.class_id = value.class_id
  if (isGeometry(value.geometry)) draft.geometry = value.geometry
  return draft
}

/** The exact evidence the API accepts for this case, or what is still missing. */
export function submittableEvidence(
  scope: 'image' | 'candidate',
  draft: ReviewDraft,
): { evidence: ImageReviewEvidence | CandidateReviewEvidence } | { problem: string } {
  if (scope === 'image') {
    const classIds = [...new Set(draft.class_ids ?? [])]
    return classIds.length ? { evidence: { class_ids: classIds } } : { problem: 'Choose at least one class for this image.' }
  }
  if (draft.decision === 'no_object') return { evidence: { decision: 'no_object' } }
  if (draft.decision !== 'object') return { problem: 'Say whether the region contains an object.' }
  if (!draft.class_id) return { problem: 'Choose the object\'s class.' }
  if (!draft.geometry) return { problem: 'Draw the object inside the region.' }
  return { evidence: { decision: 'object', class_id: draft.class_id, geometry: draft.geometry } }
}

export function insideRegion(geometry: RectangleGeometry | PolygonGeometry, region: Region | null) {
  if (!region) return true
  const [left, top, width, height] = region
  const inside = (x: number, y: number) => x >= left && y >= top && x <= left + width && y <= top + height
  if (geometry.type === 'rectangle') {
    const [x, y, boxWidth, boxHeight] = geometry.coordinates
    return inside(x, y) && inside(x + boxWidth, y + boxHeight)
  }
  return geometry.coordinates.every((ring) => ring.every((_, index) => index % 2 === 1 || inside(ring[index]!, ring[index + 1]!)))
}

function isGeometry(value: unknown): value is RectangleGeometry | PolygonGeometry {
  if (!isRecord(value) || !Array.isArray(value.coordinates)) return false
  if (value.type === 'rectangle') return value.coordinates.length === 4 && value.coordinates.every(Number.isFinite)
  return value.type === 'polygon' && value.coordinates.every((ring) => Array.isArray(ring) && ring.every(Number.isFinite))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
