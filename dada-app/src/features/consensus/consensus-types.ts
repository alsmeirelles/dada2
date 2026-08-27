import type { AnnotationDocument } from '../annotation/types'

export type ResolutionStatus = 'pending' | 'running' | 'resolved' | 'review_required' | 'failed'

export type ResolutionQueueItem = {
  batch_item_id: string
  media_id: string
  relative_path: string
  submission_count: number
  required_submission_count: number
  status: ResolutionStatus
  review_reason?: string | null
  diagnostics?: Record<string, number | string | boolean>
}

export type ResolutionEvidence = {
  batch_item_id: string
  status: ResolutionStatus
  media: { id: string; image_url: string; relative_path: string; width: number; height: number }
  submissions: Array<{ id: string; document: AnnotationDocument }>
  proposed_resolution?: { id: string; document: AnnotationDocument } | null
  accepted_resolution?: { id: string; document: AnnotationDocument } | null
  diagnostics: Record<string, number | string | boolean>
  resolver?: { name: string; version: string; parameters: Record<string, unknown> } | null
}
