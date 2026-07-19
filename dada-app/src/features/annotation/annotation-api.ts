import { apiRequest } from '../../api/client'
import type { Page, Project, ProjectClassInput } from '../projects/types'
import type {
  AnnotationDocument,
  AnnotationQueue,
  IterationList,
  Lease,
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
  mediaId: string | null,
  token: string,
) {
  return apiRequest<Lease>(
    `/api/v1/projects/${projectId}/iterations/${iterationId}/leases`,
    {
      method: 'POST', token,
      body: mediaId ? { media_id: mediaId } : { selection: 'next' },
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
