import { AlertTriangle, Check, RotateCw } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { acceptResolution, adjudicateResolution, getResolutionEvidence, retryResolution } from './consensus-api'
import './consensus.css'

export function ConsensusReviewPage() {
  const { projectId = '', batchItemId = '' } = useParams()
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [editorValue, setEditorValue] = useState('')
  const evidence = useQuery({ queryKey: ['resolution-evidence', projectId, batchItemId], queryFn: () => getResolutionEvidence(projectId, batchItemId, token!), enabled: Boolean(projectId && batchItemId && token) })
  const invalidate = () => { void queryClient.invalidateQueries({ queryKey: ['resolution-evidence', projectId, batchItemId] }); void queryClient.invalidateQueries({ queryKey: ['resolution-queue', projectId] }) }
  const accept = useMutation({ mutationFn: (id: string) => acceptResolution(projectId, batchItemId, id, token!), onSuccess: invalidate })
  const retry = useMutation({ mutationFn: () => retryResolution(projectId, batchItemId, token!), onSuccess: invalidate })
  useEffect(() => {
    const item = evidence.data
    if (!item) return
    const source = item.proposed_resolution?.document ?? item.submissions[0]?.document
    setEditorValue(source ? JSON.stringify(source, null, 2) : '')
  }, [evidence.data])
  const adjudicate = useMutation({
    mutationFn: () => adjudicateResolution(projectId, batchItemId, JSON.parse(editorValue), token!),
    onSuccess: invalidate,
  })
  const submitAdjudication = () => adjudicate.mutate()
  if (evidence.isLoading) return <div className="centered-status">Loading annotation evidence…</div>
  if (evidence.isError || !evidence.data) return <div className="centered-status">Evidence is unavailable. <Link to={`/projects/${projectId}/consensus`}>Return to review queue</Link></div>
  const item = evidence.data
  return <main className="consensus-page"><header className="page-heading"><div><Link to={`/projects/${projectId}/consensus`} className="back-link">← Consensus queue</Link><p className="eyebrow">Manager review</p><h1>{item.media.relative_path}</h1><p className="muted">Raw submissions remain immutable. Accepting a proposal creates the canonical resolution.</p></div></header><section className="consensus-evidence"><aside><h2>Resolution</h2><p className={`resolution-status resolution-status--${item.status}`}>{item.status.replace('_', ' ')}</p>{item.resolver && <p><strong>{item.resolver.name}</strong> v{item.resolver.version}</p>}<dl>{Object.entries(item.diagnostics).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl><div className="consensus-actions">{item.proposed_resolution && <Button onClick={() => accept.mutate(item.proposed_resolution!.id)} disabled={accept.isPending}><Check size={17} /> Accept proposal</Button>}<Button variant="secondary" onClick={() => retry.mutate()} disabled={retry.isPending}><RotateCw size={17} /> Retry resolver</Button></div>{(accept.isError || retry.isError || adjudicate.isError) && <p className="consensus-warning"><AlertTriangle size={15} /> {accept.error?.message ?? retry.error?.message ?? adjudicate.error?.message}</p>}</aside><div><h2>Independent submissions</h2><div className="evidence-grid">{item.submissions.map((submission, index) => <article key={submission.id}><h3>Submission {index + 1}</h3><p>{submission.document.objects.length} object{submission.document.objects.length === 1 ? '' : 's'}</p><pre>{JSON.stringify(submission.document.objects, null, 2)}</pre></article>)}{item.proposed_resolution && <article className="evidence-proposal"><h3>Proposed resolution</h3><p>{item.proposed_resolution.document.objects.length} objects</p><pre>{JSON.stringify(item.proposed_resolution.document.objects, null, 2)}</pre></article>}</div><section className="adjudication-editor"><h2>Adjudicated annotation</h2><p className="muted">Edit a copy of the proposed or first submitted document. This creates a new canonical document and does not alter raw evidence.</p><textarea aria-label="Adjudicated annotation JSON" value={editorValue} onChange={(event) => setEditorValue(event.target.value)} /><Button onClick={submitAdjudication} disabled={!editorValue || adjudicate.isPending}><Check size={17} /> Submit adjudication</Button></section></div></section></main>
}
