import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

export function ConsensusReviewPage() {
  const { projectId = '' } = useParams()

  return (
    <main className="centered-status">
      <div>
        <p className="eyebrow">Consensus review</p>
        <h1>Not available yet</h1>
        <p>
          Comparing independent submissions and adjudicating a canonical
          annotation requires API endpoints that are not implemented yet.
        </p>
        <Link to={`/projects/${projectId}/consensus`}>
          <ArrowLeft size={16} aria-hidden="true" /> Back to the review queue
        </Link>
      </div>
    </main>
  )
}
