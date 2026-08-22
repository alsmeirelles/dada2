export type TaskType = 'classification' | 'detection' | 'segmentation'
export type ProjectStatus =
  | 'draft'
  | 'ingesting'
  | 'ready'
  | 'active'
  | 'training'
  | 'completed'
  | 'failed'

export type Project = {
  id: string
  name: string
  description: string | null
  task_type: TaskType
  status: ProjectStatus
  owner_id: string
  initial_training_size: number
  test_set_size: number
  iteration_batch_size: number
  version: number
  created_at: string
  updated_at: string
  media_count?: number
  completed_annotations?: number
  resolved_images?: number
  review_required_count?: number
}

export type AnnotationMode = 'single' | 'consensus'

export type AnnotationPolicyDraft =
  | { mode: 'single' }
  | {
      mode: 'consensus'
      annotatorUsernames: string[]
      resolver: 'majority_vote' | 'weighted_box_fusion' | 'staple'
      reviewThreshold: number
    }

export type AnnotationPolicy = {
  mode: AnnotationMode
  version: number
  annotator_ids: string[]
  resolver?: string | null
  resolver_version?: string | null
  parameters?: Record<string, number | string | boolean>
  review_thresholds?: Record<string, number>
}

export type ProjectClassInput = {
  id: string
  name: string
  color: string
}

export type ProjectDraft = {
  name: string
  description: string
  taskType: TaskType
  classes: ProjectClassInput[]
  initialTrainingSize: number
  testSetSize: number
  iterationBatchSize: number
  collaborators: string[]
  annotationPolicy: AnnotationPolicyDraft
}

export type Page<T> = { items: T[]; next_cursor: string | null }
