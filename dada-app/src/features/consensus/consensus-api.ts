import { apiRequest } from '../../api/client'
import type { Page } from '../projects/types'
import type { AnnotationDocument } from '../annotation/types'
import type { ResolutionEvidence, ResolutionQueueItem } from './consensus-types'

export function getResolutionQueue(projectId: string, token: string) {
  return apiRequest<Page<ResolutionQueueItem>>(`/api/v1/projects/${projectId}/batches/resolutions`, { token })
}

export function getResolutionEvidence(projectId: string, batchItemId: string, token: string) {
  return apiRequest<ResolutionEvidence>(`/api/v1/projects/${projectId}/batch-items/${batchItemId}/evidence`, { token })
}

export function acceptResolution(projectId: string, batchItemId: string, resolutionId: string, token: string) {
  return apiRequest(`/api/v1/projects/${projectId}/batch-items/${batchItemId}/adjudicate`, {
    method: 'POST', token, headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: { action: 'accept', resolution_id: resolutionId },
  })
}

export function retryResolution(projectId: string, batchItemId: string, token: string) {
  return apiRequest(`/api/v1/projects/${projectId}/batch-items/${batchItemId}/resolve`, {
    method: 'POST', token, headers: { 'Idempotency-Key': crypto.randomUUID() }, body: {},
  })
}

export function adjudicateResolution(projectId: string, batchItemId: string, document: AnnotationDocument, token: string) {
  return apiRequest(`/api/v1/projects/${projectId}/batch-items/${batchItemId}/adjudicate`, {
    method: 'POST', token, headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: { action: 'replace', document },
  })
}
