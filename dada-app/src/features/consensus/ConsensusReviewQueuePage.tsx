import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

export function ConsensusReviewQueuePage() {
  const { projectId = '' } = useParams()

  return (
    <main className="centered-status">
      <div>
        <p className="eyebrow">Consensus review</p>
        <h1>Not available yet</h1>
        <p>
          Items needing manual review appear here once the API delivers
          resolution and adjudication endpoints.
        </p>
        <Link to={`/projects/${projectId}/activity`}>
          <ArrowLeft size={16} aria-hidden="true" /> Back to project activity
        </Link>
      </div>
    </main>
  )
}
