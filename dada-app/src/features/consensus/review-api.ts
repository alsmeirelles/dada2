import { apiRequest } from '../../api/client'
import { config } from '../../config/env'
import type { ReviewAssignmentDetail, ReviewQueue } from './review-types'

export function listReviewAssignments(projectId: string, token: string) {
  return apiRequest<ReviewQueue>(`/api/v1/projects/${projectId}/review-assignments`, { token })
}

export async function getReviewAssignment(projectId: string, assignmentId: string, token: string) {
  const detail = await apiRequest<ReviewAssignmentDetail>(`/api/v1/projects/${projectId}/review-assignments/${assignmentId}`, { token })
  return { ...detail, media: { ...detail.media, image_url: `${config.apiBaseUrl}${detail.media.image_url}` } }
}

export function saveReviewDraft(projectId: string, assignmentId: string, version: number, evidence: Record<string, unknown>, token: string) {
  return apiRequest<{ version: number }>(`/api/v1/projects/${projectId}/review-assignments/${assignmentId}/draft`, { method: 'PUT', token, body: { version, evidence } })
}

export function submitReview(projectId: string, assignmentId: string, version: number, evidence: Record<string, unknown>, token: string) {
  return apiRequest(`/api/v1/projects/${projectId}/review-assignments/${assignmentId}/submit`, { method: 'POST', token, headers: { 'Idempotency-Key': `review:${assignmentId}:${version}` }, body: { version, evidence } })
}
