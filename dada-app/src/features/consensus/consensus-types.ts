import type { AnnotationObject, AssignmentMedia, ResolutionSource } from '../annotation/types'
import type { BatchPurpose, ResolverSettings, TaskType } from '../projects/types'

export type WorkItemStatus = 'pending_review' | 'review_ready' | 'review_required' | 'resolved' | 'cancelled'
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'review_required' | 'failed' | 'cancelled'
export type AdjudicationAction = 'accept_proposal' | 'edit_proposal' | 'edit_submission' | 'replace'

/** The closed review vocabulary of A6-01. */
export type ReviewReason =
  | 'class_tie'
  | 'support_below_threshold'
  | 'posterior_below_threshold'
  | 'ambiguous_match'
  | 'geometry_below_threshold'
  | 'topology_invalid'
  | 'resolver_unavailable'
  | 'resolver_output_invalid'
  | 'worker_failed'
  | 'expert_required'

/** One open case in a batch's manager queue; it carries no evidence documents. */
export type ResolutionQueueItem = {
  work_item_id: string
  batch_item_id: string
  media_id: string
  relative_path: string
  scope: 'image' | 'candidate'
  candidate_key: string
  status: WorkItemStatus
  reason: ReviewReason | null
  submissions: number
  reviews_submitted: number
  reviews_required: number
  resolver: string | null
  resolver_version: string | null
  class_strategy: string | null
  metrics: Record<string, unknown>
  lease_holder_id: string | null
  lease_expires_at: string | null
  created_at: string
}

export type ResolutionQueuePage = { items: ResolutionQueueItem[]; next_cursor: string | null }

export type ResolutionQueueFilters = {
  state?: WorkItemStatus[]
  reason?: ReviewReason
  classStrategy?: string
  minAgeSeconds?: number
}

/** What every manager write sends back; a mismatch is a `409`. */
export type ExpectedVersions = {
  expected_evidence_generation: number
  expected_configuration_fingerprint: string | null
  expected_resolution_version: number
}

export type EvidenceVersions = {
  evidence_generation: number
  configuration_fingerprint: string | null
  resolution_version: number
}

/** One pipeline decision for an image-level or object-level case. */
export type CandidateDecision = {
  key: string
  ordinal: number
  scope: 'image' | 'candidate'
  passed: boolean
  reasons: ReviewReason[]
  objects: AnnotationObject[]
  /** `[x, y, width, height]` in original-image pixels. */
  region: [number, number, number, number] | null
  members: { source_id: string; object_id: string; annotator_index: number; class_id: string | null }[]
  metrics: Record<string, unknown>
}

export type ProposalView = {
  id: string
  outcome: string
  objects: AnnotationObject[]
  candidates: CandidateDecision[]
  diagnostics: Record<string, unknown>
  content_hash: string
  created_at: string
}

export type RunView = {
  id: string
  sequence: number
  trigger: string
  status: RunStatus
  pipeline: string
  pipeline_version: string
  configuration: { parameters: ResolverSettings; review_thresholds: ResolverSettings } & Record<string, unknown>
  configuration_fingerprint: string
  input_fingerprint: string
  dependency_versions: Record<string, unknown>
  attempt: number
  failure_code: string | null
  failure_detail: string | null
  requested_by: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  proposal: ProposalView | null
}

export type ResolutionView = {
  id: string
  version: number
  source: ResolutionSource
  objects: AnnotationObject[]
  content_hash: string
  accepted_by: string | null
  run_id: string | null
  created_at: string
  superseded_at: string | null
}

/** One immutable annotator submission, named for owners and managers only. */
export type SubmissionEvidence = {
  id: string
  assignment_id: string
  annotator_id: string
  annotator_name: string
  revision: number
  content_hash: string
  objects: AnnotationObject[]
  submitted_at: string
  current_generation: boolean
}

export type ReviewEvidence = {
  id: string
  work_item_id: string
  candidate_key: string
  reviewer_id: string
  reviewer_name: string
  evidence: Record<string, unknown>
  content_hash: string
  submitted_at: string
}

export type LeaseView = {
  work_item_id: string
  holder_id: string
  acquired_at: string
  renewed_at: string
  /** Fifteen minutes after the last renewal. */
  expires_at: string
  /** Two hours after acquisition; a lease never outlives it. */
  cap_at: string
}

export type AdjudicationView = {
  id: string
  work_item_id: string
  action: AdjudicationAction
  actor_id: string
  actor_role: string
  objects: AnnotationObject[]
  rationale: string | null
  contributor_conflict: boolean
  resolved_annotation_id: string | null
  created_at: string
}

export type WorkItemView = {
  id: string
  candidate_key: string
  candidate_ordinal: number
  scope: 'image' | 'candidate'
  status: WorkItemStatus
  reason: ReviewReason | null
  candidate_context: { region?: [number, number, number, number] }
  run_id: string | null
  reviews_submitted: number
  reviews_required: number
  lease: LeaseView | null
  adjudications: AdjudicationView[]
  created_at: string
  closed_at: string | null
}

/** Everything an owner or manager needs to review one image. */
export type ImageEvidence = {
  batch_item_id: string
  batch_id: string
  purpose: BatchPurpose
  status: string
  task_type: TaskType
  media: AssignmentMedia
  versions: EvidenceVersions
  require_independent_adjudicator: boolean
  contributors: string[]
  submissions: SubmissionEvidence[]
  reviews: ReviewEvidence[]
  runs: RunView[]
  /** Every version, oldest first. */
  resolutions: ResolutionView[]
  work_items: WorkItemView[]
}

export type RetryRequest = ExpectedVersions & {
  rationale: string
  configuration?: { parameters: ResolverSettings; review_thresholds: ResolverSettings }
}

export type AdjudicationRequest = ExpectedVersions & {
  action: AdjudicationAction
  objects?: AnnotationObject[]
  source_submission_id?: string
  rationale?: string
}

export type AdjudicationResponse = { adjudication: AdjudicationView; resolution: ResolutionView | null }

export type PerformanceSummary = {
  annotator_id: string
  annotator_name: string
  evaluation_source: 'automated_consensus' | 'human_adjudication'
  task_type: TaskType
  decisions: number
  suppressed: boolean
  outcomes: Record<string, number | null> | null
  metrics: Record<string, number | null> | null
  classes: Record<string, number | null> | null
}

export type PerformanceReport = { items: PerformanceSummary[]; minimum_decisions: number; minimum_cell: number }

export type StrategyEligibility = {
  strategy: 'reliability_weighted_vote' | 'dawid_skene'
  eligible: boolean
  missing: { requirement: string; [detail: string]: unknown }[]
  report: Record<string, unknown>
}

export type ResolverEligibility = { strategies: StrategyEligibility[] }

export type PolicyChange = {
  version: number
  actor_id: string | null
  actor_name: string | null
  changed_at: string
  resolver: string | null
  resolver_version: string | null
  changed_fields: Record<string, { before: unknown; after: unknown }>
}

export type PolicyHistory = { items: PolicyChange[]; preparing_batches: number }
