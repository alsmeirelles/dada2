import { AlertTriangle, ArrowLeft, Check, Hand, Pentagon, Save, Square, Trash2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { getWorkspaceBootstrap } from '../annotation/annotation-api'
import { ImageStage } from '../annotation/ImageStage'
import type { AnnotationDocument, AnnotationTool } from '../annotation/types'
import { useAuth } from '../auth/auth-context'
import { detailErrorLines } from '../projects/error-details'
import type { ProjectClassInput } from '../projects/types'
import { getReviewAssignment, reviewKeys, saveReviewDraft, submitReview } from './review-api'
import { insideRegion, submittableEvidence, type Region } from './review-draft'
import { clearReviewRecovery, loadReviewRecovery, openReview, saveReviewRecovery, type ReviewRecovery } from './review-recovery'
import type { ReviewAssignmentDetail, ReviewDraft, ReviewStatus } from './review-types'
import '../annotation/annotation.css'
import './review.css'

const STATUS_LABELS: Record<ReviewStatus, string> = {
  pending: 'Not started',
  in_progress: 'In progress',
  submitted: 'Submitted',
  cancelled: 'Cancelled',
}

export function CandidateReviewPage() {
  const { projectId = '', reviewAssignmentId = '' } = useParams()
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<ReviewDraft>({})
  const draftRef = useRef<ReviewDraft>({})
  const [version, setVersion] = useState(0)
  const [conflict, setConflict] = useState<ReviewRecovery | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [panning, setPanning] = useState(false)
  const review = useQuery({
    queryKey: reviewKeys.assignment(projectId, reviewAssignmentId),
    queryFn: () => getReviewAssignment(projectId, reviewAssignmentId, token!),
    enabled: Boolean(projectId && reviewAssignmentId && token),
  })
  const bootstrap = useQuery({
    queryKey: ['annotation-workspace', projectId],
    queryFn: () => getWorkspaceBootstrap(projectId, token!),
    enabled: Boolean(projectId && token),
  })

  const setCurrent = useCallback((value: ReviewDraft) => {
    draftRef.current = value
    setDraft(value)
  }, [])

  const show = useCallback((detail: ReviewAssignmentDetail, message?: string) => {
    const opened = openReview(detail, loadReviewRecovery(projectId, detail.id))
    setCurrent(opened.evidence)
    setVersion(detail.version)
    setConflict(opened.conflict)
    setNotice(message ?? opened.notice)
  }, [projectId, setCurrent])

  useEffect(() => {
    if (review.data) show(review.data)
  }, [review.data, show])

  const refresh = useCallback(async (message: string) => {
    const detail = await getReviewAssignment(projectId, reviewAssignmentId, token!)
    queryClient.setQueryData(reviewKeys.assignment(projectId, reviewAssignmentId), detail)
    show(detail, message)
    void queryClient.invalidateQueries({ queryKey: reviewKeys.queue(projectId) })
  }, [projectId, queryClient, reviewAssignmentId, show, token])

  const handleWriteError = useCallback(async (error: unknown) => {
    const code = error instanceof ApiError ? error.code : undefined
    setProblems(code === 'invalid_review_evidence' ? detailErrorLines(error) : [])
    if (code === 'version_conflict' || code === 'idempotency_conflict') {
      await refresh('This review changed on the server. Your work was kept in this browser; choose which version to keep.')
    } else if (code === 'review_already_submitted') {
      await refresh('This review was already submitted. The server copy is shown.')
    } else if (code === 'review_not_active') {
      await refresh('This review is no longer active. Your unsaved work stays in this browser.')
    } else {
      setNotice(error instanceof Error ? error.message : 'The review could not be saved.')
    }
  }, [refresh])

  const save = useMutation({
    mutationFn: ({ evidence, base }: { evidence: ReviewDraft; base: number }) => saveReviewDraft(projectId, reviewAssignmentId, base, evidence, token!),
    onSuccess: (saved, { evidence }) => {
      setVersion(saved.version)
      setProblems([])
      if (draftRef.current === evidence) clearReviewRecovery(projectId, reviewAssignmentId)
      else saveReviewRecovery(projectId, reviewAssignmentId, saved.version, draftRef.current)
      setNotice('Draft saved.')
    },
    onError: handleWriteError,
  })
  const submit = useMutation({
    mutationFn: ({ evidence, base }: { evidence: Parameters<typeof submitReview>[3]; base: number }) => submitReview(projectId, reviewAssignmentId, base, evidence, token!),
    onSuccess: async () => {
      setProblems([])
      clearReviewRecovery(projectId, reviewAssignmentId)
      await refresh('Review submitted. It is read-only.')
    },
    onError: handleWriteError,
  })

  function change(next: ReviewDraft) {
    setCurrent(next)
    saveReviewRecovery(projectId, reviewAssignmentId, version, next)
  }

  function keepMine() {
    if (!conflict) return
    setConflict(null)
    change(conflict.evidence)
    setNotice('Your version is kept on top of the server copy. Save or submit to store it.')
  }

  function takeServerVersion() {
    clearReviewRecovery(projectId, reviewAssignmentId)
    setConflict(null)
    setNotice(null)
  }

  function submitNow() {
    if (!review.data) return
    const result = submittableEvidence(review.data.scope, draftRef.current)
    if ('problem' in result) return setNotice(result.problem)
    submit.mutate({ evidence: result.evidence, base: version })
  }

  if (review.isLoading || bootstrap.isLoading) return <div className="centered-status">Loading review…</div>
  if (review.isError || !review.data || bootstrap.isError || !bootstrap.data) {
    return <div className="centered-status"><div><AlertTriangle size={28} /><p>This review is unavailable.</p><Link to={`/projects/${projectId}/reviews`}>Return to my reviews</Link></div></div>
  }

  const item = review.data
  const { project, classes } = bootstrap.data
  const writable = (item.status === 'pending' || item.status === 'in_progress') && !conflict
  const busy = save.isPending || submit.isPending
  const region = item.candidate_context.region ?? null

  return <main className="review-page">
    <header className="review-heading">
      <Link to={`/projects/${projectId}/reviews`} className="back-link back-link--flow"><ArrowLeft size={17} /> My reviews</Link>
      <p className="eyebrow">{item.scope === 'image' ? 'Image label review' : 'Object review'}</p>
      <h1>{item.media.relative_path}</h1>
      <p className="muted">{item.scope === 'image'
        ? 'Choose every class that applies to the whole image. Only the image is shown here; nobody else\'s labels are.'
        : `Look inside the dashed region. Say whether it holds an object and, if it does, draw it and choose its class. Only the image and the region are shown here; nobody else's annotations are.`}</p>
      <span className={`status-badge status-badge--review-${item.status}`}>{STATUS_LABELS[item.status]}</span>
    </header>
    <div className="review-layout">
      {item.scope === 'image'
        ? <img className="review-source-image" src={item.media.image_url} alt={item.media.relative_path} />
        : <CandidateStage
          detail={item}
          taskType={project.task_type}
          classes={classes}
          draft={draft}
          region={region}
          writable={writable}
          panning={panning}
          onChange={change}
          onNotice={setNotice}
        />}
      <aside className="review-panel" aria-label="Your review">
        {item.scope === 'image'
          ? <fieldset className="review-choices"><legend>Classes in this image</legend>
            {classes.map((entry) => <label key={entry.id}><input type="checkbox" disabled={!writable || busy} checked={draft.class_ids?.includes(entry.id) ?? false} onChange={(event) => change({ ...draft, class_ids: event.target.checked ? [...(draft.class_ids ?? []), entry.id] : (draft.class_ids ?? []).filter((id) => id !== entry.id) })} /><i style={{ background: entry.color }} aria-hidden="true" />{entry.name}</label>)}
          </fieldset>
          : <>
            <fieldset className="review-choices"><legend>Is there an object in the region?</legend>
              <label><input type="radio" name="review-decision" disabled={!writable || busy} checked={draft.decision === 'object'} onChange={() => change({ ...draft, decision: 'object' })} />Yes, one object</label>
              <label><input type="radio" name="review-decision" disabled={!writable || busy} checked={draft.decision === 'no_object'} onChange={() => change({ ...draft, decision: 'no_object' })} />No object</label>
            </fieldset>
            {draft.decision === 'object' && <>
              <fieldset className="review-choices"><legend>Class of the object</legend>
                {classes.map((entry) => <label key={entry.id}><input type="radio" name="review-class" disabled={!writable || busy} checked={draft.class_id === entry.id} onChange={() => change({ ...draft, class_id: entry.id })} /><i style={{ background: entry.color }} aria-hidden="true" />{entry.name}</label>)}
              </fieldset>
              <div className="review-drawing">
                <p>{draft.geometry ? 'Object drawn. Drawing again replaces it.' : `Choose a class, then draw the ${project.task_type === 'detection' ? 'box' : 'polygon'} inside the region.${project.task_type === 'segmentation' ? ' Press Enter or double-click to close the polygon.' : ''}`}</p>
                <div className="review-tools">
                  <Button variant={panning ? 'secondary' : 'primary'} onClick={() => setPanning(false)} disabled={!writable} aria-pressed={!panning}>{project.task_type === 'detection' ? <Square size={16} /> : <Pentagon size={16} />} Draw</Button>
                  <Button variant={panning ? 'primary' : 'secondary'} onClick={() => setPanning(true)} aria-pressed={panning}><Hand size={16} /> Pan</Button>
                  {draft.geometry && <Button variant="ghost" disabled={!writable || busy} onClick={() => change({ ...draft, geometry: undefined })}><Trash2 size={16} /> Remove drawing</Button>}
                </div>
              </div>
            </>}
          </>}
        {conflict && <div className="review-conflict" role="alert">
          <p><AlertTriangle size={16} /> This review changed on the server after your unsaved work from {new Date(conflict.savedAt).toLocaleTimeString()}.</p>
          <div><Button variant="secondary" onClick={keepMine}>Keep my version</Button><Button variant="ghost" onClick={takeServerVersion}>Use server version</Button></div>
        </div>}
        {notice && !conflict && <p className="review-notice" role="status">{notice}</p>}
        {problems.length > 0 && <ul className="review-problems" role="alert">{problems.map((line) => <li key={line}>{line}</li>)}</ul>}
        <div className="review-actions">
          <Button variant="secondary" disabled={!writable || busy} onClick={() => save.mutate({ evidence: draftRef.current, base: version })}><Save size={17} /> {save.isPending ? 'Saving…' : 'Save draft'}</Button>
          <Button disabled={!writable || busy} onClick={submitNow}><Check size={17} /> {submit.isPending ? 'Submitting…' : 'Submit review'}</Button>
        </div>
      </aside>
    </div>
  </main>
}

function CandidateStage({ detail, taskType, classes, draft, region, writable, panning, onChange, onNotice }: {
  detail: ReviewAssignmentDetail
  taskType: AnnotationDocument['task_type']
  classes: ProjectClassInput[]
  draft: ReviewDraft
  region: Region | null
  writable: boolean
  panning: boolean
  onChange: (draft: ReviewDraft) => void
  onNotice: (message: string) => void
}) {
  const drawing = draft.decision === 'object' && !panning && writable
  const tool: AnnotationTool = drawing ? (taskType === 'detection' ? 'box' : 'polygon') : 'pan'
  const document: AnnotationDocument = {
    media_id: detail.media.id,
    task_type: taskType,
    version: detail.version,
    objects: draft.decision === 'object' && draft.geometry
      ? [{ id: 'review-object', class_id: draft.class_id ?? '', geometry: draft.geometry, attributes: {} }]
      : [],
  }
  return <section className="review-stage" aria-label="Review image">
    <ImageStage
      media={detail.media}
      document={document}
      classes={classes}
      tool={tool}
      selectedClassId={draft.class_id ?? null}
      selectedObjectId={null}
      locked={!writable}
      samPending={false}
      onChange={(next) => {
        const drawn = next.objects.at(-1)
        if (!drawn?.geometry) return
        if (!insideRegion(drawn.geometry, region)) return onNotice('Draw the object inside the dashed region.')
        onChange({ ...draft, decision: 'object', class_id: drawn.class_id, geometry: drawn.geometry })
      }}
      onSelectObject={() => undefined}
      onSamPoint={() => undefined}
      onNotice={onNotice}
      overlay={region && <RegionOverlay region={region} width={detail.media.width} height={detail.media.height} />}
    />
  </section>
}

function RegionOverlay({ region, width, height }: { region: Region; width: number; height: number }) {
  const [x, y, regionWidth, regionHeight] = region
  return <>
    <path className="review-region-shade" fillRule="evenodd" d={`M0 0H${width}V${height}H0Z M${x} ${y}H${x + regionWidth}V${y + regionHeight}H${x}Z`} />
    <rect className="review-region" x={x} y={y} width={regionWidth} height={regionHeight} />
  </>
}
