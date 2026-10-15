import type { AnnotationObject } from '../annotation/types'
import { expectedVersions } from './consensus-api'
import type {
  AdjudicationAction,
  AdjudicationRequest,
  EvidenceVersions,
  ImageEvidence,
  LeaseView,
  RetryRequest,
  WorkItemView,
} from './consensus-types'
import { currentResolution } from './consensus-view-model'

export type EditAction = Exclude<AdjudicationAction, 'accept_proposal'>

/** Where an expert edit starts; the choice is recorded as the adjudication action. */
export type EditStart = { kind: 'proposal' } | { kind: 'submission'; submissionId: string } | { kind: 'blank' }

/**
 * An expert's local edit of one work item. `sourceObjects` is what the edit
 * started from and `base` the evidence versions it was built on.
 */
export type AdjudicationDraft = {
  action: EditAction
  sourceSubmissionId: string | null
  sourceObjects: AnnotationObject[]
  objects: AnnotationObject[]
  base: EvidenceVersions
}

export type RationaleRule = 'required' | 'optional'

export type LeaseState =
  | { kind: 'free' }
  | { kind: 'mine'; lease: LeaseView }
  | { kind: 'other'; lease: LeaseView }

export function workItemRun(evidence: Pick<ImageEvidence, 'runs'>, workItem: Pick<WorkItemView, 'run_id'>) {
  return evidence.runs.find((run) => run.id === workItem.run_id) ?? null
}

export function workItemCandidate(evidence: Pick<ImageEvidence, 'runs'>, workItem: Pick<WorkItemView, 'run_id' | 'candidate_key'>) {
  return workItemRun(evidence, workItem)?.proposal?.candidates.find((entry) => entry.key === workItem.candidate_key) ?? null
}

/**
 * The objects `accept_proposal` would decide, as the API chooses them: the
 * candidate's objects, or the whole proposal for an image case; null when
 * there is no proposal.
 */
export function proposalObjects(evidence: Pick<ImageEvidence, 'runs'>, workItem: Pick<WorkItemView, 'run_id' | 'candidate_key' | 'scope'>) {
  const candidate = workItemCandidate(evidence, workItem)
  if (candidate) return candidate.objects
  const proposal = workItemRun(evidence, workItem)?.proposal
  return proposal && workItem.scope === 'image' ? proposal.objects : null
}

export function workItemRegion(evidence: Pick<ImageEvidence, 'runs'>, workItem: WorkItemView) {
  return workItem.candidate_context.region ?? workItemCandidate(evidence, workItem)?.region ?? null
}

/** A submission's objects that belong to the case: all of them for an image case, the candidate's members otherwise. */
export function submissionObjects(evidence: Pick<ImageEvidence, 'runs' | 'submissions'>, workItem: WorkItemView, submissionId: string) {
  const submission = evidence.submissions.find((entry) => entry.id === submissionId)
  if (!submission) return []
  if (workItem.scope === 'image') return submission.objects
  const members = new Set(
    (workItemCandidate(evidence, workItem)?.members ?? [])
      .filter((member) => member.source_id === submissionId)
      .map((member) => member.object_id),
  )
  return submission.objects.filter((object) => members.has(object.id))
}

export function startDraft(evidence: ImageEvidence, workItem: WorkItemView, start: EditStart): AdjudicationDraft {
  const sourceObjects = start.kind === 'proposal'
    ? proposalObjects(evidence, workItem) ?? []
    : start.kind === 'submission' ? submissionObjects(evidence, workItem, start.submissionId) : []
  return {
    action: start.kind === 'proposal' ? 'edit_proposal' : start.kind === 'submission' ? 'edit_submission' : 'replace',
    sourceSubmissionId: start.kind === 'submission' ? start.submissionId : null,
    sourceObjects,
    objects: sourceObjects,
    base: evidence.versions,
  }
}

export function isContributor(evidence: Pick<ImageEvidence, 'contributors'>, userId: string | undefined) {
  return Boolean(userId && evidence.contributors.includes(userId))
}

export function overridesExpert(evidence: Pick<ImageEvidence, 'resolutions'>) {
  return currentResolution(evidence)?.source === 'expert_adjudication'
}

/** Edits, conflicted self-adjudication, and overriding an expert need a rationale; a plain acceptance takes an optional note. */
export function rationaleRule(
  action: AdjudicationAction,
  context: { contributor: boolean; overridingExpert: boolean },
): RationaleRule {
  return action !== 'accept_proposal' || context.contributor || context.overridingExpert ? 'required' : 'optional'
}

export function rationaleReasons(action: AdjudicationAction, context: { contributor: boolean; overridingExpert: boolean }) {
  const reasons: string[] = []
  if (action !== 'accept_proposal') reasons.push('Edits and replacements need a rationale.')
  if (context.contributor) reasons.push('You contributed evidence to this image, so the decision is recorded as a conflict.')
  if (context.overridingExpert) reasons.push('This overrides an earlier expert adjudication.')
  return reasons
}

export function leaseState(lease: LeaseView | null, userId: string | undefined, now: number): LeaseState {
  if (!lease || new Date(lease.expires_at).getTime() <= now) return { kind: 'free' }
  return lease.holder_id === userId ? { kind: 'mine', lease } : { kind: 'other', lease }
}

export function sameVersions(a: EvidenceVersions, b: EvidenceVersions) {
  return a.evidence_generation === b.evidence_generation &&
    a.configuration_fingerprint === b.configuration_fingerprint &&
    a.resolution_version === b.resolution_version
}

export function draftChanged(draft: Pick<AdjudicationDraft, 'objects' | 'sourceObjects'>) {
  return JSON.stringify(draft.objects) !== JSON.stringify(draft.sourceObjects)
}

export function editRequest(draft: AdjudicationDraft, rationale: string): AdjudicationRequest {
  return {
    ...expectedVersions(draft.base),
    action: draft.action,
    objects: draft.objects,
    ...(draft.sourceSubmissionId ? { source_submission_id: draft.sourceSubmissionId } : {}),
    rationale,
  }
}

export function acceptRequest(versions: EvidenceVersions, rationale: string): AdjudicationRequest {
  return {
    ...expectedVersions(versions),
    action: 'accept_proposal',
    ...(rationale.trim() ? { rationale: rationale.trim() } : {}),
  }
}

/** A retry over the image's latest evidence; without a configuration the batch snapshot is used. */
export function retryRequest(versions: EvidenceVersions, rationale: string, configuration?: RetryRequest['configuration']): RetryRequest {
  return { ...expectedVersions(versions), rationale: rationale.trim(), ...(configuration ? { configuration } : {}) }
}
