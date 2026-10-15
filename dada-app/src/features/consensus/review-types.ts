import type { PolygonGeometry, RectangleGeometry } from '../annotation/types'

export type ReviewStatus = 'pending' | 'in_progress' | 'submitted' | 'cancelled'

/** A reviewer's own label set for an image-level classification case. */
export type ImageReviewEvidence = { class_ids: string[] }

/** A reviewer's statement about one candidate: an object with its class and geometry, or nothing there. */
export type CandidateReviewEvidence =
  | { decision: 'object'; class_id: string; geometry: RectangleGeometry | PolygonGeometry }
  | { decision: 'no_object' }

/** A draft may be incomplete; a submission must be one of the typed shapes. */
export type ReviewEvidence = ImageReviewEvidence | CandidateReviewEvidence | Record<string, never>

/** A reviewer's work in progress. Drafts are free-form, so every part is optional until submission. */
export type ReviewDraft = {
  class_ids?: string[]
  decision?: 'object' | 'no_object'
  class_id?: string
  geometry?: RectangleGeometry | PolygonGeometry
}

export type ReviewQueueItem = {
  id: string
  work_item_id: string
  media_id: string
  relative_path: string
  scope: 'image' | 'candidate'
  status: ReviewStatus
  version: number
  updated_at: string
}

export type ReviewQueue = {
  items: ReviewQueueItem[]
  next_cursor: string | null
  counts: Record<'pending' | 'in_progress' | 'submitted', number>
}

export type ReviewAssignmentDetail = {
  id: string
  project_id: string
  work_item_id: string
  source_input_id: string
  candidate_key: string
  candidate_ordinal: number
  scope: 'image' | 'candidate'
  status: ReviewStatus
  version: number
  media: { id: string; relative_path: string; width: number; height: number; image_url: string }
  /** `region` is `[x, y, width, height]` in image pixels; image cases have none. */
  candidate_context: { region?: [number, number, number, number] }
  /** The submitted evidence once submitted, otherwise the saved draft. */
  evidence: ReviewDraft
  draft_saved_at: string | null
  submitted_at: string | null
}

export type ReviewDraftSaved = { id: string; status: ReviewStatus; version: number; draft_saved_at: string }

export type ReviewSubmissionReceived = { id: string; status: ReviewStatus; version: number; submission_id: string; submitted_at: string }
