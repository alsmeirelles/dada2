import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  Clock3,
  Download,
  LoaderCircle,
  Radio,
  RotateCcw,
  Target,
} from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { getCapabilities } from '../../api/capabilities'
import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { METRIC_LABELS } from '../projects/learning-settings'
import { listMembers } from '../projects/project-api'
import type { CompletionReason, Project, TaskType } from '../projects/types'
import {
  downloadDataset,
  getProjectActivity,
  getQuality,
  retryIteration,
} from './annotation-api'
import type {
  AgreementMetric,
  Evaluation,
  ExportFormat,
  Iteration,
  QualityReport,
} from './types'
import { useProjectEvents } from './useProjectEvents'
import './activity.css'

const COMPLETION_TEXT: Record<CompletionReason, string> = {
  max_iterations: 'The iteration limit was reached.',
  metric_target: 'The validation metric reached its target.',
  pool_exhausted: 'The training pool has no eligible images left.',
}

const AGREEMENT_LABELS: Record<AgreementMetric, string> = {
  winner_support: 'Share of votes for the winning class',
  box_iou: 'Median pairwise box IoU',
  mask_iou: 'Median pairwise mask IoU',
  mask_dice: 'Median pairwise mask Dice',
}

const NOT_ENOUGH_DATA = 'Not enough data'

export function ProjectActivityPage() {
  const { projectId = '' } = useParams()
  const { token, user } = useAuth()
  const queryClient = useQueryClient()
  const activity = useQuery({
    queryKey: ['project-activity', projectId],
    queryFn: () => getProjectActivity(projectId, token!),
    enabled: Boolean(projectId && token),
    refetchInterval: (query) => {
      const status = query.state.data?.iterations.current_iteration?.status
      return status === 'training' || status === 'consolidating' ? 5_000 : 30_000
    },
  })
  const members = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listMembers(projectId, token!),
    enabled: Boolean(projectId && token),
  })
  const self = members.data?.items.find((member) => member.user_id === user?.id)
  const canManage = Boolean(user?.is_administrator || self?.role === 'owner' || self?.role === 'manager')
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getCapabilities, staleTime: Infinity })
  const handleEvent = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['project-activity', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['projects'] })
  }, [projectId, queryClient])
  const realtime = useProjectEvents(projectId, token, handleEvent)
  const retry = useMutation({
    mutationFn: (iterationId: string) => retryIteration(projectId, iterationId, token!),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['project-activity', projectId] }),
  })

  if (activity.isLoading) return <div className="centered-status">Loading project activity…</div>
  if (activity.isError) return <ActivityError error={activity.error} />
  if (!activity.data) return null

  const { project, iterations, statistics } = activity.data
  const current = iterations.current_iteration
  const solution = capabilities.data?.active_learning_solutions.find((item) => item.id === project.learning_solution)

  return (
    <main className="activity-page">
      <header className="activity-heading">
        <div>
          <Link to="/projects" className="back-link"><ArrowLeft size={17} /> Projects</Link>
          <p className="eyebrow">Acquisition loop</p>
          <h1>{project.name}</h1>
          <p className="muted">Iteration progress, target-model evaluations, quality, and the dataset export.</p>
        </div>
        <span className={`activity-live activity-live--${realtime}`}><Radio size={14} />{realtime === 'live' ? 'Live updates' : 'Polling fallback'}</span>
      </header>

      <ActivityCard
        project={project}
        iteration={current}
        canManage={canManage}
        retrying={retry.isPending}
        retryError={retry.error}
        onRetry={(iterationId) => retry.mutate(iterationId)}
      />

      <section className="summary-grid" aria-label="Acquisition summary">
        <Summary icon={<Activity />} label="Completed acquisition iterations" value={statistics.max_acquisition_iterations === null ? `${statistics.completed_iterations}` : `${statistics.completed_iterations} of ${statistics.max_acquisition_iterations}`} />
        <Summary icon={<BarChart3 />} label="Acquisition" value={statistics.acquisition_strategy === 'random' ? 'Random' : solution?.display_name ?? project.learning_solution ?? 'Active learning'} />
        <Summary icon={<Target />} label={statistics.metric_target === null ? 'Evaluation metric' : `Evaluation metric, target ${statistics.metric_target}`} value={statistics.evaluation_metric ? METRIC_LABELS[statistics.evaluation_metric] : 'None'} />
      </section>

      <section className="activity-panel" aria-labelledby="evaluations-title">
        <div className="section-heading"><div><p className="eyebrow">Target model</p><h2 id="evaluations-title">Evaluations</h2></div></div>
        {statistics.evaluations.length
          ? <Evaluations evaluations={statistics.evaluations} />
          : <p className="activity-empty">{statistics.acquisition_strategy === 'random' ? 'Random acquisition trains no model, so there is nothing to evaluate.' : 'Evaluations appear once the target model is first measured.'}</p>}
      </section>

      <section className="activity-panel" aria-labelledby="iterations-title">
        <div className="section-heading"><div><p className="eyebrow">Timeline</p><h2 id="iterations-title">Iterations</h2></div></div>
        {iterations.items.length ? <div className="iteration-table-wrap">
          <table className="iteration-table">
            <caption className="sr-only">Iteration history</caption>
            <thead><tr><th scope="col">Iteration</th><th scope="col">Status</th><th scope="col">Selected</th><th scope="col">Resolved</th><th scope="col">Completed</th></tr></thead>
            <tbody>{iterations.items.map((iteration) => (
              <tr key={iteration.id}>
                <th scope="row">#{iteration.number}{iteration.purpose === 'final_evaluation' ? ' · final evaluation' : ''}</th>
                <td><span className={`iteration-status iteration-status--${iteration.status}`}>{iteration.status}</span></td>
                <td>{iteration.selected_count ?? '—'}{iteration.attempt > 1 ? ` · attempt ${iteration.attempt}` : ''}</td>
                <td>{iteration.batch_id ? `${iteration.resolved_count} / ${iteration.total_count}` : '—'}</td>
                <td>{iteration.completed_at ? formatDate(iteration.completed_at) : '—'}</td>
              </tr>
            ))}</tbody>
          </table>
        </div> : <p className="activity-empty">The first iteration opens once every validation, test, and first-training image has an accepted resolution.</p>}
      </section>

      {canManage && <QualitySection projectId={projectId} />}
      {canManage && <ExportSection projectId={projectId} taskType={project.task_type} />}
    </main>
  )
}

