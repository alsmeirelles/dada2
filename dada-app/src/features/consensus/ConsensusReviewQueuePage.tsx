import { AlertTriangle, CheckCircle2, Eye } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { useAuth } from '../auth/auth-context'
import { getResolutionQueue } from './consensus-api'
import './consensus.css'

export function ConsensusReviewQueuePage() {
  const { projectId = '' } = useParams()
  const { token } = useAuth()
  const queue = useQuery({ queryKey: ['resolution-queue', projectId], queryFn: () => getResolutionQueue(projectId, token!), enabled: Boolean(projectId && token) })
  if (queue.isLoading) return <div className="centered-status">Loading consensus review…</div>
  if (queue.isError) return <div className="centered-status">Consensus review is unavailable: {queue.error.message}</div>
  return <main className="consensus-page"><header className="page-heading"><div><p className="eyebrow">Manager review</p><h1>Consensus resolution</h1><p className="muted">Review ambiguous annotations without changing the immutable raw submissions.</p></div></header><section className="consensus-list">{queue.data?.items.map((item) => <article key={item.batch_item_id} className="consensus-card"><div><strong>{item.relative_path}</strong><p>{item.submission_count} of {item.required_submission_count} submissions · {item.status.replace('_', ' ')}</p>{item.review_reason && <p className="consensus-warning"><AlertTriangle size={15} /> {item.review_reason}</p>}</div><Link className="button button--secondary" to={`/projects/${projectId}/consensus/${item.batch_item_id}`}>{item.status === 'review_required' ? <Eye size={16} /> : <CheckCircle2 size={16} />} Review</Link></article>)}{queue.data?.items.length === 0 && <p className="activity-empty">No consensus items need review.</p>}</section></main>
}
