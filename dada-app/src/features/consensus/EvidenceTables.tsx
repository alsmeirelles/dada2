import { Gavel } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { ProjectClassInput, TaskType } from '../projects/types'
import type { CandidateDecision, ImageEvidence, ResolutionView, RunView } from './consensus-types'
import {
  ACTION_LABELS,
  RUN_STATUS_LABELS,
  SOURCE_LABELS,
  WORK_ITEM_STATUS_LABELS,
  candidateMetricRows,
  classLabel,
  classVoteRows,
  consensusPaths,
  dependencyText,
  formatTime,
  geometrySummary,
  humanize,
  memberSummary,
  personName,
  reasonLabel,
  reviewSummary,
  scopeLabel,
  settingsLines,
  type ClassVoteRow,
  type EvidenceSource,
} from './consensus-view-model'

type People = { user_id: string; display_name: string }[]

/** Every source and its objects as text, so nothing on the image depends on colour or sight. */
export function EvidenceSourceTable({ sources, classes }: { sources: EvidenceSource[]; classes: ProjectClassInput[] }) {
  return <table className="consensus-table">
    <caption>Every evidence source and its objects</caption>
    <thead><tr><th scope="col">Source</th><th scope="col">Line pattern</th><th scope="col">Object</th><th scope="col">Class</th><th scope="col">Geometry</th></tr></thead>
    <tbody>
      {sources.flatMap((source) => source.objects.length
        ? source.objects.map((object, index) => <tr key={`${source.id}:${object.id}`}>
          {index === 0 && <th scope="rowgroup" rowSpan={source.objects.length}>{source.label}<small>{source.detail}</small></th>}
          {index === 0 && <td rowSpan={source.objects.length}>{source.pattern}</td>}
          <td>{index + 1}</td>
          <td>{classLabel(classes, object.class_id)}</td>
          <td>{geometrySummary(object)}</td>
        </tr>)
        : [<tr key={source.id}><th scope="row">{source.label}<small>{source.detail}</small></th><td>{source.pattern}</td><td colSpan={3}>No objects</td></tr>])}
    </tbody>
  </table>
}

export function ReviewTable({ evidence, classes }: { evidence: ImageEvidence; classes: ProjectClassInput[] }) {
  if (!evidence.reviews.length) return <p className="muted">No scoped reviews were submitted for this image.</p>
  const ordinals = new Map(evidence.work_items.map((item) => [item.id, item]))
  return <table className="consensus-table">
    <caption>Scoped review submissions</caption>
    <thead><tr><th scope="col">Reviewer</th><th scope="col">Case</th><th scope="col">Evidence</th><th scope="col">Submitted</th></tr></thead>
    <tbody>{evidence.reviews.map((review) => {
      const workItem = ordinals.get(review.work_item_id)
      return <tr key={review.id}>
        <th scope="row">{review.reviewer_name}</th>
        <td>{workItem ? scopeLabel(workItem.scope, workItem.candidate_ordinal) : review.candidate_key}</td>
        <td>{reviewSummary(review.evidence, classes)}</td>
        <td>{formatTime(review.submitted_at)}</td>
      </tr>
    })}</tbody>
  </table>
}

/** The latest proposal's decision for every image or object case, with the metrics the API computed. */
export function CandidateDecisions({ evidence, run, taskType, classes }: { evidence: ImageEvidence; run: RunView | null; taskType: TaskType; classes: ProjectClassInput[] }) {
  if (!run?.proposal) return <p className="muted">No run has produced a proposal for this image yet.</p>
  return <div className="candidate-list">
    {run.proposal.candidates.map((candidate) => <CandidateCard key={candidate.key} candidate={candidate} evidence={evidence} taskType={taskType} classes={classes} />)}
  </div>
}

export function CandidateCard({ candidate, evidence, taskType, classes }: { candidate: CandidateDecision; evidence: ImageEvidence; taskType: TaskType; classes: ProjectClassInput[] }) {
  const classification = taskType === 'classification' && candidate.scope === 'image'
  const rows = classification ? [] : candidateMetricRows(candidate, taskType, classes)
  return <article className="candidate-card" aria-label={scopeLabel(candidate.scope, candidate.ordinal)}>
    <header>
      <h3>{scopeLabel(candidate.scope, candidate.ordinal)}</h3>
      <span className={`consensus-status consensus-status--${candidate.passed ? 'resolved' : 'review_required'}`}>{candidate.passed ? 'Passed' : 'Needs review'}</span>
    </header>
    {!candidate.passed && <p>{candidate.reasons.map(reasonLabel).join(' · ') || 'No reason recorded'}</p>}
    <p className="muted">Proposed: {candidate.objects.length
      ? candidate.objects.map((object) => `${classLabel(classes, object.class_id)}${object.geometry ? ` (${geometrySummary(object)})` : ''}`).join(', ')
      : 'nothing exists here'}</p>
    {candidate.members.length > 0 && <>
      <h4>Members</h4>
      <ul className="member-list">{candidate.members.map((member) => <li key={`${member.source_id}:${member.object_id}`}>{memberSummary(member, evidence, classes)}</li>)}</ul>
    </>}
    {classification && <ClassVotes rows={classVoteRows(candidate, classes)} />}
    {rows.length > 0 && <dl className="metric-list">{rows.map((row) => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>}
  </article>
}

/** Per-class votes as a table with a bar chart beside it; the table is the text equivalent of the bars. */
export function ClassVotes({ rows }: { rows: ClassVoteRow[] }) {
  return <table className="consensus-table class-votes">
    <caption>Vote distribution per class</caption>
    <thead><tr><th scope="col">Class</th><th scope="col">Marked</th><th scope="col">Not marked</th><th scope="col">Support</th><th scope="col">Decision</th><th scope="col">Result</th><th scope="col">Share marked</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.classId}>
      <th scope="row">{row.name}</th>
      <td>{row.marked}</td>
      <td>{row.notMarked}</td>
      <td>{row.support}{row.posterior ? ` · posterior ${row.posterior}` : ''}</td>
      <td>{row.outcome}</td>
      <td>{row.passed ? 'Passed' : row.reasons.map(reasonLabel).join(', ') || 'Needs review'}</td>
      <td><span className="vote-bar" aria-hidden="true"><span style={{ width: `${Math.round(row.share * 100)}%` }} /></span> {Math.round(row.share * 100)}%</td>
    </tr>)}</tbody>
  </table>
}

