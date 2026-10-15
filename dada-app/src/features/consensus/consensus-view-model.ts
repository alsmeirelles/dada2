import type { AnnotationObject, ResolutionSource } from '../annotation/types'
import type { AnnotationBatch, BatchPurpose, ProjectClassInput, TaskType } from '../projects/types'
import { ApiError } from '../../api/client'
import type {
  AdjudicationAction,
  CandidateDecision,
  ImageEvidence,
  ProposalView,
  ResolutionQueueFilters,
  ResolutionQueueItem,
  ResolutionView,
  ReviewReason,
  RunStatus,
  RunView,
  SubmissionEvidence,
  WorkItemStatus,
} from './consensus-types'

export const NO_OBJECT = 'no_object'

export const REASON_LABELS: Record<ReviewReason, string> = {
  class_tie: 'Tied class votes',
  support_below_threshold: 'Support below the threshold',
  posterior_below_threshold: 'Posterior below the threshold',
  ambiguous_match: 'Ambiguous object match',
  geometry_below_threshold: 'Geometry agreement below the threshold',
  topology_invalid: 'Invalid mask topology',
  resolver_unavailable: 'Resolver unavailable',
  resolver_output_invalid: 'Invalid resolver output',
  worker_failed: 'Resolver run failed',
  expert_required: 'Needs an expert decision',
}
export const REASONS = Object.keys(REASON_LABELS) as ReviewReason[]

export const WORK_ITEM_STATUS_LABELS: Record<WorkItemStatus, string> = {
  pending_review: 'Waiting for reviewers',
  review_ready: 'All reviews submitted',
  review_required: 'Needs a decision',
  resolved: 'Decided',
  cancelled: 'Cancelled',
}
export const WORK_ITEM_STATUSES = Object.keys(WORK_ITEM_STATUS_LABELS) as WorkItemStatus[]

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  review_required: 'Needs review',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

export const SOURCE_LABELS: Record<ResolutionSource, string> = {
  single_submission: 'Single submission',
  automatic_consensus: 'Automatic consensus',
  expert_adjudication: 'Expert adjudication',
}

export const ACTION_LABELS: Record<AdjudicationAction, string> = {
  accept_proposal: 'Accepted the proposal',
  edit_proposal: 'Edited the proposal',
  edit_submission: 'Edited a raw submission',
  replace: 'Replaced with a new annotation',
}

export const PURPOSE_LABELS: Record<BatchPurpose, string> = {
  initial_annotation: 'All images',
  initial_training: 'First training',
  validation: 'Validation',
  test: 'Test',
  acquisition: 'Acquisition',
}

export const DEFAULT_QUEUE_FILTERS: ResolutionQueueFilters = { state: ['review_required'] }

export const AGE_OPTIONS = [
  { label: 'Any age', seconds: undefined },
  { label: 'At least 1 hour', seconds: 3_600 },
  { label: 'At least 1 day', seconds: 86_400 },
  { label: 'At least 1 week', seconds: 604_800 },
] as const

export const SIDE_BY_SIDE_WIDTH = 1200
export const MAX_OVERLAY_SOURCES = 4

type Ratio = { numerator: number; denominator: number }

/** One evidence document drawn read-only with a stable colour and line pattern. */
export type EvidenceSource = {
  id: string
  kind: 'proposal' | 'resolution' | 'submission'
  label: string
  detail: string
  objects: AnnotationObject[]
  color: string
  dash: string
  pattern: string
  defaultVisible: boolean
}

export type CandidateRegion = {
  key: string
  label: string
  passed: boolean
  region: [number, number, number, number]
}

export type MetricRow = { label: string; value: string }

export type ClassVoteRow = {
  classId: string
  name: string
  marked: number
  notMarked: number
  validVotes: number
  support: string
  share: number
  outcome: string
  passed: boolean
  reasons: string[]
  posterior: string | null
}

export type EvidenceLayout = 'overlay' | 'side-by-side'

