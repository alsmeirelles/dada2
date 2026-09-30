import type { BatchPurpose, Project, ProjectClassInput, TaskType } from '../projects/types'

export type IterationStatus = 'preparing' | 'annotating' | 'consolidating' | 'closing' | 'training' | 'ready' | 'failed'

export type Iteration = {
  id: string
  number: number
  status: IterationStatus
  available_count: number
  leased_count: number
  completed_count: number
  total_count: number
  submitted_assignment_count?: number
  total_assignment_count?: number
  resolved_count?: number
  review_required_count?: number
  training_progress?: number | null
  eta_seconds?: number | null
  started_at?: string | null
  completed_at?: string | null
  metrics?: Record<string, number>
}

export type IterationList = {
  items: Iteration[]
  current_iteration: Iteration | null
  next_cursor: string | null
}

export type AssignmentStatus = 'pending' | 'in_progress' | 'submitted' | 'reassigned' | 'cancelled'
export type QueueState = 'pending' | 'in_progress' | 'submitted'

/** One of the caller's own assignments. It never carries peer information. */
export type AssignmentQueueItem = {
  id: string
  batch_id: string
  batch_purpose: BatchPurpose
  media_id: string
  relative_path: string
  width: number
  height: number
  status: AssignmentStatus
  version: number
  seeded_from_import: boolean
  updated_at: string
}

export type AssignmentQueue = {
  items: AssignmentQueueItem[]
  counts: Record<QueueState, number>
}

export type AssignmentMedia = {
  id: string
  relative_path: string
  width: number
  height: number
  image_url: string
}

export type AssignmentDetail = {
  id: string
  project_id: string
  batch_id: string
  batch_purpose: BatchPurpose
  task_type: TaskType
  status: AssignmentStatus
  version: number
  media: AssignmentMedia
  objects: AnnotationObject[]
  seeded_from_import: boolean
  draft_saved_at: string | null
  revision: number | null
  submitted_at: string | null
}

export type DraftSaved = {
  id: string
  status: AssignmentStatus
  version: number
  draft_saved_at: string
}

export type SubmissionReceived = {
  id: string
  status: AssignmentStatus
  version: number
  submission_id: string
  revision: number
  submitted_at: string
  image_resolved: boolean
}

/** A manager's view of one assignment, without its document content. */
export type BatchAssignment = {
  id: string
  batch_item_id: string
  item_status: string
  media_id: string
  relative_path: string
  annotator_id: string
  status: AssignmentStatus
  version: number
  updated_at: string
}

export type RectangleGeometry = {
  type: 'rectangle'
  coordinates: [number, number, number, number]
}

export type PolygonGeometry = {
  type: 'polygon'
  coordinates: number[][]
}

export type AnnotationObject = {
  id: string
  class_id: string
  geometry: RectangleGeometry | PolygonGeometry | null
  attributes: Record<string, unknown>
}

export type AnnotationDocument = {
  media_id: string
  task_type: TaskType
  version: number
  objects: AnnotationObject[]
}

export type AnnotationTool = 'select' | 'pan' | 'box' | 'polygon' | 'sam-point'

export type SamPrompt = {
  type: 'point' | 'box'
  coordinates: number[]
  label?: string
}

export type SamPrediction = {
  image_id: string
  polygons: Array<{ coordinates: number[][] } | number[][]>
  embedding_cache_key?: string | null
}

export type WorkspaceBootstrap = {
  project: Project
  classes: ProjectClassInput[]
}

export type ProjectStatistics = {
  iterations: Array<{
    iteration_id: string
    iteration_number: number
    annotated_images: number
    metrics: Record<string, number>
    completed_at?: string | null
  }>
  totals: {
    images: number
    annotated_images: number
    iterations_completed: number
  }
}

export type ProjectEventType =
  | 'upload.progress'
  | 'upload.completed'
  | 'lease.acquired'
  | 'lease.released'
  | 'annotation.completed'
  | 'iteration.status_changed'
  | 'training.progress'
  | 'training.eta_updated'
  | 'assignment.leased'
  | 'assignment.released'
  | 'annotation.submitted'
  | 'resolution.started'
  | 'resolution.completed'
  | 'resolution.review_required'
  | 'resolution.adjudicated'

export type ProjectEvent = {
  sequence: number
  type: ProjectEventType
  project_id: string
  occurred_at: string
  data: Record<string, unknown>
}

export type EventTicket = {
  ticket: string
  websocket_url?: string
  expires_at: string
}
