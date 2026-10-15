import { ArrowLeft, ClipboardCheck } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { useAuth } from '../auth/auth-context'
import { listReviewAssignments, reviewKeys } from './review-api'
import type { ReviewStatus } from './review-types'
import './review.css'

const STATUS_LABELS: Record<ReviewStatus, string> = {
  pending: 'Not started',
  in_progress: 'In progress',
  submitted: 'Submitted',
  cancelled: 'Cancelled',
}

export function CandidateReviewQueuePage() {
  const { projectId = '' } = useParams()
  const { token } = useAuth()
  const queue = useQuery({ queryKey: reviewKeys.queue(projectId), queryFn: () => listReviewAssignments(projectId, token!), enabled: Boolean(projectId && token), refetchInterval: 30_000 })
  if (queue.isLoading) return <div className="centered-status">Loading your reviews…</div>
  if (queue.isError) return <div className="centered-status">Your reviews are unavailable: {queue.error.message}</div>
  const counts = queue.data?.counts
  return <main className="review-page">
    <header className="review-heading">
      <Link to="/projects" className="back-link back-link--flow"><ArrowLeft size={17} /> Projects</Link>
      <p className="eyebrow">My independent review work</p>
      <h1>My reviews</h1>
      <p className="muted">Each review asks about one image or one region of an image. Nobody else's annotations, votes, or names are shown.</p>
      {counts && <p className="muted">{counts.pending} not started · {counts.in_progress} in progress · {counts.submitted} submitted</p>}
    </header>
    <section className="review-list" aria-label="My reviews">
      {queue.data?.items.map((item) => <article key={item.id} className="review-card">
        <div><strong>{item.relative_path}</strong><p>{item.scope === 'image' ? 'Image label review' : 'Object review'} · {STATUS_LABELS[item.status]}</p></div>
        <Link className="button button--secondary" to={`/projects/${projectId}/reviews/${item.id}`}><ClipboardCheck size={16} /> {item.status === 'submitted' ? 'View review' : 'Open review'}</Link>
      </article>)}
      {queue.data?.items.length === 0 && <p className="muted">No reviews are assigned to you in this project.</p>}
    </section>
  </main>
}
