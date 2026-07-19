import type { Project, ProjectClassInput, TaskType } from '../projects/types'

export type IterationStatus = 'preparing' | 'annotating' | 'closing' | 'training' | 'ready' | 'failed'

export type Iteration = {
  id: string
  number: number
  status: IterationStatus
  available_count: number
  leased_count: number
  completed_count: number
  total_count: number
}

export type IterationList = {
  items: Iteration[]
  current_iteration: Iteration | null
  next_cursor: string | null
}

export type QueueItemStatus = 'available' | 'leased' | 'completed'

export type QueueItem = {
  media_id: string
  relative_path: string
  thumbnail_url?: string
  status: QueueItemStatus
  width: number
  height: number
  leased_by?: { id: string; display_name: string }
}

export type AnnotationQueue = {
  items: QueueItem[]
  available_count: number
  leased_count: number
  completed_count: number
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

export type Lease = {
  lease_id: string
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
