import { apiRequest } from '../../api/client'
import type { AnnotationBatch, AnnotationPolicy, Page } from './types'

export function listBatches(projectId: string, token: string, cursor?: string) {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return apiRequest<Page<AnnotationBatch>>(
    `/api/v1/projects/${projectId}/batches${query}`,
    { token },
  )
}

export function getBatch(projectId: string, batchId: string, token: string) {
  return apiRequest<AnnotationBatch>(
    `/api/v1/projects/${projectId}/batches/${batchId}`,
    { token },
  )
}

export function updateBatchPolicy(
  projectId: string,
  batchId: string,
  policy: AnnotationPolicy,
  token: string,
) {
  return apiRequest<AnnotationBatch>(
    `/api/v1/projects/${projectId}/batches/${batchId}`,
    {
      method: 'PATCH',
      token,
      body: {
        mode: policy.mode,
        annotator_ids: policy.annotator_ids,
        resolver: policy.resolver ?? null,
        parameters: policy.parameters ?? {},
        review_thresholds: policy.review_thresholds ?? {},
      },
    },
  )
}

export function startBatch(projectId: string, batchId: string, token: string) {
  return apiRequest<AnnotationBatch>(
    `/api/v1/projects/${projectId}/batches/${batchId}/start`,
    { method: 'POST', token, body: {} },
  )
}