export function RunProvenance({ runs, people, userId }: { runs: RunView[]; people: People; userId: string | undefined }) {
  if (!runs.length) return <p className="muted">No resolver run exists for this image yet.</p>
  return <div className="run-list">{[...runs].reverse().map((run, index) => <details key={run.id} open={index === 0} className="run-card">
    <summary>Run {run.sequence} · {RUN_STATUS_LABELS[run.status]} · {run.pipeline} v{run.pipeline_version}</summary>
    <dl className="metric-list">
      <div><dt>Trigger</dt><dd>{humanize(run.trigger)}</dd></div>
      <div><dt>Attempt</dt><dd>{run.attempt}</dd></div>
      <div><dt>Requested by</dt><dd>{personName(run.requested_by, people, userId)}</dd></div>
      {run.failure_code && <div><dt>Failure</dt><dd>{humanize(run.failure_code)}{run.failure_detail ? `: ${run.failure_detail}` : ''}</dd></div>}
      <div><dt>Created</dt><dd>{formatTime(run.created_at)}</dd></div>
      <div><dt>Started</dt><dd>{formatTime(run.started_at)}</dd></div>
      <div><dt>Finished</dt><dd>{formatTime(run.finished_at)}</dd></div>
      {settingsLines(run.configuration.parameters).map((row) => <div key={`p:${row.label}`}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
      {settingsLines(run.configuration.review_thresholds).map((row) => <div key={`t:${row.label}`}><dt>Review threshold · {row.label}</dt><dd>{row.value}</dd></div>)}
      <div><dt>Dependency versions</dt><dd>{dependencyText(run.dependency_versions)}</dd></div>
      <div><dt>Configuration fingerprint</dt><dd><code>{run.configuration_fingerprint}</code></dd></div>
      <div><dt>Input fingerprint</dt><dd><code>{run.input_fingerprint}</code></dd></div>
      {run.proposal && <div><dt>Proposal</dt><dd>{run.proposal.outcome === 'accept' ? 'Every case passed' : 'Some cases need review'} · <code>{run.proposal.content_hash}</code></dd></div>}
    </dl>
  </details>)}</div>
}

export function ResolutionHistory({ resolutions, people, userId }: { resolutions: ResolutionView[]; people: People; userId: string | undefined }) {
  if (!resolutions.length) return <p className="muted">This image has no resolution yet.</p>
  return <table className="consensus-table">
    <caption>Resolution history, newest first</caption>
    <thead><tr><th scope="col">Version</th><th scope="col">Source</th><th scope="col">Objects</th><th scope="col">Accepted by</th><th scope="col">Created</th><th scope="col">Superseded</th></tr></thead>
    <tbody>{[...resolutions].reverse().map((resolution) => <tr key={resolution.id}>
      <th scope="row">v{resolution.version}{resolution.superseded_at ? '' : ' (current)'}</th>
      <td>{SOURCE_LABELS[resolution.source]}</td>
      <td>{resolution.objects.length}</td>
      <td>{personName(resolution.accepted_by, people, userId)}</td>
      <td>{formatTime(resolution.created_at)}</td>
      <td>{formatTime(resolution.superseded_at)}</td>
    </tr>)}</tbody>
  </table>
}

export function WorkItemList({ evidence, projectId, people, userId }: { evidence: ImageEvidence; projectId: string; people: People; userId: string | undefined }) {
  if (!evidence.work_items.length) return <p className="muted">No case of this image needed review.</p>
  return <ul className="work-item-list">{evidence.work_items.map((workItem) => <li key={workItem.id} className="work-item-card">
    <div className="queue-row__title">
      <strong>{scopeLabel(workItem.scope, workItem.candidate_ordinal)}</strong>
      <span className={`consensus-status consensus-status--${workItem.status}`}>{WORK_ITEM_STATUS_LABELS[workItem.status]}</span>
    </div>
    <p>{reasonLabel(workItem.reason)} · {workItem.reviews_required ? `${workItem.reviews_submitted} of ${workItem.reviews_required} reviews` : 'no scoped review'}</p>
    {workItem.lease && <p className="muted">Being edited by {personName(workItem.lease.holder_id, people, userId)} until {formatTime(workItem.lease.expires_at)}</p>}
    {workItem.adjudications.map((decision) => <p key={decision.id} className="muted">
      {ACTION_LABELS[decision.action]} by {personName(decision.actor_id, people, userId)} ({decision.actor_role}) on {formatTime(decision.created_at)}
      {decision.contributor_conflict ? ' · contributed evidence to this image' : ''}{decision.rationale ? ` · “${decision.rationale}”` : ''}
    </p>)}
    {workItem.status === 'review_required' && <Link className="button button--primary" to={consensusPaths.workItem(projectId, workItem.id, evidence.batch_item_id)}><Gavel size={16} /> Decide this case</Link>}
  </li>)}</ul>
}
