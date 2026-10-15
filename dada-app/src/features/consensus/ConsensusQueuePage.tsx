import { ArrowLeft, Gavel, Images } from 'lucide-react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { getCapabilities } from '../../api/capabilities'
import { Button } from '../../components/ui/Button'
import { getWorkspaceBootstrap } from '../annotation/annotation-api'
import { useAuth } from '../auth/auth-context'
import { listBatches } from '../projects/batch-api'
import { listMembers } from '../projects/project-api'
import type { AnnotationBatch } from '../projects/types'
import { ErrorNotice } from './ConfirmDialog'
import { consensusKeys, listResolutionQueue } from './consensus-api'
import type { ResolutionQueueFilters, ReviewReason, WorkItemStatus } from './consensus-types'
import {
  AGE_OPTIONS,
  DEFAULT_QUEUE_FILTERS,
  REASONS,
  REASON_LABELS,
  WORK_ITEM_STATUSES,
  WORK_ITEM_STATUS_LABELS,
  batchOptionLabel,
  consensusBatches,
  consensusPaths,
  defaultBatchId,
  formatAge,
  formatTime,
  personName,
  queueMetricsSummary,
  reasonLabel,
  resolverText,
  reviewCountText,
  scopeLabel,
  shortId,
} from './consensus-view-model'
import './consensus.css'

