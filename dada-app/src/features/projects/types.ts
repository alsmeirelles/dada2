import type { EvaluationMetric } from '../../api/capabilities'
import type { ResolverConfiguration } from './resolver-config'

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
  acquisition_strategy: AcquisitionStrategy
  dataset_layout: DatasetLayout
  initial_training_size: number | null
  test_set_size: number | null
  test_set_percentage: number | null
  validation_set_size: number | null
  validation_set_percentage: number | null
  iteration_batch_size: number | null
  max_acquisition_iterations: number | null
  learning_solution: string | null
  learning_solution_version: string | null
  learning_configuration: ResolverSettings
  evaluation_metric: EvaluationMetric | null
  evaluation_interval: number | null
  metric_target: number | null
  completion_reason: CompletionReason | null
  dataset_prepared_at: string | null
  version: number
  created_at: string
  updated_at: string
  media_count?: number
}

export type AcquisitionStrategy = 'random' | 'active_learning'
export type CompletionReason = 'max_iterations' | 'metric_target' | 'pool_exhausted'

/**
 * The active-learning choices of a project: the solution, its configuration,
 * the target-model metric, how many acquisitions pass between evaluations, and
 * an optional target that stops the loop once reached.
 */
export type LearningDraft = {
  solution: string
  configuration: ResolverSettings
  metric: EvaluationMetric
  interval: number
  target: number | null
}
/** `single_batch` annotates every image once and never trains or acquires. */
export type DatasetLayout = 'split' | 'single_batch'

export type AnnotationMode = 'single' | 'consensus'

export type AnnotationPolicyDraft =
  | { mode: 'single' }
  | {
      mode: 'consensus'
      annotatorUsernames: string[]
      requiredAnnotations: number
      requiredReviewers: number
      /** The task's pipeline ID; empty until the capabilities have loaded. */
      resolver: string
      configuration: ResolverConfiguration
      requireIndependentAdjudicator: boolean
    }

/**
 * `parameters` and `review_thresholds` are the pipeline's closed, typed
 * configuration; `/capabilities` describes every field. The API fills omitted
 * values with their defaults.
 */
export type AnnotationPolicy = {
  mode: AnnotationMode
  version: number
  annotator_ids: string[]
  required_consensus_annotations: number | null
  required_consensus_reviewers: number | null
  resolver?: string | null
  resolver_version?: string | null
  parameters?: ResolverSettings
  review_thresholds?: ResolverSettings
  require_independent_adjudicator?: boolean
}

export type ResolverSettings = Record<string, unknown>

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
  /** Decides how later training batches are chosen; `single_batch` is random only. */
  acquisitionStrategy: AcquisitionStrategy
  datasetLayout: DatasetLayout
  /** Null means the first training batch uses `iterationBatchSize`. */
  initialTrainingSize: number | null
  testSetSize: number
  testSetUnit: SplitSizeUnit
  validationSetSize: number
  validationSetUnit: SplitSizeUnit
  iterationBatchSize: number
  /** Acquisition iterations before the loop stops; required for `split`. */
  maxAcquisitionIterations: number
  /** Null until the active-learning catalog is known, and for random acquisition. */
  learning: LearningDraft | null
  collaborators: string[]
  annotationPolicy: AnnotationPolicyDraft
}

export type SplitSizeUnit = 'count' | 'percentage'

export type BatchPurpose =
  | 'initial_annotation'
  | 'initial_training'
  | 'validation'
  | 'test'
  | 'acquisition'
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
  required_consensus_annotations: number | null
  required_consensus_reviewers: number | null
  resolver: string | null
  resolver_version: string | null
  parameters: ResolverSettings
  review_thresholds: ResolverSettings
  require_independent_adjudicator: boolean
  source_policy_version: number
  selection_strategy: string
  selection_seed: number
  selection_input_fingerprint: string
  requested_size: number
  total_items: number
  resolved_items: number
  awaiting_resolution_items: number
  resolving_items: number
  in_review_items: number
  review_required_items: number
  cancelled_items: number
  total_assignments: number
  available_assignments: number
  in_progress_assignments: number
  submitted_assignments: number
  started_at: string | null
  created_at: string
  updated_at: string
}

export type DatasetLayoutSummary = {
  dataset_layout: DatasetLayout
  prepared_at: string | null
  train_size: number
  validation_size: number
  test_size: number
  first_training_batch_size: number | null
  training_pool_size: number
  batch_ids: string[]
  annotation_import_id: string | null
}

export type ImportFormat = 'yolo_detection' | 'coco_segmentation'
export type ImportStatus = 'uploading' | 'validated' | 'rejected' | 'accepted'

export type AnnotationImport = {
  id: string
  project_id: string
  format: ImportFormat
  parser_version: string
  status: ImportStatus
  created_by: string
  report: {
    labelled_images: number
    objects: number
    unlabelled_images: number
    errors: { code: string; client_file_id: string; detail: string }[]
  } | null
  files: {
    client_file_id: string
    relative_path: string
    size_bytes: number
    sha256: string
    received: boolean
  }[]
  created_at: string
  validated_at: string | null
  accepted_at: string | null
}

export type Page<T> = { items: T[]; next_cursor: string | null }
