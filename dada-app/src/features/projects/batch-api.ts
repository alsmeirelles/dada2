import { apiRequest } from '../../api/client'
import type { BatchAssignment } from '../annotation/types'
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

/** The policy fields a batch snapshot carries; a default policy, a batch, or an edited copy of either. */
export type BatchPolicySource = Pick<AnnotationPolicy,
  'mode' | 'annotator_ids' | 'required_consensus_annotations' | 'required_consensus_reviewers' |
  'resolver' | 'parameters' | 'review_thresholds' | 'require_independent_adjudicator'>

/** Replaces the policy snapshot of a batch that is still preparing; an unknown independence flag takes the API default. */
export function updateBatchPolicy(
  projectId: string,
  batchId: string,
  policy: BatchPolicySource,
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
        required_consensus_annotations: policy.required_consensus_annotations,
        required_consensus_reviewers: policy.required_consensus_reviewers,
        resolver: policy.resolver ?? null,
        parameters: policy.parameters ?? {},
        review_thresholds: policy.review_thresholds ?? {},
        ...(policy.require_independent_adjudicator === undefined ? {} : { require_independent_adjudicator: policy.require_independent_adjudicator }),
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

export async function listBatchAssignments(projectId: string, batchId: string, token: string) {
  const items: BatchAssignment[] = []
  let page: Page<BatchAssignment> | null = null
  do {
    const query: string = page?.next_cursor ? `?cursor=${encodeURIComponent(page.next_cursor)}` : ''
    page = await apiRequest<Page<BatchAssignment>>(
      `/api/v1/projects/${projectId}/batches/${batchId}/assignments${query}`,
      { token },
    )
    items.push(...page.items)
  } while (page.next_cursor)
  return items
}

export function reopenAssignment(projectId: string, assignmentId: string, token: string) {
  return apiRequest<BatchAssignment>(
    `/api/v1/projects/${projectId}/assignments/${assignmentId}/reopen`,
    { method: 'POST', token, body: {} },
  )
}

export function reassignAssignment(projectId: string, assignmentId: string, annotatorId: string, token: string) {
  return apiRequest<BatchAssignment>(
    `/api/v1/projects/${projectId}/assignments/${assignmentId}/reassign`,
    { method: 'POST', token, body: { annotator_id: annotatorId } },
  )
}

export function cancelBatchItem(projectId: string, batchItemId: string, token: string) {
  return apiRequest<void>(
    `/api/v1/projects/${projectId}/batch-items/${batchItemId}/cancel`,
    { method: 'POST', token, body: {} },
  )
}
