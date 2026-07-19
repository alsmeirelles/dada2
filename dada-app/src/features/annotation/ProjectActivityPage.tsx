import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  Radio,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { useAuth } from '../auth/auth-context'
import { getProjectActivity } from './annotation-api'
import type { Iteration } from './types'
import { useProjectEvents } from './useProjectEvents'
import './activity.css'

export function ProjectActivityPage() {
  const { projectId = '' } = useParams()
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const activity = useQuery({
    queryKey: ['project-activity', projectId],
    queryFn: () => getProjectActivity(projectId, token!),
    enabled: Boolean(projectId && token),
    refetchInterval: (query) => {
      const status = query.state.data?.iterations.current_iteration?.status
      return status === 'training' || status === 'closing' || status === 'preparing' ? 5_000 : 30_000
    },
  })
  const handleEvent = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['project-activity', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['projects'] })
  }, [projectId, queryClient])
  const realtime = useProjectEvents(projectId, token, handleEvent)

  if (activity.isLoading) return <div className="centered-status">Loading project activity…</div>
  if (activity.isError) return <ActivityError error={activity.error} />
  if (!activity.data) return null

  const { project, iterations, statistics } = activity.data
  const current = iterations.current_iteration

  return (
    <main className="activity-page">
      <header className="activity-heading">
        <div>
          <Link to="/projects" className="back-link"><ArrowLeft size={17} /> Projects</Link>
          <p className="eyebrow">Active learning</p>
          <h1>{project.name}</h1>
          <p className="muted">Iteration progress, model training, and historical performance.</p>
        </div>
        <span className={`activity-live activity-live--${realtime}`}><Radio size={14} />{realtime === 'live' ? 'Live updates' : 'Polling fallback'}</span>
      </header>

      {current ? <CurrentIteration projectId={projectId} iteration={current} /> : (
        <section className="activity-hero activity-hero--complete"><CheckCircle2 /><div><p className="eyebrow">Project status</p><h2>No active iteration</h2><p>All scheduled work is complete or the next iteration has not started.</p></div></section>
      )}

      <section className="summary-grid" aria-label="Project totals">
        <Summary icon={<BarChart3 />} label="Dataset images" value={statistics.totals.images} />
        <Summary icon={<CheckCircle2 />} label="Annotated images" value={statistics.totals.annotated_images} />
        <Summary icon={<Activity />} label="Completed iterations" value={statistics.totals.iterations_completed} />
      </section>

      <section className="activity-panel">
        <div className="section-heading"><div><p className="eyebrow">History</p><h2>Iteration performance</h2></div></div>
        {statistics.iterations.length ? <MetricChart iterations={statistics.iterations} /> : <p className="activity-empty">Metrics appear after the first training cycle completes.</p>}
      </section>

      <section className="activity-panel">
        <div className="section-heading"><div><p className="eyebrow">Timeline</p><h2>Past iterations</h2></div></div>
        <div className="iteration-table-wrap">
          <table className="iteration-table">
            <caption className="sr-only">Iteration history</caption>
            <thead><tr><th scope="col">Iteration</th><th scope="col">Status</th><th scope="col">Annotations</th><th scope="col">Completed</th></tr></thead>
            <tbody>{iterations.items.map((iteration) => (
              <tr key={iteration.id}>
                <th scope="row">#{iteration.number}</th>
                <td><span className={`iteration-status iteration-status--${iteration.status}`}>{iteration.status}</span></td>
                <td>{iteration.completed_count} / {iteration.total_count}</td>
                <td>{iteration.completed_at ? formatDate(iteration.completed_at) : '—'}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </main>
  )
}

function CurrentIteration({ projectId, iteration }: { projectId: string; iteration: Iteration }) {
  const eta = useCountdown(iteration.eta_seconds)
  const progress = Math.max(0, Math.min(100, iteration.training_progress ?? 0))
  const annotating = iteration.status === 'annotating' || iteration.status === 'ready'
  const failed = iteration.status === 'failed'

  return (
    <section className={`activity-hero activity-hero--${iteration.status}`}>
      <div className="activity-hero__icon">{failed ? <AlertTriangle /> : annotating ? <Activity /> : <LoaderCircle />}</div>
      <div className="activity-hero__content">
        <p className="eyebrow">Iteration {iteration.number}</p>
        <h2>{iterationTitle(iteration.status)}</h2>
        <p>{iterationDescription(iteration.status)}</p>
        {iteration.status === 'training' && <div className="training-progress"><div><span>Model training</span><strong>{Math.round(progress)}%</strong></div><progress max="100" value={progress} /></div>}
        <div className="iteration-counts"><span><strong>{iteration.completed_count}</strong> completed</span><span><strong>{iteration.available_count}</strong> available</span><span><strong>{iteration.leased_count}</strong> in progress</span></div>
      </div>
      <div className="activity-hero__aside">
        {(iteration.status === 'training' || iteration.status === 'preparing' || iteration.status === 'closing') && <div className="eta"><Clock3 /><span>Estimated time</span><strong>{eta === null ? 'Calculating…' : formatDuration(eta)}</strong></div>}
        {annotating && <Link to={`/projects/${projectId}/annotate`} className="button button--primary">Open annotation workspace</Link>}
        {failed && <p>Review the API worker logs or retry from project administration.</p>}
      </div>
    </section>
  )
}

function MetricChart({ iterations }: { iterations: Array<{ iteration_id: string; iteration_number: number; annotated_images: number; metrics: Record<string, number> }> }) {
  const metricName = useMemo(() => iterations.flatMap((item) => Object.keys(item.metrics))[0], [iterations])
  const values = iterations.map((item) => metricName ? item.metrics[metricName] ?? 0 : item.annotated_images)
  const maximum = Math.max(...values, 1)
  return <div className="metric-chart"><div className="metric-chart__label">{metricName ?? 'Annotated images'}</div><div className="metric-bars">{iterations.map((item, index) => <div className="metric-bar" key={item.iteration_id}><div style={{ height: `${Math.max(3, (values[index]! / maximum) * 100)}%` }} title={`${values[index]}`} /><strong>{formatMetric(values[index]!)}</strong><span>#{item.iteration_number}</span></div>)}</div></div>
}

function Summary({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return <article className="summary-card"><span>{icon}</span><div><strong>{value.toLocaleString()}</strong><p>{label}</p></div></article>
}

function ActivityError({ error }: { error: Error }) {
  return <div className="centered-status"><div><AlertTriangle size={32} /><h1>Activity unavailable</h1><p>{error instanceof ApiError && error.status === 404 ? 'The iteration statistics endpoints are not available yet.' : error.message}</p><Link to="/projects">Return to projects</Link></div></div>
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

function iterationTitle(status: Iteration['status']) {
  return { preparing: 'Preparing the next batch', annotating: 'Annotation in progress', closing: 'Finalizing annotations', training: 'Training the next model', ready: 'Ready for annotation', failed: 'Iteration needs attention' }[status]
}

function iterationDescription(status: Iteration['status']) {
  return { preparing: 'The API is selecting the most informative images for the next cycle.', annotating: 'Annotators can claim available images from the shared queue.', closing: 'The API is validating the completed batch before training.', training: 'GPU workers are training and evaluating the next model.', ready: 'A new batch of images is available for annotation.', failed: 'The API reported a processing failure for this iteration.' }[status]
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

function formatMetric(value: number) {
  return value > 0 && value <= 1 ? value.toFixed(3) : value.toLocaleString(undefined, { maximumFractionDigits: 3 })
}
