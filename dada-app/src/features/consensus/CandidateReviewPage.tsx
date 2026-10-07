import { AlertTriangle, Check, Save } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { getReviewAssignment, saveReviewDraft, submitReview } from './review-api'
import './consensus.css'

function recoveryKey(projectId: string, assignmentId: string) {
  return `dada:candidate-review:${projectId}:${assignmentId}`
}

export function CandidateReviewPage() {
  const { projectId = '', reviewAssignmentId = '' } = useParams()
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [value, setValue] = useState('{}')
  const [version, setVersion] = useState(1)
  const [parseError, setParseError] = useState<string | null>(null)
  const review = useQuery({ queryKey: ['candidate-review', projectId, reviewAssignmentId], queryFn: () => getReviewAssignment(projectId, reviewAssignmentId, token!), enabled: Boolean(projectId && reviewAssignmentId && token) })

  useEffect(() => {
    if (!review.data) return
    const recovered = window.localStorage.getItem(recoveryKey(projectId, reviewAssignmentId))
    setValue(recovered ?? JSON.stringify(review.data.evidence, null, 2))
    setVersion(review.data.version)
  }, [projectId, review.data, reviewAssignmentId])

  const evidence = () => {
    try {
      const parsed = JSON.parse(value) as Record<string, unknown>
      setParseError(null)
      return parsed
    } catch {
      setParseError('Review evidence must be valid JSON.')
      return null
    }
  }
  const saved = useMutation({
    mutationFn: async () => {
      const parsed = evidence()
      if (!parsed) throw new Error('Review evidence must be valid JSON.')
      return saveReviewDraft(projectId, reviewAssignmentId, version, parsed, token!)
    },
    onSuccess: (result) => setVersion(result.version),
  })
  const submitted = useMutation({
    mutationFn: async () => {
      const parsed = evidence()
      if (!parsed) throw new Error('Review evidence must be valid JSON.')
      return submitReview(projectId, reviewAssignmentId, version, parsed, token!)
    },
    onSuccess: () => {
      window.localStorage.removeItem(recoveryKey(projectId, reviewAssignmentId))
      void queryClient.invalidateQueries({ queryKey: ['candidate-review-queue', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['candidate-review', projectId, reviewAssignmentId] })
    },
  })

  if (review.isLoading) return <div className="centered-status">Loading candidate review…</div>
  if (review.isError || !review.data) return <div className="centered-status">Review unavailable. <Link to={`/projects/${projectId}/reviews`}>Return to review queue</Link></div>
  const item = review.data
  const writable = item.status === 'pending' || item.status === 'in_progress'
  return <main className="consensus-page"><header className="page-heading"><div><Link to={`/projects/${projectId}/reviews`} className="back-link">← Candidate reviews</Link><p className="eyebrow">{item.scope === 'image' ? 'Image label review' : 'Candidate-scoped review'}</p><h1>{item.media.relative_path}</h1><p className="muted">Review only the frozen context shown here. Other candidates and peer evidence are excluded.</p></div></header><section className="consensus-evidence"><aside><h2>Candidate context</h2><pre>{JSON.stringify(item.candidate_context, null, 2)}</pre></aside><div><img src={item.media.image_url} width={item.media.width} height={item.media.height} alt={item.media.relative_path} className="review-source-image" /><section className="adjudication-editor"><h2>Your independent evidence</h2><textarea aria-label="Candidate review evidence JSON" value={value} disabled={!writable} onChange={(event) => { setValue(event.target.value); window.localStorage.setItem(recoveryKey(projectId, reviewAssignmentId), event.target.value) }} />{(parseError || saved.isError || submitted.isError) && <p className="consensus-warning"><AlertTriangle size={15} /> {parseError ?? saved.error?.message ?? submitted.error?.message}</p>}<div className="consensus-actions"><Button variant="secondary" disabled={!writable || saved.isPending} onClick={() => saved.mutate()}><Save size={17} /> Save draft</Button><Button disabled={!writable || submitted.isPending} onClick={() => submitted.mutate()}><Check size={17} /> Submit review</Button></div></section></div></section></main>
}
