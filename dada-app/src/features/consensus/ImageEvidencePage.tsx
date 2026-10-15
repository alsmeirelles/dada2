import { ArrowLeft, Ban, RotateCcw } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { getWorkspaceBootstrap } from '../annotation/annotation-api'
import { useAuth } from '../auth/auth-context'
import { listMembers } from '../projects/project-api'
import type { ProjectClassInput } from '../projects/types'
import { retryRequest } from './adjudication'
import { ConfirmDialog, ErrorNotice } from './ConfirmDialog'
import { cancelRun, consensusKeys, getImageEvidence, retryResolution } from './consensus-api'
import type { ImageEvidence, RetryRequest } from './consensus-types'
import {
  PURPOSE_LABELS,
  RUN_STATUS_LABELS,
  candidateRegions,
  consensusPaths,
  errorCode,
  evidenceSources,
  humanize,
  latestProposalRun,
  personName,
  resolveLayout,
  type EvidenceLayout,
} from './consensus-view-model'
import { EvidenceStage } from './EvidenceStage'
import { RetryDialog } from './RetryDialog'
import {
  CandidateDecisions,
  EvidenceSourceTable,
  ResolutionHistory,
  ReviewTable,
  RunProvenance,
  WorkItemList,
} from './EvidenceTables'
import { SourceToggles } from './SourceToggles'
import { useEvidenceView } from './useEvidenceView'
import './consensus.css'

const RETRYABLE = ['review_required', 'resolved']
const CONFLICTS = ['version_conflict', 'resolution_config_conflict', 'resolution_in_progress', 'run_not_active']

type Dialog = { kind: 'retry' } | { kind: 'cancel'; runId: string; sequence: number }

export function ImageEvidencePage() {
  const { projectId = '', batchItemId = '' } = useParams()
  const { token, user } = useAuth()
  const queryClient = useQueryClient()
  const enabled = Boolean(projectId && batchItemId && token)
  const evidence = useQuery({
    queryKey: consensusKeys.evidence(projectId, batchItemId),
    queryFn: () => getImageEvidence(projectId, batchItemId, token!),
    enabled,
  })
  const bootstrap = useQuery({
    queryKey: ['annotation-workspace', projectId],
    queryFn: () => getWorkspaceBootstrap(projectId, token!),
    enabled,
  })
  const members = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listMembers(projectId, token!),
    enabled,
  })

  if (evidence.error instanceof ApiError && evidence.error.status === 403) {
    return <main className="page-container consensus-page"><div className="panel status-panel">Image evidence is available to project owners and managers.</div></main>
  }
  if (evidence.isLoading || bootstrap.isLoading) {
    return <main className="page-container consensus-page"><div className="panel status-panel">Loading image evidence…</div></main>
  }
  if (evidence.isError || bootstrap.isError) {
    return <main className="page-container consensus-page"><ErrorNotice error={evidence.error ?? bootstrap.error} /></main>
  }

  return <EvidenceView
    projectId={projectId}
    evidence={evidence.data!}
    classes={bootstrap.data!.classes}
    people={members.data?.items ?? []}
    userId={user?.id}
    token={token!}
    onChanged={() => Promise.all([
      queryClient.invalidateQueries({ queryKey: consensusKeys.evidence(projectId, batchItemId) }),
      queryClient.invalidateQueries({ queryKey: consensusKeys.queues(projectId) }),
    ])}
  />
}