const SUBMISSION_COLORS = ['#E69F00', '#56B4E9', '#009E73', '#CC79A7', '#D55E00', '#0072B2']
const SUBMISSION_PATTERNS = [
  { dash: '8 4', name: 'dashed line' },
  { dash: '2 4', name: 'dotted line' },
  { dash: '10 4 2 4', name: 'dash-dot line' },
  { dash: '4 3', name: 'short dashes' },
  { dash: '', name: 'solid line' },
]
const PROPOSAL_STYLE = { color: '#FFFFFF', dash: '14 5', pattern: 'long dashes' }
const RESOLUTION_STYLE = { color: '#F0E442', dash: '', pattern: 'solid line' }

export function reasonLabel(reason: string | null) {
  if (!reason) return 'No reason recorded'
  return REASON_LABELS[reason as ReviewReason] ?? humanize(reason)
}

export function humanize(identifier: string) {
  const words = identifier.replaceAll('_', ' ').replaceAll('.', ' · ').trim()
  return words ? words[0]!.toLocaleUpperCase() + words.slice(1) : identifier
}

export function classLabel(classes: ProjectClassInput[], classId: string | null | undefined) {
  if (classId === NO_OBJECT) return 'No object'
  if (!classId) return 'No class'
  return classes.find((item) => item.id === classId)?.name ?? 'Unknown class'
}

export function formatRatio(value: unknown) {
  if (!isRatio(value)) return formatValue(value)
  const share = value.denominator ? ` (${Math.round((value.numerator / value.denominator) * 100)}%)` : ''
  return `${value.numerator}/${value.denominator}${share}`
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'string') return value
  if (isRatio(value)) return formatRatio(value)
  if (Array.isArray(value)) return value.map(formatValue).join(', ')
  return Object.entries(value as Record<string, unknown>)
    .map(([key, entry]) => `${humanize(key)} ${formatValue(entry)}`)
    .join(' · ')
}

