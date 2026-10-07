export type ReviewStatus = 'pending' | 'in_progress' | 'submitted' | 'cancelled'

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
  candidate_context: Record<string, unknown>
  evidence: Record<string, unknown>
  draft_saved_at: string | null
  submitted_at: string | null
}
