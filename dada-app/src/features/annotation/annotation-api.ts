import { apiRequest } from '../../api/client'
import type { Page, Project, ProjectClassInput } from '../projects/types'
import type {
  AnnotationDocument,
  AnnotationQueue,
  EventTicket,
  IterationList,
  Lease,
  ProjectStatistics,
  SamPrediction,
  SamPrompt,
  WorkspaceBootstrap,
} from './types'

export async function getWorkspaceBootstrap(projectId: string, token: string): Promise<WorkspaceBootstrap> {
  const [project, classes, iterations] = await Promise.all([
    apiRequest<Project>(`/api/v1/projects/${projectId}`, { token }),
    apiRequest<Page<ProjectClassInput>>(`/api/v1/projects/${projectId}/classes`, { token }),
    apiRequest<IterationList>(`/api/v1/projects/${projectId}/iterations`, { token }),
  ])
  return { project, classes: classes.items, iteration: iterations.current_iteration }
}

export function getQueue(projectId: string, iterationId: string, token: string) {
  return apiRequest<AnnotationQueue>(
    `/api/v1/projects/${projectId}/iterations/${iterationId}/queue`,
    { token },
  )
}

export function acquireLease(
  projectId: string,
  iterationId: string,
  assignmentId: string | null,
  token: string,
) {
  return apiRequest<Lease>(
    `/api/v1/projects/${projectId}/iterations/${iterationId}/leases`,
    {
      method: 'POST', token,
      body: assignmentId ? { assignment_id: assignmentId } : { selection: 'next' },
    },
  )
}

export function renewLease(leaseId: string, token: string) {
  return apiRequest<Pick<Lease, 'expires_at' | 'renew_after'>>(
    `/api/v1/leases/${leaseId}/renew`,
    { method: 'POST', token, body: {} },
  )
}

export function releaseLease(leaseId: string, token: string) {
  return apiRequest<void>(`/api/v1/leases/${leaseId}`, { method: 'DELETE', token })
}

export function saveAnnotationDraft(leaseId: string, document: AnnotationDocument, token: string) {
  return apiRequest<AnnotationDocument>(`/api/v1/leases/${leaseId}/annotations`, {
    method: 'PUT', token, body: document,
  })
}

export function completeAnnotation(leaseId: string, document: AnnotationDocument, token: string) {
  return apiRequest<AnnotationDocument>(`/api/v1/leases/${leaseId}/complete`, {
    method: 'POST', token,
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: document,
  })
}

export function predictSegmentation(
  projectId: string,
  lease: Lease,
  prompts: SamPrompt[],
  token: string,
) {
  return apiRequest<SamPrediction>('/api/v1/inference/sam-predict', {
    method: 'POST', token,
    body: {
      project_id: projectId,
      lease_id: lease.lease_id,
      image_id: lease.media.id,
      prompts,
    },
  })
}

export function closeIteration(projectId: string, iterationId: string, token: string) {
  return apiRequest<IterationList['current_iteration']>(
    `/api/v1/projects/${projectId}/iterations/${iterationId}/close`,
    {
      method: 'POST', token,
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: {},
    },
  )
}

export async function getProjectActivity(projectId: string, token: string) {
  const [project, iterations, statistics] = await Promise.all([
    apiRequest<Project>(`/api/v1/projects/${projectId}`, { token }),
    apiRequest<IterationList>(`/api/v1/projects/${projectId}/iterations`, { token }),
    apiRequest<ProjectStatistics>(`/api/v1/projects/${projectId}/statistics`, { token }),
  ])
  return { project, iterations, statistics }
}

export function createEventTicket(projectId: string, token: string) {
  return apiRequest<EventTicket>(`/api/v1/projects/${projectId}/events/ticket`, {
    method: 'POST', token, body: {},
  })
}
