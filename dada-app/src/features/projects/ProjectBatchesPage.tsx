import { ArrowLeft, CheckCircle2, ClipboardCheck, Layers3, Play, RefreshCcw, Users } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { getCapabilities, type PipelineCapability } from '../../api/capabilities'
import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { consensusKeys, getResolverEligibility } from '../consensus/consensus-api'
import { BatchAssignmentsPanel } from './BatchAssignmentsPanel'
import { listBatches, startBatch, updateBatchPolicy, type BatchPolicySource } from './batch-api'
import { getDatasetLayout } from './dataset-api'
import { detailErrorLines } from './error-details'
import { getAnnotationPolicy, getProject, listMembers, type ProjectMember } from './project-api'
import { ResolverConfigForm } from './ResolverConfigForm'
import {
  configurationIsValid,
  projectConfiguration,
  summarizeSettings,
  type EligibilityState,
  type ResolverConfiguration,
} from './resolver-config'
import { resolverLabel } from './resolver-label'
import type { AnnotationBatch, AnnotationPolicy, BatchPurpose, TaskType } from './types'

const purposeLabels: Record<BatchPurpose, string> = {
  initial_annotation: 'All images',
  initial_training: 'First training',
  validation: 'Validation',
  test: 'Test',
  acquisition: 'Acquisition',
}

export function ProjectBatchesPage() {
  const { projectId = '' } = useParams()
  const { token, user } = useAuth()
  const queryClient = useQueryClient()
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId, token!),
    enabled: Boolean(projectId && token),
  })
  const members = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listMembers(projectId, token!),
    enabled: Boolean(projectId && token),
  })
  const batches = useQuery({
    queryKey: ['project-batches', projectId],
    queryFn: () => listBatches(projectId, token!),
    enabled: Boolean(projectId && token),
  })
  const layout = useQuery({
    queryKey: ['dataset-layout', projectId],
    queryFn: () => getDatasetLayout(projectId, token!),
    enabled: Boolean(projectId && token),
  })
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getCapabilities, staleTime: Infinity })
  const self = members.data?.items.find((member) => member.user_id === user?.id)
  const memberNames = new Map(
    members.data?.items.map((member) => [member.user_id, member.display_name]) ?? [],
  )
  const canManage = Boolean(
    user?.is_administrator || self?.role === 'owner' || self?.role === 'manager',
  )
  const defaultPolicy = useQuery({
    queryKey: ['project-policy', projectId],
    queryFn: () => getAnnotationPolicy(projectId, token!),
    enabled: Boolean(projectId && token && canManage),
  })
  const hasPreparingConsensus = Boolean(batches.data?.items.some((batch) => batch.status === 'preparing' && batch.mode === 'consensus'))
  const eligibilityQuery = useQuery({
    queryKey: consensusKeys.eligibility(projectId),
    queryFn: () => getResolverEligibility(projectId, token!),
    enabled: Boolean(projectId && token && canManage && hasPreparingConsensus),
  })
  const eligibility: EligibilityState = eligibilityQuery.data
    ? { status: 'ready', report: eligibilityQuery.data }
    : eligibilityQuery.isError ? { status: 'error' } : { status: 'loading' }
  const refreshBatches = () => queryClient.invalidateQueries({ queryKey: ['project-batches', projectId] })
  const start = useMutation({
    mutationFn: (batchId: string) => startBatch(projectId, batchId, token!),
    onSuccess: refreshBatches,
  })
  const applyDefault = useMutation({
    mutationFn: ({ batchId, policy }: { batchId: string; policy: AnnotationPolicy }) =>
      updateBatchPolicy(projectId, batchId, policy, token!),
    onSuccess: refreshBatches,
  })
  const editPolicy = useMutation({
    mutationFn: ({ batchId, body }: { batchId: string; body: BatchPolicySource }) =>
      updateBatchPolicy(projectId, batchId, body, token!),
    onSuccess: refreshBatches,
  })
  const hasStartedBatch = batches.data?.items.some((batch) => batch.status !== 'preparing')
  const taskType = project.data?.task_type
  const pipeline = taskType ? capabilities.data?.consensus_pipelines[taskType] : undefined
  const failure = start.error ?? applyDefault.error ?? editPolicy.error

  if (project.isLoading || members.isLoading || batches.isLoading) {
    return <main className="page-container"><div className="panel status-panel">Loading annotation batches…</div></main>
  }
  if (batches.error instanceof ApiError && batches.error.status === 403) {
    return <main className="page-container"><div className="panel status-panel">Annotation batches are a manager view. <Link to={`/projects/${projectId}/annotate`}>Open my assignments</Link>.</div></main>
  }
  if (project.isError || members.isError || batches.isError) {
    return <main className="page-container"><div className="panel error-panel" role="alert">Annotation batches could not be loaded.</div></main>
  }

  return <main className="page-container batch-page">
    <div className="page-heading">
      <div><Link className="back-link back-link--flow" to="/projects"><ArrowLeft size={17} /> Projects</Link><p className="eyebrow">{project.data?.name}</p><h1>Annotation batches</h1><p className="muted">{project.data?.dataset_layout === 'single_batch'
        ? 'One static batch covers every image. There is no training or acquisition loop.'
        : `Validation and test are annotated in full, together with the first training batch. The first acquisition waits until every initial image has an accepted resolution.${layout.data ? ` ${layout.data.training_pool_size} training images remain in the unlabeled pool.` : ''}`}</p></div>
      <div className="batch-actions">
        {hasStartedBatch && <Link className="button button--primary" to={`/projects/${projectId}/annotate`}>Open my assignments</Link>}
        {canManage && <Link className="button button--secondary" to={`/projects/${projectId}/settings`}>Default policy settings</Link>}
      </div>
    </div>
    {failure && <div className="form-error" role="alert">{batchError(failure)}{detailErrorLines(failure).map((line) => <small key={line}>{line}</small>)}</div>}
    <section className="batch-grid" aria-label="Annotation batches">
      {(batches.data?.items ?? []).map((batch) => <BatchCard
        key={batch.id}
        projectId={projectId}
        batch={batch}
        members={members.data?.items ?? []}
        canManage={canManage}
        annotatorNames={batch.annotator_ids.map((id) => memberNames.get(id) ?? id)}
        defaultPolicy={defaultPolicy.data}
        taskType={taskType}
        pipeline={pipeline}
        eligibility={eligibility}
        pending={start.isPending || applyDefault.isPending || editPolicy.isPending}
        onApplyDefault={() => defaultPolicy.data && applyDefault.mutate({ batchId: batch.id, policy: defaultPolicy.data })}
        onSavePolicy={(body) => editPolicy.mutate({ batchId: batch.id, body })}
        onStart={() => start.mutate(batch.id)}
      />)}
    </section>
  </main>
}

