import { ArrowLeft, CheckCircle2, Layers3, Play, RefreshCcw, Users } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { listBatches, startBatch, updateBatchPolicy } from './batch-api'
import { getAnnotationPolicy, getProject, listMembers } from './project-api'
import type { AnnotationBatch, AnnotationPolicy, BatchPurpose } from './types'

const purposeLabels: Record<BatchPurpose, string> = {
  initial_training: 'Train',
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
  const start = useMutation({
    mutationFn: (batchId: string) => startBatch(projectId, batchId, token!),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['project-batches', projectId],
    }),
  })
  const applyDefault = useMutation({
    mutationFn: ({ batchId, policy }: { batchId: string; policy: AnnotationPolicy }) =>
      updateBatchPolicy(projectId, batchId, policy, token!),
    onSuccess: () => queryClient.invalidateQueries({
      queryKey: ['project-batches', projectId],
    }),
  })
  const hasStartedBatch = batches.data?.items.some((batch) => batch.status !== 'preparing')

  if (project.isLoading || members.isLoading || batches.isLoading) {
    return <main className="page-container"><div className="panel status-panel">Loading annotation batches…</div></main>
  }
  if (project.isError || members.isError || batches.isError) {
    return <main className="page-container"><div className="panel error-panel" role="alert">Annotation batches could not be loaded.</div></main>
  }

  return <main className="page-container batch-page">
    <div className="page-heading">
      <div><Link className="back-link back-link--flow" to="/projects"><ArrowLeft size={17} /> Projects</Link><p className="eyebrow">{project.data?.name}</p><h1>Annotation batches</h1><p className="muted">Train, validation, and test are fixed at activation. Every initial assignment must be submitted before the first acquisition round.</p></div>
      <div className="batch-actions">
        {hasStartedBatch && <Link className="button button--primary" to={`/projects/${projectId}/annotate`}>Open annotation workspace</Link>}
        {canManage && <Link className="button button--secondary" to={`/projects/${projectId}/settings`}>Default policy settings</Link>}
      </div>
    </div>
    {(start.isError || applyDefault.isError) && <p className="form-error" role="alert">{batchError(start.error ?? applyDefault.error!)}</p>}
    <section className="batch-grid" aria-label="Annotation batches">
      {(batches.data?.items ?? []).map((batch) => <BatchCard
        key={batch.id}
        batch={batch}
        canManage={canManage}
        annotatorNames={batch.annotator_ids.map((id) => memberNames.get(id) ?? id)}
        defaultPolicy={defaultPolicy.data}
        pending={start.isPending || applyDefault.isPending}
        onApplyDefault={() => defaultPolicy.data && applyDefault.mutate({ batchId: batch.id, policy: defaultPolicy.data })}
        onStart={() => start.mutate(batch.id)}
      />)}
    </section>
  </main>
}

function BatchCard({ batch, canManage, annotatorNames, defaultPolicy, pending, onApplyDefault, onStart }: {
  batch: AnnotationBatch
  canManage: boolean
  annotatorNames: string[]
  defaultPolicy?: AnnotationPolicy
  pending: boolean
  onApplyDefault: () => void
  onStart: () => void
}) {
  const expectedAssignments = batch.mode === 'consensus'
    ? batch.total_items * batch.annotator_ids.length
    : batch.total_items
  return <article className="batch-card">
    <header><span className={`status-badge status-badge--${batch.status}`}>{batch.status.replace('_', ' ')}</span><span className="batch-purpose"><Layers3 size={16} />{purposeLabels[batch.purpose]}</span></header>
    <h2>{purposeLabels[batch.purpose]} annotations</h2>
    <div className="batch-counts"><span><strong>{batch.total_items}</strong> selected images</span><span><strong>{batch.total_assignments || expectedAssignments}</strong> {batch.total_assignments ? 'generated' : 'assignments after start'}</span><span><strong>{batch.submitted_assignments}</strong> submitted</span></div>
    <div className="batch-policy"><span><Users size={16} /><strong>{batch.mode === 'consensus' ? `Consensus · ${batch.annotator_ids.length} annotators` : 'Single annotation'}</strong></span><small>Policy snapshot v{batch.source_policy_version}. Changes to project defaults do not alter this batch.</small>{batch.resolver && <small>Resolver: {batch.resolver}{batch.resolver_version ? ` v${batch.resolver_version}` : ''}</small>}</div>
    {canManage && <details className="batch-details"><summary>Snapshot and selection details</summary><dl>
      <div><dt>Annotators</dt><dd>{annotatorNames.join(', ') || 'Any eligible annotator'}</dd></div>
      <div><dt>Parameters</dt><dd>{formatRecord(batch.parameters)}</dd></div>
      <div><dt>Review thresholds</dt><dd>{formatRecord(batch.review_thresholds)}</dd></div>
      <div><dt>Selection</dt><dd>{batch.selection_strategy} · seed {batch.selection_seed}</dd></div>
      <div><dt>Input fingerprint</dt><dd><code>{batch.selection_input_fingerprint}</code></dd></div>
    </dl></details>}
    {canManage && batch.status === 'preparing' && <div className="batch-actions">
      <Button variant="secondary" onClick={onApplyDefault} disabled={pending || !defaultPolicy}><RefreshCcw size={16} />Apply current default</Button>
      <Button onClick={onStart} disabled={pending}><Play size={16} />Start batch</Button>
    </div>}
    {batch.status !== 'preparing' && <p className="batch-started"><CheckCircle2 size={16} />Started {batch.started_at ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(batch.started_at)) : ''}</p>}
  </article>
}

function batchError(error: Error) {
  if (error instanceof ApiError && error.code === 'invalid_consensus_group') return 'This batch snapshot contains annotators who are no longer eligible. Update the batch policy before starting it.'
  if (error instanceof ApiError && error.code === 'batch_already_started') return 'This batch was already started. Refresh to see its current assignment counts.'
  if (error instanceof ApiError && error.code === 'policy_locked') return 'This batch has started, so its policy snapshot can no longer be changed.'
  return error.message || 'The batch could not be started.'
}

function formatRecord(values: Record<string, number | string | boolean>) {
  const entries = Object.entries(values)
  return entries.length ? entries.map(([key, value]) => `${key}: ${value}`).join(', ') : 'None'
}
