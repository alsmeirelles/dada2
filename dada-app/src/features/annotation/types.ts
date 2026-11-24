import type { EvaluationMetric } from '../../api/capabilities'
import type {
  AcquisitionStrategy,
  BatchPurpose,
  CompletionReason,
  Project,
  ProjectClassInput,
  TaskType,
} from '../projects/types'

/**
 * Iteration n is run n plus batch n (D6): `training` while the run is queued or
 * working, then the batch's state; `ready` once its images are resolved.
 */
export type IterationStatus = 'training' | 'preparing' | 'annotating' | 'consolidating' | 'ready' | 'failed'
export type IterationStage = 'training' | 'evaluating' | 'selecting'

/** One target-model evaluation, on validation during the loop and on test at its end. */
export type Evaluation = {
  iteration: number
  split: 'validation' | 'test'
  metric: EvaluationMetric
  value: number
  metrics: Record<string, number>
  model: Record<string, unknown>
  created_at: string
}

export type Iteration = {
  id: string
  number: number
  purpose: 'selection' | 'final_evaluation'
  status: IterationStatus
  stage: IterationStage | null
  strategy: AcquisitionStrategy
  attempt: number
  solution: string | null
  solution_version: string | null
  batch_id: string | null
  requested_size: number
  selected_count: number | null
  shortfall_reason: string | null
  stop_reason: 'metric_target' | null
  failure_code: string | null
  failure_detail: string | null
  total_count: number
  resolved_count: number
  review_required_count: number
  available_count: number
  total_assignment_count: number
  submitted_assignment_count: number
  /** Always null in Phase 7; shown only when the API provides it. */
  eta_seconds: number | null
  metrics: Record<string, number>
  evaluations: Evaluation[]
  started_at: string
  completed_at: string | null
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
  target?: AssignmentTarget | null
}

/**
 * The object target an assignment answers (D16): the solution's proposed box or
 * polygon and the context region around it, in canonical image pixels. It is a
 * cue, never an annotation or a vote; the document holds at most that one
 * object, and an empty document means there is none.
 */
export type AssignmentTarget = {
  geometry: RectangleGeometry | PolygonGeometry
  region: [number, number, number, number]
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
  /** Present only once the image is resolved; it never names peers or carries votes. */
  resolution: FinalResolution | null
  target?: AssignmentTarget | null
}

export type ResolutionSource = 'single_submission' | 'automatic_consensus' | 'expert_adjudication'

/** The image's accepted canonical annotation as its annotators may see it. */
export type FinalResolution = {
  version: number
  source: ResolutionSource
  objects: AnnotationObject[]
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

export type AnnotationTool = 'select' | 'pan' | 'box' | 'polygon' | 'assist'

/** A point `[x, y]` or a box `[x, y, width, height]` in canonical image pixels. */
export type AssistPrompt = {
  type: 'point' | 'box'
  coordinates: number[]
}

/**
 * The model's answer to one prompt (A7-03): a box for detection, a polygon for
 * segmentation, or `no_suggestion`. Nothing is saved until the annotator
 * accepts it into the draft.
 */
export type AssistResult = {
  request_id: string
  assignment_id: string
  status: 'suggestion' | 'no_suggestion'
  geometry: RectangleGeometry | PolygonGeometry | null
  score: number | null
  model: Record<string, unknown>
}

export type WorkspaceBootstrap = {
  project: Project
  classes: ProjectClassInput[]
}

export type ProjectStatistics = {
  project_id: string
  acquisition_strategy: AcquisitionStrategy
  max_acquisition_iterations: number | null
  completed_iterations: number
  completion_reason: CompletionReason | null
  evaluation_metric: EvaluationMetric | null
  metric_target: number | null
  evaluations: Evaluation[]
}

export type AgreementMetric = 'winner_support' | 'box_iou' | 'mask_iou' | 'mask_dice'

/**
 * Project-level quality for owners and managers (D20). Every rate and median
 * is null until `minimum_decisions` items are resolved, and a median backed by
 * fewer than `minimum_cell` candidates is null too. It never names anyone.
 */
export type QualityReport = {
  task_type: TaskType
  total_items: number
  resolved_items: number
  minimum_decisions: number
  minimum_cell: number
  suppressed: boolean
  review_rate: number | null
  resolution_rate: number | null
  agreement: Array<{ metric: AgreementMetric; observations: number; median: number | null }>
}

export type ExportFormat = 'coco' | 'yolo' | 'csv'

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
