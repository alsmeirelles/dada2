import { apiRequest } from '../../api/client'
import { requestKey } from '../../api/idempotency'
import { config } from '../../config/env'
import type { Page, Project, ProjectClassInput } from '../projects/types'
import type {
  AnnotationObject,
  AssignmentDetail,
  AssignmentQueue,
  AssignmentQueueItem,
  DraftSaved,
  EventTicket,
  IterationList,
  ProjectStatistics,
  SamPrediction,
  SamPrompt,
  SubmissionReceived,
  WorkspaceBootstrap,
} from './types'

type AssignmentPage = Page<AssignmentQueueItem> & Pick<AssignmentQueue, 'counts'>

export async function getWorkspaceBootstrap(projectId: string, token: string): Promise<WorkspaceBootstrap> {
  const [project, classes] = await Promise.all([
    apiRequest<Project>(`/api/v1/projects/${projectId}`, { token }),
    apiRequest<Page<ProjectClassInput>>(`/api/v1/projects/${projectId}/classes`, { token }),
  ])
  return { project, classes: classes.items }
}

export async function listAssignments(projectId: string, token: string): Promise<AssignmentQueue> {
  const items: AssignmentQueueItem[] = []
  let page: AssignmentPage | null = null
  do {
    const query: string = page?.next_cursor ? `?cursor=${encodeURIComponent(page.next_cursor)}` : ''
    page = await apiRequest<AssignmentPage>(`/api/v1/projects/${projectId}/assignments${query}`, { token })
    items.push(...page.items)
  } while (page.next_cursor)
  return { items, counts: page.counts }
}

export async function getAssignment(projectId: string, assignmentId: string, token: string) {
  const detail = await apiRequest<AssignmentDetail>(
    `/api/v1/projects/${projectId}/assignments/${assignmentId}`,
    { token },
  )
  return { ...detail, media: { ...detail.media, image_url: `${config.apiBaseUrl}${detail.media.image_url}` } }
}

export function saveDraft(
  projectId: string,
  assignmentId: string,
  version: number,
  objects: AnnotationObject[],
  token: string,
) {
  return apiRequest<DraftSaved>(`/api/v1/projects/${projectId}/assignments/${assignmentId}/draft`, {
    method: 'PUT', token, body: { version, objects },
  })
}

export async function submitAssignment(
  projectId: string,
  assignmentId: string,
  version: number,
  objects: AnnotationObject[],
  token: string,
) {
  const body = { version, objects }
  return apiRequest<SubmissionReceived>(`/api/v1/projects/${projectId}/assignments/${assignmentId}/submit`, {
    method: 'POST', token,
    headers: { 'Idempotency-Key': await submissionKey(assignmentId, body) },
    body,
  })
}

/**
 * The same document at the same version replays the original result after a
 * lost response; a corrected document is a new request (I6-02).
 */
export function submissionKey(assignmentId: string, body: { version: number; objects: AnnotationObject[] }) {
  return requestKey(`submit:${assignmentId}`, body)
}

export function predictSegmentation(
  projectId: string,
  assignment: AssignmentDetail,
  prompts: SamPrompt[],
  token: string,
) {
  return apiRequest<SamPrediction>('/api/v1/inference/sam-predict', {
    method: 'POST', token,
    body: {
      project_id: projectId,
      assignment_id: assignment.id,
      image_id: assignment.media.id,
      prompts,
    },
  })
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