function BatchCard({ projectId, batch, members, canManage, annotatorNames, defaultPolicy, taskType, pipeline, eligibility, pending, onApplyDefault, onSavePolicy, onStart }: {
  projectId: string
  batch: AnnotationBatch
  members: ProjectMember[]
  canManage: boolean
  annotatorNames: string[]
  defaultPolicy?: AnnotationPolicy
  taskType: TaskType | undefined
  pipeline: PipelineCapability | undefined
  eligibility: EligibilityState
  pending: boolean
  onApplyDefault: () => void
  onSavePolicy: (body: BatchPolicySource) => void
  onStart: () => void
}) {
  const expectedAssignments = batch.mode === 'consensus'
    ? batch.total_items * batch.annotator_ids.length
    : batch.total_items
  return <article className="batch-card">
    <header><span className={`status-badge status-badge--${batch.status}`}>{batch.status.replace('_', ' ')}</span><span className="batch-purpose"><Layers3 size={16} />{purposeLabels[batch.purpose]}</span></header>
    <h2>{purposeLabels[batch.purpose]} annotations</h2>
    <div className="batch-counts"><span><strong>{batch.total_items}</strong> selected images</span><span><strong>{batch.resolved_items}</strong> resolved images</span><span><strong>{batch.total_assignments || expectedAssignments}</strong> {batch.total_assignments ? 'assignments' : 'assignments after start'}</span><span><strong>{batch.submitted_assignments}</strong> submitted</span></div>
    {batch.status !== 'preparing' && <>
      <p className="muted">{batch.available_assignments} available · {batch.in_progress_assignments} in progress assignments</p>
      <div className="batch-resolution" aria-label="Image resolution progress">
        <span><strong>{batch.resolved_items}</strong> resolved</span>
        <span><strong>{batch.awaiting_resolution_items}</strong> awaiting resolution</span>
        <span><strong>{batch.resolving_items}</strong> resolving</span>
        <span><strong>{batch.in_review_items}</strong> in review</span>
        <span className={batch.review_required_items ? 'attention' : ''}><strong>{batch.review_required_items}</strong> review required</span>
        <span><strong>{batch.cancelled_items}</strong> cancelled</span>
      </div>
      {canManage && batch.review_required_items > 0 && <Link className="button button--secondary" to={`/projects/${projectId}/consensus`}><ClipboardCheck size={16} />Review {batch.review_required_items} image{batch.review_required_items === 1 ? '' : 's'} in the consensus queue</Link>}
    </>}
    <div className="batch-policy"><span><Users size={16} /><strong>{batch.mode === 'consensus' ? `Consensus · ${batch.annotator_ids.length} annotators` : 'Single annotation'}</strong></span><small>Policy snapshot v{batch.source_policy_version}. Changes to project defaults do not alter this batch.</small>{batch.resolver && <small>Resolver: {resolverLabel(batch.resolver)}{batch.resolver_version ? ` · version ${batch.resolver_version}` : ''}</small>}</div>
    {canManage && <details className="batch-details"><summary>Snapshot and selection details</summary><dl>
      <div><dt>Annotators</dt><dd>{annotatorNames.join(', ') || 'Every member allowed to annotate, in turn'}</dd></div>
      {batch.mode === 'consensus' && <div><dt>Resolution settings</dt><dd><ConfigSummary configuration={{ parameters: batch.parameters, review_thresholds: batch.review_thresholds }} /></dd></div>}
      {batch.mode === 'consensus' && <div><dt>Adjudicator</dt><dd>{batch.require_independent_adjudicator ? 'Must be independent of the image\'s evidence' : 'Contributors may adjudicate with a rationale'}</dd></div>}
      <div><dt>Selection</dt><dd>{batch.selection_strategy} · seed {batch.selection_seed}</dd></div>
      <div><dt>Requested / selected</dt><dd>{batch.requested_size} / {batch.total_items + batch.cancelled_items} images</dd></div>
      <div><dt>Selected at</dt><dd>{new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(batch.created_at))}</dd></div>
      <div><dt>Input fingerprint</dt><dd><code>{batch.selection_input_fingerprint}</code></dd></div>
    </dl></details>}
    {canManage && batch.status === 'preparing' && batch.mode === 'consensus' && taskType && pipeline && <details className="batch-details">
      <summary>Edit this batch's resolution settings</summary>
      <BatchPolicyEditor batch={batch} taskType={taskType} pipeline={pipeline} eligibility={eligibility} pending={pending} onSave={onSavePolicy} />
    </details>}
    {canManage && batch.status !== 'preparing' && <BatchAssignmentsPanel projectId={projectId} batch={batch} members={members} />}
    {canManage && batch.status === 'preparing' && <div className="batch-actions">
      <Button variant="secondary" onClick={onApplyDefault} disabled={pending || !defaultPolicy}><RefreshCcw size={16} />Apply current default</Button>
      <Button onClick={onStart} disabled={pending}><Play size={16} />Start batch</Button>
    </div>}
    {batch.status !== 'preparing' && <p className="batch-started"><CheckCircle2 size={16} />Started {batch.started_at ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(batch.started_at)) : ''}</p>}
  </article>
}