function EvidenceView({ projectId, evidence, classes, people, userId, token, onChanged }: {
  projectId: string
  evidence: ImageEvidence
  classes: ProjectClassInput[]
  people: { user_id: string; display_name: string }[]
  userId: string | undefined
  token: string
  onChanged: () => Promise<unknown>
}) {
  const sources = useMemo(() => evidenceSources(evidence), [evidence])
  const view = useEvidenceView(sources)
  const [layoutChoice, setLayoutChoice] = useState<EvidenceLayout | null>(null)
  const [width, setWidth] = useState(() => window.innerWidth)
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    const resize = () => setWidth(window.innerWidth)
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])

  const handled = async (error: unknown) => {
    if (CONFLICTS.includes(errorCode(error) ?? '')) await onChanged()
  }
  const retry = useMutation({
    mutationFn: (body: RetryRequest) => retryResolution(projectId, evidence.batch_item_id, body, token),
    onSuccess: async (run) => {
      setDialog(null)
      setNotice(`Run ${run.sequence} was queued.`)
      await onChanged()
    },
    onError: handled,
  })
  const cancel = useMutation({
    mutationFn: ({ runId, rationale }: { runId: string; rationale: string }) => cancelRun(projectId, runId, rationale, token),
    onSuccess: async (run) => {
      setDialog(null)
      setNotice(`Run ${run.sequence} is ${RUN_STATUS_LABELS[run.status].toLowerCase()}.`)
      await onChanged()
    },
    onError: handled,
  })

  const taskType = evidence.task_type
  const latest = latestProposalRun(evidence)
  const activeRuns = evidence.runs.filter((run) => run.status === 'queued' || run.status === 'running')
  const foreignLease = evidence.work_items.find((item) => item.lease && item.lease.holder_id !== userId)?.lease
  const layout = resolveLayout(layoutChoice, width, view.shown.length)
  const regions = view.showRegions ? candidateRegions(latest?.proposal ?? null) : []
  const geometric = taskType !== 'classification'
  const retryBlocked = !RETRYABLE.includes(evidence.status) || activeRuns.length > 0 || Boolean(foreignLease)

  return <main className="page-container consensus-page">
    <div className="page-heading">
      <div>
        <Link className="back-link back-link--flow" to={consensusPaths.queue(projectId)}><ArrowLeft size={17} /> Consensus review queue</Link>
        <p className="eyebrow">{PURPOSE_LABELS[evidence.purpose]} · image {humanize(evidence.status).toLowerCase()}</p>
        <h1>{evidence.media.relative_path}</h1>
        <p className="muted">Named evidence for owners and managers. The proposal is the resolver&apos;s estimate from these submissions and can still need a human decision.</p>
      </div>
      <div className="consensus-actions">
        <Button variant="secondary" disabled={retryBlocked} onClick={() => setDialog({ kind: 'retry' })}><RotateCcw size={16} /> Retry resolution</Button>
        {activeRuns.map((run) => <Button key={run.id} variant="secondary" disabled={Boolean(foreignLease)} onClick={() => setDialog({ kind: 'cancel', runId: run.id, sequence: run.sequence })}><Ban size={16} /> Cancel run {run.sequence}</Button>)}
      </div>
    </div>
    {foreignLease && <p className="consensus-note" role="status">{personName(foreignLease.holder_id, people, userId)} is editing a case of this image, so retry and cancellation wait until the lease is released or expires.</p>}
    {!RETRYABLE.includes(evidence.status) && <p className="consensus-note">Retry is possible once the image needs a decision or is resolved.</p>}
    {notice && <p className="consensus-note" role="status">{notice}</p>}

    <section className="consensus-section" aria-labelledby="comparison-heading">
      <h2 id="comparison-heading">Evidence comparison</h2>
      {geometric ? <div className="evidence-compare">
        <SourceToggles
          sources={sources}
          visible={view.visible}
          onToggle={view.toggle}
          onHideAll={view.hideAll}
          regions={{ checked: view.showRegions, onChange: view.setShowRegions }}
          alpha={taskType === 'segmentation' ? { value: view.alpha, onChange: view.setAlpha } : undefined}
          layout={{ value: layout, onChange: setLayoutChoice }}
        />
        <div className={`evidence-stages evidence-stages--${layout}`}>
          {layout === 'overlay'
            ? <EvidenceStage label={view.shown.length ? `${view.shown.length} sources overlaid` : 'Image only'} media={evidence.media} sources={view.shown} regions={regions} classes={classes} alpha={view.alpha} />
            : view.shown.map((source) => <EvidenceStage key={source.id} label={source.label} media={evidence.media} sources={[source]} regions={regions} classes={classes} alpha={view.alpha} />)}
          {layout === 'side-by-side' && !view.shown.length && <p className="muted">Every source is hidden. Turn one on to compare.</p>}
        </div>
      </div> : <>
        <p className="muted">Classification labels have no geometry; compare them in the tables below.</p>
        <EvidenceStage label="Image" media={evidence.media} sources={[]} regions={[]} classes={classes} alpha={view.alpha} />
      </>}
    </section>

    <section className="consensus-section" aria-labelledby="table-heading">
      <h2 id="table-heading">Evidence table</h2>
      <EvidenceSourceTable sources={sources} classes={classes} />
      <ReviewTable evidence={evidence} classes={classes} />
    </section>

    <section className="consensus-section" aria-labelledby="decisions-heading">
      <h2 id="decisions-heading">Latest proposal{latest ? ` (run ${latest.sequence})` : ''}</h2>
      <CandidateDecisions evidence={evidence} run={latest} taskType={taskType} classes={classes} />
    </section>

    <section className="consensus-section" aria-labelledby="cases-heading">
      <h2 id="cases-heading">Cases</h2>
      <WorkItemList evidence={evidence} projectId={projectId} people={people} userId={userId} />
    </section>

    <section className="consensus-section" aria-labelledby="runs-heading">
      <h2 id="runs-heading">Runs and provenance</h2>
      <RunProvenance runs={evidence.runs} people={people} userId={userId} />
    </section>

    <section className="consensus-section" aria-labelledby="history-heading">
      <h2 id="history-heading">Resolution history</h2>
      <ResolutionHistory resolutions={evidence.resolutions} people={people} userId={userId} />
    </section>

    {dialog?.kind === 'retry' && <RetryDialog
      projectId={projectId}
      evidence={evidence}
      token={token}
      pending={retry.isPending}
      error={retry.error}
      onConfirm={(rationale, configuration) => retry.mutate(retryRequest(evidence.versions, rationale, configuration))}
      onCancel={() => { setDialog(null); retry.reset() }}
    />}
    {dialog?.kind === 'cancel' && <ConfirmDialog
      title={`Cancel run ${dialog.sequence}`}
      effect="This cancels the run. Its evidence is kept and the image moves to an owner or manager for a decision."
      confirmLabel="Cancel the run"
      rationale="required"
      pending={cancel.isPending}
      error={cancel.error}
      onConfirm={(rationale) => cancel.mutate({ runId: dialog.runId, rationale })}
      onCancel={() => { setDialog(null); cancel.reset() }}
    />}
  </main>
}
