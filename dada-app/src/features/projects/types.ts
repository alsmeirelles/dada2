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
  test_set_size: number | null
  test_set_percentage: number | null
  validation_set_size: number | null
  validation_set_percentage: number | null
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
      resolver: string
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

export type ProjectClass = ProjectClassInput & {
  version: number
  display_order: number
}

export type ProjectDraft = {
  name: string
  description: string
  taskType: TaskType
  classes: ProjectClassInput[]
  initialTrainingSize: number
  testSetSize: number
  testSetUnit: SplitSizeUnit
  validationSetSize: number
  validationSetUnit: SplitSizeUnit
  iterationBatchSize: number
  collaborators: string[]
  annotationPolicy: AnnotationPolicyDraft
}

export type SplitSizeUnit = 'count' | 'percentage'

export type BatchPurpose = 'initial_training' | 'validation' | 'test' | 'acquisition'
export type BatchStatus =
  | 'preparing'
  | 'annotating'
  | 'resolving'
  | 'review_required'
  | 'resolved'
  | 'closed'
  | 'failed'

export type AnnotationBatch = {
  id: string
  project_id: string
  purpose: BatchPurpose
  status: BatchStatus
  mode: AnnotationMode
  annotator_ids: string[]
  resolver: string | null
  resolver_version: string | null
  parameters: Record<string, number | string | boolean>
  review_thresholds: Record<string, number>
  source_policy_version: number
  selection_strategy: string
  selection_seed: number
  selection_input_fingerprint: string
  requested_size: number
  total_items: number
  total_assignments: number
  submitted_assignments: number
  started_at: string | null
  created_at: string
  updated_at: string
}

export type Page<T> = { items: T[]; next_cursor: string | null }
