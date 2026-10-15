import { apiRequest } from '../../api/client'
import { requestKey } from '../../api/idempotency'
import { config } from '../../config/env'
import type {
  ReviewAssignmentDetail,
  ReviewDraft,
  ReviewDraftSaved,
  ReviewEvidence,
  ReviewQueue,
  ReviewSubmissionReceived,
} from './review-types'

export const reviewKeys = {
  queue: (projectId: string) => ['candidate-review-queue', projectId] as const,
  assignment: (projectId: string, assignmentId: string) => ['candidate-review', projectId, assignmentId] as const,
}

export function listReviewAssignments(projectId: string, token: string) {
  return apiRequest<ReviewQueue>(`/api/v1/projects/${projectId}/review-assignments`, { token })
}

export async function getReviewAssignment(projectId: string, assignmentId: string, token: string) {
  const detail = await apiRequest<ReviewAssignmentDetail>(`/api/v1/projects/${projectId}/review-assignments/${assignmentId}`, { token })
  return { ...detail, media: { ...detail.media, image_url: `${config.apiBaseUrl}${detail.media.image_url}` } }
}

export function saveReviewDraft(projectId: string, assignmentId: string, version: number, evidence: ReviewDraft, token: string) {
  return apiRequest<ReviewDraftSaved>(`/api/v1/projects/${projectId}/review-assignments/${assignmentId}/draft`, { method: 'PUT', token, body: { version, evidence } })
}

/** Keyed by the body, so a corrected review after a `422` is a new request (I6-02). */
export async function submitReview(projectId: string, assignmentId: string, version: number, evidence: ReviewEvidence, token: string) {
  const body = { version, evidence }
  return apiRequest<ReviewSubmissionReceived>(`/api/v1/projects/${projectId}/review-assignments/${assignmentId}/submit`, { method: 'POST', token, headers: { 'Idempotency-Key': await requestKey(`review:${assignmentId}`, body) }, body })
}
