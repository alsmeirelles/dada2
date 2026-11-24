import { apiDownload, apiRequest } from '../../api/client'
import { requestKey } from '../../api/idempotency'
import { config } from '../../config/env'
import type { Page, Project, ProjectClassInput } from '../projects/types'
import type {
  AnnotationObject,
  AssignmentQueue,
  AssignmentDetail,
  AssignmentQueueItem,
  AssistPrompt,
  AssistResult,
  DraftSaved,
  EventTicket,
  ExportFormat,
  Iteration,
  IterationList,
  ProjectStatistics,
  QualityReport,
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

/** Asks the project's latest target model for a suggestion on the caller's open assignment (D18). */
export function requestAssistance(
  projectId: string,
  assignmentId: string,
  requestId: string,
  prompt: AssistPrompt,
  token: string,
) {
  return apiRequest<AssistResult>('/api/v1/inference/sam-predict', {
    method: 'POST', token,
    body: { project_id: projectId, assignment_id: assignmentId, request_id: requestId, prompts: [prompt] },
  })
}

/** Every iteration, oldest first, and the current one. */
export async function listIterations(projectId: string, token: string): Promise<IterationList> {
  const items: Iteration[] = []
  let page: IterationList | null = null
  do {
    const query: string = page?.next_cursor ? `?cursor=${encodeURIComponent(page.next_cursor)}` : ''
    page = await apiRequest<IterationList>(`/api/v1/projects/${projectId}/iterations${query}`, { token })
    items.push(...page.items)
  } while (page.next_cursor)
  return { items, current_iteration: page.current_iteration, next_cursor: null }
}

export async function getProjectActivity(projectId: string, token: string) {
  const [project, iterations, statistics] = await Promise.all([
    apiRequest<Project>(`/api/v1/projects/${projectId}`, { token }),
    listIterations(projectId, token),
    apiRequest<ProjectStatistics>(`/api/v1/projects/${projectId}/statistics`, { token }),
  ])
  return { project, iterations, statistics }
}

/** Queues a new attempt of a failed iteration over the same snapshots. */
export function retryIteration(projectId: string, iterationId: string, token: string) {
  return apiRequest<Iteration>(`/api/v1/projects/${projectId}/iterations/${iterationId}/retry`, { method: 'POST', token })
}

export function getQuality(projectId: string, token: string) {
  return apiRequest<QualityReport>(`/api/v1/projects/${projectId}/quality`, { token })
}

/** Downloads the annotated dataset as a ZIP archive and saves it in the browser. */
export async function downloadDataset(projectId: string, format: ExportFormat, token: string) {
  const { blob, name } = await apiDownload(`/api/v1/projects/${projectId}/export?format=${format}`, { token })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

export function createEventTicket(projectId: string, token: string) {
  return apiRequest<EventTicket>(`/api/v1/projects/${projectId}/events/ticket`, {
    method: 'POST', token, body: {},
  })
}
