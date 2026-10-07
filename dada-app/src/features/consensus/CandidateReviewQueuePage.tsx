import { ClipboardCheck } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { useAuth } from '../auth/auth-context'
import { listReviewAssignments } from './review-api'
import './consensus.css'

export function CandidateReviewQueuePage() {
  const { projectId = '' } = useParams()
  const { token } = useAuth()
  const queue = useQuery({ queryKey: ['candidate-review-queue', projectId], queryFn: () => listReviewAssignments(projectId, token!), enabled: Boolean(projectId && token), refetchInterval: 30_000 })
  if (queue.isLoading) return <div className="centered-status">Loading candidate reviews…</div>
  if (queue.isError) return <div className="centered-status">Candidate reviews are unavailable: {queue.error.message}</div>
  return <main className="consensus-page"><header className="page-heading"><div><Link to="/projects" className="back-link">Projects</Link><p className="eyebrow">My independent review work</p><h1>Candidate reviews</h1><p className="muted">Each assignment contains one image-level result or one candidate. Peer submissions and unrelated objects stay hidden.</p></div></header><section className="consensus-list">{queue.data?.items.map((item) => <article key={item.id} className="consensus-card"><div><strong>{item.relative_path}</strong><p>{item.scope === 'image' ? 'Image label review' : 'Candidate review'} · {item.status.replace('_', ' ')}</p></div><Link className="button button--secondary" to={`/projects/${projectId}/reviews/${item.id}`}><ClipboardCheck size={16} /> Open review</Link></article>)}{queue.data?.items.length === 0 && <p className="activity-empty">No candidate reviews are assigned to you.</p>}</section></main>
}