function ActivityCard({ project, iteration, canManage, retrying, retryError, onRetry }: {
  project: Project
  iteration: Iteration | null
  canManage: boolean
  retrying: boolean
  retryError: Error | null
  onRetry: (iterationId: string) => void
}) {
  const eta = useCountdown(iteration?.eta_seconds)
  if (project.status === 'completed') {
    return <section className="activity-hero activity-hero--complete"><CheckCircle2 /><div><p className="eyebrow">Acquisition complete</p><h2>The loop has ended</h2><p>{project.completion_reason ? COMPLETION_TEXT[project.completion_reason] : 'Every scheduled iteration is complete.'} The annotated dataset can be exported below.</p></div></section>
  }
  if (!iteration) {
    return <section className="activity-hero activity-hero--waiting"><div className="activity-hero__icon"><Clock3 /></div><div className="activity-hero__content"><p className="eyebrow">Waiting</p><h2>No acquisition iteration yet</h2><p>The loop starts once every validation, test, and first-training image has an accepted resolution.</p></div></section>
  }
  const failed = iteration.status === 'failed'
  const working = iteration.status === 'training' || iteration.status === 'consolidating'
  return (
    <section className={`activity-hero activity-hero--${iteration.status}`} aria-labelledby="activity-title">
      <div className="activity-hero__icon">{failed ? <AlertTriangle /> : working ? <LoaderCircle /> : <Activity />}</div>
      <div className="activity-hero__content">
        <p className="eyebrow">{iteration.purpose === 'final_evaluation' ? 'Final evaluation' : `Iteration ${iteration.number}`}{iteration.attempt > 1 ? ` · attempt ${iteration.attempt}` : ''}</p>
        <h2 id="activity-title">{activityTitle(iteration, project.task_type)}</h2>
        <p>{activityDescription(iteration, project.task_type)}</p>
        {failed && <p className="activity-failure" role="alert">{iteration.failure_detail ?? iteration.failure_code ?? 'The API reported no reason.'}</p>}
        {iteration.batch_id && <div className="iteration-counts"><span><strong>{iteration.submitted_assignment_count} / {iteration.total_assignment_count}</strong> submissions</span><span><strong>{iteration.resolved_count} / {iteration.total_count}</strong> resolved</span><span><strong>{iteration.available_count}</strong> available</span></div>}
      </div>
      <div className="activity-hero__aside">
        {eta !== null && <div className="eta"><Clock3 /><span>Estimated time</span><strong>{formatDuration(eta)}</strong></div>}
        {iteration.status === 'annotating' && <Link to={`/projects/${project.id}/annotate`} className="button button--primary">Open annotation workspace</Link>}
        {iteration.status === 'preparing' && canManage && <Link to={`/projects/${project.id}/batches`} className="button button--primary">Start the batch</Link>}
        {canManage && iteration.review_required_count > 0 && <Link to={`/projects/${project.id}/consensus`} className="button button--secondary">Review {iteration.review_required_count} consensus item{iteration.review_required_count === 1 ? '' : 's'}</Link>}
        {failed && canManage && <Button onClick={() => onRetry(iteration.id)} disabled={retrying}><RotateCcw size={16} /> {retrying ? 'Retrying…' : 'Retry iteration'}</Button>}
        {failed && !canManage && <p>An owner or manager can retry this iteration.</p>}
        {failed && retryError && <p role="alert">{retryError.message}</p>}
      </div>
    </section>
  )
}