export function ConsensusQueuePage() {
  const { projectId = '' } = useParams()
  const { token, user } = useAuth()
  const [batchChoice, setBatchChoice] = useState<string | null>(null)
  const [filters, setFilters] = useState<ResolutionQueueFilters>(DEFAULT_QUEUE_FILTERS)
  const enabled = Boolean(projectId && token)

  const bootstrap = useQuery({
    queryKey: ['annotation-workspace', projectId],
    queryFn: () => getWorkspaceBootstrap(projectId, token!),
    enabled,
  })
  const batches = useQuery({
    queryKey: ['project-batches', projectId, 'all'],
    queryFn: () => allBatches(projectId, token!),
    enabled,
  })
  const members = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listMembers(projectId, token!),
    enabled,
  })
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getCapabilities, staleTime: Infinity })

  const batchId = batchChoice ?? defaultBatchId(batches.data ?? [])
  const queue = useInfiniteQuery({
    queryKey: consensusKeys.queue(projectId, batchId ?? '', filters),
    queryFn: ({ pageParam }) => listResolutionQueue(projectId, batchId!, filters, token!, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: Boolean(enabled && batchId),
  })

  const forbidden = [batches.error, queue.error].some((error) => error instanceof ApiError && error.status === 403)
  const heading = <div className="page-heading">
    <div>
      <Link className="back-link back-link--flow" to={`/projects/${projectId}/batches`}><ArrowLeft size={17} /> Annotation batches</Link>
      <p className="eyebrow">{bootstrap.data?.project.name}</p>
      <h1>Consensus review queue</h1>
      <p className="muted">Cases where the resolver could not settle an image or one of its objects. The resolver proposes a best estimate from the submissions; an owner or manager decides what it could not.</p>
    </div>
  </div>

  if (forbidden) {
    return <main className="page-container consensus-page">{heading}<div className="panel status-panel">The consensus review queue is available to project owners and managers.</div></main>
  }
  if (batches.isLoading || bootstrap.isLoading) {
    return <main className="page-container consensus-page">{heading}<div className="panel status-panel">Loading consensus batches…</div></main>
  }
  if (batches.isError || bootstrap.isError) {
    return <main className="page-container consensus-page">{heading}<ErrorNotice error={batches.error ?? bootstrap.error} /></main>
  }

  const taskType = bootstrap.data!.project.task_type
  const classes = bootstrap.data!.classes
  const options = consensusBatches(batches.data ?? [])
  const strategies = capabilities.data?.consensus_pipelines[taskType]?.class_strategies.map((strategy) => strategy.id) ?? []
  const people = members.data?.items ?? []
  const items = queue.data?.pages.flatMap((page) => page.items) ?? []
  const states = filters.state ?? []
  const now = Date.now()

  function toggleState(state: WorkItemStatus) {
    setFilters((current) => {
      const selected = current.state ?? []
      return { ...current, state: selected.includes(state) ? selected.filter((entry) => entry !== state) : [...selected, state] }
    })
  }

  return <main className="page-container consensus-page">
    {heading}
    {!batchId ? <div className="panel status-panel">No consensus batch of this project has started yet.</div> : <>
      <form className="panel queue-filters-panel" aria-label="Queue filters" onSubmit={(event) => event.preventDefault()}>
        <label className="queue-filter">Batch
          <select value={batchId} onChange={(event) => setBatchChoice(event.target.value)}>
            {options.map((batch) => <option key={batch.id} value={batch.id}>{batchOptionLabel(batch)}</option>)}
          </select>
        </label>
        <fieldset className="queue-filter queue-filter--states">
          <legend>State</legend>
          {WORK_ITEM_STATUSES.map((state) => <label key={state}>
            <input type="checkbox" checked={states.includes(state)} disabled={states.length === 1 && states.includes(state)} onChange={() => toggleState(state)} />
            {WORK_ITEM_STATUS_LABELS[state]}
          </label>)}
        </fieldset>
        <label className="queue-filter">Reason
          <select value={filters.reason ?? ''} onChange={(event) => setFilters({ ...filters, reason: (event.target.value || undefined) as ReviewReason | undefined })}>
            <option value="">All reasons</option>
            {REASONS.map((reason) => <option key={reason} value={reason}>{REASON_LABELS[reason]}</option>)}
          </select>
        </label>
        <label className="queue-filter">Class strategy
          <select value={filters.classStrategy ?? ''} onChange={(event) => setFilters({ ...filters, classStrategy: event.target.value || undefined })}>
            <option value="">All strategies</option>
            {strategies.map((strategy) => <option key={strategy} value={strategy}>{strategy}</option>)}
          </select>
        </label>
        <label className="queue-filter">Age
          <select
            value={String(AGE_OPTIONS.findIndex((option) => option.seconds === filters.minAgeSeconds))}
            onChange={(event) => setFilters({ ...filters, minAgeSeconds: AGE_OPTIONS[Number(event.target.value)]?.seconds })}
          >
            {AGE_OPTIONS.map((option, index) => <option key={option.label} value={index}>{option.label}</option>)}
          </select>
        </label>
      </form>

      {queue.isError && <ErrorNotice error={queue.error} />}
      {queue.isLoading && <div className="panel status-panel">Loading cases…</div>}
      {queue.isSuccess && !items.length && <div className="panel status-panel">No cases match these filters.</div>}
      <ul className="queue-rows" aria-label="Resolution cases">
        {items.map((item) => <li key={item.work_item_id} className="panel queue-row">
          <div className="queue-row__title">
            <strong>{item.relative_path}</strong>
            <span className="consensus-badge">{scopeLabel(item.scope)}{item.scope === 'candidate' ? ` ${shortId(item.candidate_key)}` : ''}</span>
            <span className={`consensus-status consensus-status--${item.status}`}>{WORK_ITEM_STATUS_LABELS[item.status]}</span>
          </div>
          <dl className="queue-row__facts">
            <div><dt>Reason</dt><dd>{reasonLabel(item.reason)}</dd></div>
            <div><dt>Evidence</dt><dd>{item.submissions} submissions · {reviewCountText(item)}</dd></div>
            <div><dt>Metrics</dt><dd>{queueMetricsSummary(item.metrics, taskType, classes)}</dd></div>
            <div><dt>Resolver</dt><dd>{resolverText(item)}</dd></div>
            <div><dt>Age</dt><dd>{formatAge(item.created_at, now)}</dd></div>
            <div><dt>Lease</dt><dd>{item.lease_holder_id ? `Being edited by ${personName(item.lease_holder_id, people, user?.id)} until ${formatTime(item.lease_expires_at)}` : 'Not being edited'}</dd></div>
          </dl>
          <div className="queue-row__links">
            <Link className="button button--secondary" to={consensusPaths.image(projectId, item.batch_item_id)}><Images size={16} /> Open image evidence</Link>
            {item.status === 'review_required' && <Link className="button button--primary" to={consensusPaths.workItem(projectId, item.work_item_id, item.batch_item_id)}><Gavel size={16} /> Decide this case</Link>}
          </div>
        </li>)}
      </ul>
      {queue.hasNextPage && <Button variant="secondary" disabled={queue.isFetchingNextPage} onClick={() => void queue.fetchNextPage()}>{queue.isFetchingNextPage ? 'Loading…' : 'Load more cases'}</Button>}
    </>}
  </main>
}

async function allBatches(projectId: string, token: string) {
  const items: AnnotationBatch[] = []
  let cursor: string | undefined
  do {
    const page = await listBatches(projectId, token, cursor)
    items.push(...page.items)
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return items
}