function BatchPolicyEditor({ batch, taskType, pipeline, eligibility, pending, onSave }: {
  batch: AnnotationBatch
  taskType: TaskType
  pipeline: PipelineCapability
  eligibility: EligibilityState
  pending: boolean
  onSave: (body: BatchPolicySource) => void
}) {
  const [configuration, setConfiguration] = useState<ResolverConfiguration>(() => projectConfiguration(taskType, pipeline, batch))
  const [requireIndependent, setRequireIndependent] = useState(batch.require_independent_adjudicator)
  const valid = configurationIsValid(taskType, pipeline, configuration)
  return <div className="batch-policy-editor">
    <ResolverConfigForm
      taskType={taskType}
      pipeline={pipeline}
      value={configuration}
      onChange={setConfiguration}
      eligibility={eligibility}
      requireIndependentAdjudicator={requireIndependent}
      onRequireIndependentAdjudicatorChange={setRequireIndependent}
      disabled={pending}
    />
    <Button onClick={() => onSave({ ...batch, resolver: pipeline.id, ...configuration, require_independent_adjudicator: requireIndependent })} disabled={pending || !valid}>Save batch settings</Button>
  </div>
}

function ConfigSummary({ configuration }: { configuration: ResolverConfiguration }) {
  const lines = [...summarizeSettings(configuration.parameters), ...summarizeSettings(configuration.review_thresholds)]
  if (!lines.length) return <>Defaults</>
  return <dl className="config-summary">{lines.map((line) => <div key={line.label}><dt>{line.label}</dt><dd>{line.value}</dd></div>)}</dl>
}

function batchError(error: Error) {
  if (error instanceof ApiError && error.code === 'invalid_consensus_group') return 'This batch snapshot contains annotators who are no longer eligible. Update the batch policy before starting it.'
  if (error instanceof ApiError && error.code === 'batch_already_started') return 'This batch was already started. Refresh to see its current assignment counts.'
  if (error instanceof ApiError && error.code === 'policy_locked') return 'This batch has started, so its policy snapshot can no longer be changed.'
  if (error instanceof ApiError && error.code === 'resolver_unavailable') return 'This batch cannot start: the API reports that its class strategy does not have enough project evidence yet. No assignments were created.'
  if (error instanceof ApiError && error.code === 'invalid_resolver_configuration') return 'The API refused these resolution settings.'
  return error.message || 'The batch could not be updated.'
}