/** The activity card's title (A7-01). */
function activityTitle(iteration: Iteration, taskType: TaskType) {
  if (iteration.status === 'training') {
    if (iteration.strategy === 'random') return 'Selecting randomly'
    if (iteration.stage === 'evaluating') return 'Evaluating'
    if (iteration.stage === 'selecting') return taskType === 'classification' ? 'Selecting images' : 'Selecting objects'
    return 'Training'
  }
  if (iteration.status === 'ready') return iteration.purpose === 'final_evaluation' ? 'Final evaluation complete' : 'Iteration complete'
  return { preparing: 'Next batch ready to start', annotating: 'Annotation in progress', consolidating: 'Resolving annotations', failed: 'Iteration failed' }[iteration.status]
}

function activityDescription(iteration: Iteration, taskType: TaskType) {
  const targets = taskType === 'classification' ? 'images' : 'objects'
  if (iteration.status === 'training') {
    if (iteration.strategy === 'random') return 'The next batch is drawn at random from the eligible training images.'
    if (iteration.stage === 'evaluating') return iteration.purpose === 'final_evaluation' ? 'The target model is being measured on the validation and test sets.' : 'The target model is being measured on the validation set.'
    if (iteration.stage === 'selecting') return `The solution is choosing the most useful ${targets} to annotate next.`
    return 'The solution is training on the accepted annotations.'
  }
  return {
    preparing: 'The batch is selected. An owner or manager starts it from the annotation batches.',
    annotating: 'Annotators are working on their assignments.',
    consolidating: 'Submitted annotations are being resolved; some may need review.',
    ready: iteration.purpose === 'final_evaluation' ? 'The target model was measured on the validation and test sets.' : 'Every item of this batch has an accepted resolution.',
    failed: 'The iteration stopped with this reason:',
  }[iteration.status]
}

