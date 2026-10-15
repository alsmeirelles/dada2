import { apiRequest } from '../../api/client'
import { requestKey } from '../../api/idempotency'
import { config } from '../../config/env'
import type {
  AdjudicationRequest,
  AdjudicationResponse,
  EvidenceVersions,
  ExpectedVersions,
  ImageEvidence,
  LeaseView,
  PerformanceReport,
  PolicyHistory,
  ResolutionQueueFilters,
  ResolutionQueuePage,
  ResolverEligibility,
  RetryRequest,
  RunView,
} from './consensus-types'

/** Query keys of the manager surfaces; reviewer queries never share them. */
export const consensusKeys = {
  queue: (projectId: string, batchId: string, filters: ResolutionQueueFilters) =>
    ['resolution-queue', projectId, batchId, filters] as const,
  queues: (projectId: string) => ['resolution-queue', projectId] as const,
  evidence: (projectId: string, batchItemId: string) => ['image-evidence', projectId, batchItemId] as const,
  performance: (projectId: string) => ['annotator-performance', projectId] as const,
  eligibility: (projectId: string) => ['resolver-eligibility', projectId] as const,
  policyHistory: (projectId: string) => ['policy-history', projectId] as const,
}

/** The expected versions a manager write is based on, read from the evidence. */
export function expectedVersions(versions: EvidenceVersions): ExpectedVersions {
  return {
    expected_evidence_generation: versions.evidence_generation,
    expected_configuration_fingerprint: versions.configuration_fingerprint,
    expected_resolution_version: versions.resolution_version,
  }
}

export function listResolutionQueue(
  projectId: string,
  batchId: string,
  filters: ResolutionQueueFilters,
  token: string,
  cursor?: string,
) {
  const query = new URLSearchParams()
  for (const state of filters.state ?? []) query.append('state', state)
  if (filters.reason) query.set('reason', filters.reason)
  if (filters.classStrategy) query.set('class_strategy', filters.classStrategy)
  if (filters.minAgeSeconds !== undefined) query.set('min_age_seconds', String(filters.minAgeSeconds))
  if (cursor) query.set('cursor', cursor)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiRequest<ResolutionQueuePage>(
    `/api/v1/projects/${projectId}/batches/${batchId}/resolutions${suffix}`,
    { token },
  )
}

export async function getImageEvidence(projectId: string, batchItemId: string, token: string) {
  const evidence = await apiRequest<ImageEvidence>(
    `/api/v1/projects/${projectId}/batch-items/${batchItemId}/evidence`,
    { token },
  )
  return { ...evidence, media: { ...evidence.media, image_url: `${config.apiBaseUrl}${evidence.media.image_url}` } }
}

export async function retryResolution(projectId: string, batchItemId: string, body: RetryRequest, token: string) {
  return apiRequest<RunView>(`/api/v1/projects/${projectId}/batch-items/${batchItemId}/resolve`, {
    method: 'POST', token,
    headers: { 'Idempotency-Key': await requestKey(`resolve:${batchItemId}`, body) },
    body,
  })
}

export async function cancelRun(projectId: string, runId: string, rationale: string, token: string) {
  const body = { rationale }
  return apiRequest<RunView>(`/api/v1/projects/${projectId}/resolution-runs/${runId}/cancel`, {
    method: 'POST', token,
    headers: { 'Idempotency-Key': await requestKey(`cancel:${runId}`, body) },
    body,
  })
}

export async function adjudicate(projectId: string, workItemId: string, body: AdjudicationRequest, token: string) {
  return apiRequest<AdjudicationResponse>(
    `/api/v1/projects/${projectId}/resolution-work-items/${workItemId}/adjudicate`,
    {
      method: 'POST', token,
      headers: { 'Idempotency-Key': await requestKey(`adjudicate:${workItemId}`, body) },
      body,
    },
  )
}

/** Acquires the edit lease, or renews it when the caller already holds it. */
export function acquireLease(projectId: string, workItemId: string, token: string) {
  return apiRequest<LeaseView>(`/api/v1/projects/${projectId}/resolution-work-items/${workItemId}/lease`, {
    method: 'POST', token,
  })
}

export function releaseLease(projectId: string, workItemId: string, token: string) {
  return apiRequest<void>(`/api/v1/projects/${projectId}/resolution-work-items/${workItemId}/lease`, {
    method: 'DELETE', token,
  })
}

export function revokeLease(projectId: string, workItemId: string, reason: string, token: string) {
  return apiRequest<void>(`/api/v1/projects/${projectId}/resolution-work-items/${workItemId}/lease/revoke`, {
    method: 'POST', token, body: { reason },
  })
}

export function getAnnotatorPerformance(projectId: string, token: string) {
  return apiRequest<PerformanceReport>(`/api/v1/projects/${projectId}/annotator-performance`, { token })
}

export function getResolverEligibility(projectId: string, token: string) {
  return apiRequest<ResolverEligibility>(`/api/v1/projects/${projectId}/resolver-eligibility`, { token })
}

export function getPolicyHistory(projectId: string, token: string) {
  return apiRequest<PolicyHistory>(`/api/v1/projects/${projectId}/annotation-policy/history`, { token })
}
