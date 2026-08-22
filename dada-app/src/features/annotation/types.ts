import type { Project, ProjectClassInput, TaskType } from '../projects/types'

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

export type QueueItemStatus = 'available' | 'leased' | 'submitted' | 'completed'

export type QueueItem = {
  assignment_id?: string
  media_id: string
  relative_path: string
  thumbnail_url?: string
  status: QueueItemStatus
  width: number
  height: number
  /** Present only for legacy, single-image queues. Consensus queues stay blind. */
  leased_by?: { id: string; display_name: string }
}

export type AnnotationQueue = {
  items: QueueItem[]
  available_count: number
  leased_count: number
  completed_count: number
  submitted_count?: number
  resolved_count?: number
  review_required_count?: number
  total_count?: number
  next_cursor: string | null
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

export type Lease = {
  lease_id: string
  assignment_id?: string
  expires_at: string
  renew_after: number
  media: {
    id: string
    image_url: string
    relative_path: string
    width: number
    height: number
  }
  annotation: AnnotationDocument
}

export type WorkspaceBootstrap = {
  project: Project
  classes: ProjectClassInput[]
  iteration: Iteration | null
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