function Evaluations({ evaluations }: { evaluations: Evaluation[] }) {
  const validation = evaluations.filter((item) => item.split === 'validation')
  return <>
    {validation.length > 0 && <div className="metric-chart" aria-hidden="true">
      <div className="metric-chart__label">{METRIC_LABELS[validation[0]!.metric]} on validation</div>
      <div className="metric-bars">{validation.map((item) => <div className="metric-bar" key={`${item.iteration}-${item.created_at}`}><div style={{ height: `${Math.max(3, item.value * 100)}%` }} /><strong>{item.value.toFixed(3)}</strong><span>#{item.iteration}</span></div>)}</div>
    </div>}
    <div className="iteration-table-wrap">
      <table className="iteration-table">
        <caption className="sr-only">Target-model evaluations</caption>
        <thead><tr><th scope="col">Iteration</th><th scope="col">Set</th><th scope="col">Metric</th><th scope="col">Value</th><th scope="col">Measured</th></tr></thead>
        <tbody>{evaluations.map((item) => <tr key={`${item.iteration}-${item.split}-${item.created_at}`}>
          <th scope="row">#{item.iteration}</th>
          <td>{item.split === 'validation' ? 'Validation' : 'Test'}</td>
          <td>{METRIC_LABELS[item.metric]}</td>
          <td>{item.value.toFixed(3)}</td>
          <td>{formatDate(item.created_at)}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </>
}

/** Manager-only quality measures; hidden values read `Not enough data` (A7-02). */
function QualitySection({ projectId }: { projectId: string }) {
  const { token } = useAuth()
  const quality = useQuery({
    queryKey: ['project-quality', projectId],
    queryFn: () => getQuality(projectId, token!),
    enabled: Boolean(token),
  })
  return <section className="activity-panel" aria-labelledby="quality-title">
    <div className="section-heading"><div><p className="eyebrow">Owners and managers</p><h2 id="quality-title">Quality</h2></div></div>
    {quality.isLoading && <p className="muted">Loading quality…</p>}
    {quality.isError && <p className="form-error" role="alert">Quality could not be loaded. {quality.error.message}</p>}
    {quality.data && <QualityTable report={quality.data} />}
  </section>
}

function QualityTable({ report }: { report: QualityReport }) {
  return <>
    <p className="muted">{report.resolved_items} of {report.total_items} items resolved. Values appear once {report.minimum_decisions} items are resolved, and a value based on fewer than {report.minimum_cell} observations stays hidden. These measures describe the project, never an annotator.</p>
    <div className="iteration-table-wrap">
      <table className="iteration-table">
        <caption className="sr-only">Annotation quality</caption>
        <thead><tr><th scope="col">Measure</th><th scope="col">Value</th><th scope="col">Based on</th></tr></thead>
        <tbody>
          <tr><th scope="row">Review rate</th><td>{percent(report.review_rate)}</td><td>Resolved items that needed reviewers or an expert</td></tr>
          <tr><th scope="row">Resolution rate</th><td>{percent(report.resolution_rate)}</td><td>Items with an accepted resolution, out of {report.total_items} not cancelled</td></tr>
          {report.agreement.map((entry) => <tr key={entry.metric}>
            <th scope="row">Agreement</th>
            <td>{entry.median === null ? NOT_ENOUGH_DATA : entry.median.toFixed(3)}</td>
            <td>{AGREEMENT_LABELS[entry.metric]}, over {entry.observations} first-round candidate{entry.observations === 1 ? '' : 's'}</td>
          </tr>)}
          {!report.agreement.length && <tr><th scope="row">Agreement</th><td>{NOT_ENOUGH_DATA}</td><td>Measured only on consensus items</td></tr>}
        </tbody>
      </table>
    </div>
  </>
}

function ExportSection({ projectId, taskType }: { projectId: string; taskType: TaskType }) {
  const { token } = useAuth()
  const [format, setFormat] = useState<ExportFormat>(taskType === 'classification' ? 'csv' : 'coco')
  const download = useMutation({ mutationFn: () => downloadDataset(projectId, format, token!) })
  return <section className="activity-panel" aria-labelledby="export-title">
    <div className="section-heading"><div><p className="eyebrow">Owners and managers</p><h2 id="export-title">Dataset export</h2></div></div>
    <p className="muted">A ZIP with every accepted resolution so far, split into training, validation, and test, with the images annotators saw and a provenance.json that records resolution versions, sources, and which images were labeled only in part.</p>
    <div className="export-actions">
      {taskType === 'classification'
        ? <p className="muted">Classification exports a CSV with one column per class.</p>
        : <label className="field" htmlFor="export-format">Format
          <select id="export-format" value={format} onChange={(event) => setFormat(event.target.value as ExportFormat)}>
            <option value="coco">COCO</option>
            <option value="yolo">YOLO (normalized)</option>
          </select>
        </label>}
      <Button onClick={() => download.mutate()} disabled={download.isPending}><Download size={16} /> {download.isPending ? 'Preparing…' : 'Download dataset'}</Button>
    </div>
    {download.isError && <p className="form-error" role="alert">The export could not be downloaded. {download.error.message}</p>}
  </section>
}

function Summary({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <article className="summary-card"><span>{icon}</span><div><strong>{value}</strong><p>{label}</p></div></article>
}

function ActivityError({ error }: { error: Error }) {
  return <div className="centered-status"><div><AlertTriangle size={32} /><h1>Activity unavailable</h1><p>{error instanceof ApiError && error.status === 404 ? 'This project does not exist.' : error.message}</p><Link to="/projects">Return to projects</Link></div></div>
}

function useCountdown(initial?: number | null) {
  const [remaining, setRemaining] = useState<number | null>(initial ?? null)
  useEffect(() => setRemaining(initial ?? null), [initial])
  useEffect(() => {
    if (remaining === null || remaining <= 0) return
    const timer = window.setInterval(() => setRemaining((value) => value === null ? null : Math.max(0, value - 1)), 1_000)
    return () => window.clearInterval(timer)
  }, [remaining])
  return remaining
}

function percent(value: number | null) {
  return value === null ? NOT_ENOUGH_DATA : `${(value * 100).toFixed(1)}%`
}

function formatDuration(seconds: number) {
  if (seconds < 60) return `${seconds}s`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.ceil((seconds % 3600) / 60)
  return hours ? `${hours}h ${minutes}m` : `${minutes} min`
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