export function formatAge(createdAt: string, now: number) {
  const minutes = Math.floor((now - new Date(createdAt).getTime()) / 60_000)
  if (minutes < 1) return 'under a minute'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h`
  return `${Math.floor(hours / 24)} d`
}

export function formatTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export function shortId(value: string) {
  return value.length > 10 ? `${value.slice(0, 8)}…` : value
}

export const consensusPaths = {
  queue: (projectId: string) => `/projects/${projectId}/consensus`,
  image: (projectId: string, batchItemId: string) => `/projects/${projectId}/consensus/images/${batchItemId}`,
  workItem: (projectId: string, workItemId: string, batchItemId: string) =>
    `/projects/${projectId}/consensus/work-items/${workItemId}?item=${encodeURIComponent(batchItemId)}`,
}

/** A person's display name, "you" for the caller, or a shortened identifier. */
export function personName(
  userId: string | null,
  people: { user_id: string; display_name: string }[],
  currentUserId: string | undefined,
) {
  if (!userId) return 'the system'
  if (userId === currentUserId) return 'you'
  return people.find((person) => person.user_id === userId)?.display_name ?? shortId(userId)
}

export function consensusBatches(batches: AnnotationBatch[]) {
  return batches.filter((batch) => batch.mode === 'consensus')
}

/** The batch with cases waiting for a decision, else the first started one. */
export function defaultBatchId(batches: AnnotationBatch[]) {
  const candidates = consensusBatches(batches)
  return (
    candidates.find((batch) => batch.review_required_items > 0) ??
    candidates.find((batch) => batch.status !== 'preparing')
  )?.id ?? null
}

export function batchOptionLabel(batch: AnnotationBatch) {
  return `${PURPOSE_LABELS[batch.purpose]} · ${humanize(batch.status)} · ${batch.review_required_items} need a decision`
}

export function scopeLabel(scope: 'image' | 'candidate', ordinal?: number) {
  if (scope === 'image') return 'Whole image'
  return ordinal === undefined ? 'One object' : `Object ${ordinal + 1}`
}

export function reviewCountText(item: Pick<ResolutionQueueItem, 'reviews_submitted' | 'reviews_required'>) {
  if (!item.reviews_required) return 'no scoped review'
  return `${item.reviews_submitted} of ${item.reviews_required} reviews`
}

export function resolverText(item: Pick<ResolutionQueueItem, 'resolver' | 'resolver_version' | 'class_strategy'>) {
  if (!item.resolver) return 'No run recorded'
  const version = item.resolver_version ? ` v${item.resolver_version}` : ''
  return `${item.resolver}${version}${item.class_strategy ? ` · ${item.class_strategy}` : ''}`
}

/** A one-line, task-specific digest of a queue row's candidate metrics. */
export function queueMetricsSummary(
  metrics: Record<string, unknown>,
  taskType: TaskType,
  classes: ProjectClassInput[],
) {
  if (!Object.keys(metrics).length) return 'No proposal metrics'
  if (taskType === 'classification') {
    const rows = Object.values(asRecord(metrics.classes)).map(asRecord)
    if (!rows.length) return 'No proposal metrics'
    const undecided = rows.filter((row) => row.passed !== true).length
    const lowest = rows
      .map((row) => row.support)
      .filter(isRatio)
      .sort((a, b) => a.numerator * b.denominator - b.numerator * a.denominator)[0]
    return `${undecided} of ${rows.length} classes need review${lowest ? ` · lowest support ${formatRatio(lowest)}` : ''}`
  }
  const parts = [`Decision ${decisionText(metrics.outcome, classes)}`]
  if (isRatio(metrics.support)) parts.push(`support ${formatRatio(metrics.support)}`)
  if (taskType === 'detection' && 'median_iou' in metrics) parts.push(`median IoU ${formatValue(metrics.median_iou)}`)
  if (taskType === 'segmentation' && 'median_overlap' in metrics) {
    parts.push(`median ${overlapName(metrics.matching_metric)} ${formatValue(metrics.median_overlap)}`)
  }
  return parts.join(' · ')
}

/** The metrics of one detection or segmentation candidate, in reading order. */
export function candidateMetricRows(
  candidate: Pick<CandidateDecision, 'metrics'>,
  taskType: TaskType,
  classes: ProjectClassInput[],
): MetricRow[] {
  const metrics = candidate.metrics
  const rows: MetricRow[] = []
  const add = (key: string, label: string, value = formatValue(metrics[key])) => {
    if (key in metrics) rows.push({ label, value })
  }
  add('outcome', 'Decision', decisionText(metrics.outcome, classes))
  add('votes', 'Votes', votesText(asRecord(metrics.votes), classes))
  add('valid_votes', 'Valid votes')
  add('support', 'Support', formatRatio(metrics.support))
  add('margin', 'Margin')
  add('normalized_entropy', 'Normalized entropy')
  add('decision_rule', 'Decision rule', humanize(String(metrics.decision_rule)))
  add('posterior', 'Posterior')
  add('weighted_support', 'Weighted support')
  if (taskType === 'detection') {
    add('median_iou', 'Median pairwise IoU')
    add('supporting_boxes', 'Supporting boxes')
  }
  if (taskType === 'segmentation') {
    add('median_overlap', `Median pairwise ${overlapName(metrics.matching_metric)}`)
    add('supporting_masks', 'Supporting masks')
    add('area', 'Mask area (pixels)')
    if ('refinement' in metrics) rows.push({ label: 'Mask refinement', value: formatValue(asRecord(metrics.refinement).strategy) })
    const post = asRecord(metrics.post_processing)
    if ('area_change' in post) rows.push({ label: 'Area change after clean-up', value: formatValue(post.area_change) })
    if ('topology_change' in post) rows.push({ label: 'Topology change after clean-up', value: formatValue(post.topology_change) })
    if ('material_change' in post) rows.push({ label: 'Material change', value: formatValue(post.material_change) })
    const tracing = asRecord(metrics.polygonization)
    if ('outer_rings' in tracing) {
      rows.push({
        label: 'Traced outline',
        value: `${formatValue(tracing.outer_rings)} outer rings · ${formatValue(tracing.holes)} holes · ${formatValue(tracing.dropped_degenerate)} degenerate rings dropped`,
      })
    }
  }
  return rows
}

/** Per-class marked and not-marked votes of a classification image case. */
export function classVoteRows(candidate: Pick<CandidateDecision, 'metrics'>, classes: ProjectClassInput[]): ClassVoteRow[] {
  return Object.entries(asRecord(candidate.metrics.classes)).map(([classId, value]) => {
    const row = asRecord(value)
    const votes = asRecord(row.votes)
    const marked = Number(votes.positive ?? 0)
    const notMarked = Number(votes.negative ?? 0)
    const validVotes = Number(row.valid_votes ?? marked + notMarked)
    return {
      classId,
      name: classLabel(classes, classId),
      marked,
      notMarked,
      validVotes,
      support: formatRatio(row.support),
      share: validVotes ? marked / validVotes : 0,
      outcome: row.outcome === 'positive' ? 'Present' : row.outcome === 'negative' ? 'Absent' : 'Tie',
      passed: row.passed === true,
      reasons: Array.isArray(row.reasons) ? row.reasons.map(String) : [],
      posterior: 'posterior' in row ? formatValue(row.posterior) : null,
    }
  })
}

export function latestProposalRun(evidence: Pick<ImageEvidence, 'runs'>): (RunView & { proposal: ProposalView }) | null {
  const run = [...evidence.runs].reverse().find((entry) => entry.proposal)
  return (run as (RunView & { proposal: ProposalView }) | undefined) ?? null
}

export function currentResolution(evidence: Pick<ImageEvidence, 'resolutions'>): ResolutionView | null {
  return evidence.resolutions.find((entry) => !entry.superseded_at) ?? null
}

/** Every drawable source of an image: latest proposal, current resolution, then each submission. */
export function evidenceSources(evidence: ImageEvidence): EvidenceSource[] {
  const sources: EvidenceSource[] = []
  const run = latestProposalRun(evidence)
  if (run) {
    sources.push({
      id: `proposal:${run.proposal.id}`,
      kind: 'proposal',
      label: `Proposal from run ${run.sequence}`,
      detail: run.proposal.outcome === 'accept' ? 'Every case passed its gates' : 'Some cases need review',
      objects: run.proposal.objects,
      ...PROPOSAL_STYLE,
      defaultVisible: true,
    })
  }
  const resolution = currentResolution(evidence)
  if (resolution) {
    sources.push({
      id: `resolution:${resolution.id}`,
      kind: 'resolution',
      label: `Resolution v${resolution.version}`,
      detail: SOURCE_LABELS[resolution.source],
      objects: resolution.objects,
      ...RESOLUTION_STYLE,
      defaultVisible: true,
    })
  }
  evidence.submissions.forEach((submission, index) => {
    const pattern = SUBMISSION_PATTERNS[index % SUBMISSION_PATTERNS.length]!
    sources.push({
      id: `submission:${submission.id}`,
      kind: 'submission',
      label: submissionLabel(submission),
      detail: submission.current_generation ? 'Current evidence' : 'Earlier evidence generation',
      objects: submission.objects,
      color: SUBMISSION_COLORS[index % SUBMISSION_COLORS.length]!,
      dash: pattern.dash,
      pattern: pattern.name,
      defaultVisible: submission.current_generation,
    })
  })
  return sources
}

export function submissionLabel(submission: Pick<SubmissionEvidence, 'annotator_name' | 'revision'>) {
  return `${submission.annotator_name}, submission revision ${submission.revision}`
}

export function candidateRegions(proposal: Pick<ProposalView, 'candidates'> | null): CandidateRegion[] {
  return (proposal?.candidates ?? [])
    .filter((candidate) => candidate.region)
    .map((candidate) => ({
      key: candidate.key,
      label: `Object ${candidate.ordinal + 1} ${candidate.passed ? 'passed' : 'needs review'}`,
      passed: candidate.passed,
      region: candidate.region!,
    }))
}

/** Side by side below 1200 px or above four visible sources, unless the user chose. */
export function resolveLayout(choice: EvidenceLayout | null, width: number, visibleSources: number): EvidenceLayout {
  if (choice) return choice
  return width < SIDE_BY_SIDE_WIDTH || visibleSources > MAX_OVERLAY_SOURCES ? 'side-by-side' : 'overlay'
}

export function geometrySummary(object: Pick<AnnotationObject, 'geometry'>) {
  const geometry = object.geometry
  if (!geometry) return 'Image label'
  if (geometry.type === 'rectangle') {
    const [x, y, width, height] = geometry.coordinates.map((value) => Math.round(value))
    return `Box at ${x}, ${y}, ${width} × ${height} px`
  }
  const points = geometry.coordinates.reduce((total, ring) => total + ring.length / 2, 0)
  return `Polygon, ${geometry.coordinates.length} ring${geometry.coordinates.length === 1 ? '' : 's'}, ${points} points`
}

export function reviewSummary(evidence: Record<string, unknown>, classes: ProjectClassInput[]) {
  if (Array.isArray(evidence.class_ids)) {
    return `Classes: ${evidence.class_ids.map((id) => classLabel(classes, String(id))).join(', ') || 'none'}`
  }
  if (evidence.decision === 'no_object') return 'No object here'
  if (evidence.decision === 'object') {
    const geometry = evidence.geometry as AnnotationObject['geometry']
    return `${classLabel(classes, String(evidence.class_id))} · ${geometrySummary({ geometry })}`
  }
  return 'Unrecognised review evidence'
}

export function memberSummary(
  member: CandidateDecision['members'][number],
  evidence: Pick<ImageEvidence, 'submissions' | 'reviews'>,
  classes: ProjectClassInput[],
) {
  const name = evidence.submissions.find((entry) => entry.id === member.source_id)?.annotator_name ??
    evidence.reviews.find((entry) => entry.id === member.source_id)?.reviewer_name ??
    shortId(member.source_id)
  return `${name} · object ${shortId(member.object_id)} · ${classLabel(classes, member.class_id)}`
}

export function settingsLines(settings: Record<string, unknown>, prefix = ''): MetricRow[] {
  return Object.entries(settings).flatMap(([key, value]) => {
    const name = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value) && !isRatio(value)) {
      return settingsLines(value as Record<string, unknown>, name)
    }
    return [{ label: humanize(name), value: value === null ? 'Off' : formatValue(value) }]
  })
}

export function dependencyText(versions: Record<string, unknown>) {
  const entries = Object.entries(versions)
  if (!entries.length) return 'None'
  return entries.map(([name, version]) => `${name} ${version ?? 'not installed'}`).join(' · ')
}

export function errorText(error: unknown) {
  if (error instanceof ApiError) return `${error.message}${error.traceId ? ` (trace ID ${error.traceId})` : ''}`
  return error instanceof Error ? error.message : 'The request failed.'
}

export function errorCode(error: unknown) {
  return error instanceof ApiError ? error.code : undefined
}

function decisionText(outcome: unknown, classes: ProjectClassInput[]) {
  if (outcome === null || outcome === undefined) return 'tie, no unique winner'
  return classLabel(classes, String(outcome))
}

function votesText(votes: Record<string, unknown>, classes: ProjectClassInput[]) {
  const parts = Object.entries(votes)
    .filter(([, count]) => Number(count) > 0)
    .map(([outcome, count]) => `${classLabel(classes, outcome)} ${count}`)
  return parts.join(' · ') || 'No votes'
}

function overlapName(metric: unknown) {
  return metric === 'dice' ? 'Dice' : 'IoU'
}

function isRatio(value: unknown): value is Ratio {
  return Boolean(
    value && typeof value === 'object' &&
    typeof (value as Ratio).numerator === 'number' &&
    typeof (value as Ratio).denominator === 'number',
  )
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
