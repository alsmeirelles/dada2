import { ArrowLeft, Check, Hand, KeyRound, MousePointer2, Pentagon, Square, Trash2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { getWorkspaceBootstrap } from '../annotation/annotation-api'
import { ImageStage } from '../annotation/ImageStage'
import type { AnnotationObject, AnnotationTool } from '../annotation/types'
import { useAuth } from '../auth/auth-context'
import { listMembers } from '../projects/project-api'
import type { ProjectClassInput, TaskType } from '../projects/types'
import {
  acceptRequest,
  draftChanged,
  editRequest,
  isContributor,
  leaseState,
  overridesExpert,
  proposalObjects,
  rationaleReasons,
  rationaleRule,
  sameVersions,
  startDraft,
  workItemRegion,
  type AdjudicationDraft,
  type EditStart,
} from './adjudication'
import {
  clearAdjudicationRecovery,
  loadAdjudicationRecovery,
  saveAdjudicationRecovery,
} from './adjudication-recovery'
import { ConfirmDialog, ErrorNotice } from './ConfirmDialog'
import { adjudicate, consensusKeys, getImageEvidence, revokeLease } from './consensus-api'
import type { AdjudicationRequest, AdjudicationResponse, ImageEvidence, WorkItemView } from './consensus-types'
import {
  SOURCE_LABELS,
  WORK_ITEM_STATUS_LABELS,
  classLabel,
  consensusPaths,
  currentResolution,
  errorCode,
  errorText,
  evidenceSources,
  formatTime,
  geometrySummary,
  personName,
  reasonLabel,
  scopeLabel,
  submissionLabel,
} from './consensus-view-model'
import { EvidenceShapes } from './EvidenceShapes'
import { SourceToggles } from './SourceToggles'
import { useEditLease } from './useEditLease'
import { useEvidenceView } from './useEvidenceView'
import './consensus.css'

const MOVED = [
  'version_conflict', 'resolution_config_conflict', 'lease_required', 'lease_held', 'adjudicator_not_independent',
  'work_item_closed', 'work_item_not_open', 'resolution_not_ready', 'item_closed',
]

type People = { user_id: string; display_name: string }[]
type DialogKind = 'accept' | 'submit' | 'revoke' | 'discard'

export function WorkItemPage() {
  const { projectId = '', workItemId = '' } = useParams()
  const [search] = useSearchParams()
  const batchItemId = search.get('item') ?? ''
  const { token, user } = useAuth()
  const queryClient = useQueryClient()
  const enabled = Boolean(projectId && batchItemId && token)
  const evidence = useQuery({
    queryKey: consensusKeys.evidence(projectId, batchItemId),
    queryFn: () => getImageEvidence(projectId, batchItemId, token!),
    enabled,
  })
  const bootstrap = useQuery({
    queryKey: ['annotation-workspace', projectId],
    queryFn: () => getWorkspaceBootstrap(projectId, token!),
    enabled: Boolean(projectId && token),
  })
  const members = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listMembers(projectId, token!),
    enabled: Boolean(projectId && token),
  })

  const back = <Link className="back-link back-link--flow" to={consensusPaths.queue(projectId)}><ArrowLeft size={17} /> Consensus review queue</Link>
  if (!batchItemId) {
    return <main className="page-container consensus-page">{back}<div className="panel status-panel">This link does not say which image the case belongs to. Open the case from the consensus review queue.</div></main>
  }
  if (evidence.error instanceof ApiError && evidence.error.status === 403) {
    return <main className="page-container consensus-page">{back}<div className="panel status-panel">Adjudication is available to project owners and managers.</div></main>
  }
  if (evidence.isLoading || bootstrap.isLoading) {
    return <main className="page-container consensus-page"><div className="panel status-panel">Loading the case…</div></main>
  }
  if (evidence.isError || bootstrap.isError) {
    return <main className="page-container consensus-page">{back}<ErrorNotice error={evidence.error ?? bootstrap.error} /></main>
  }
  const workItem = evidence.data!.work_items.find((item) => item.id === workItemId)
  if (!workItem) {
    return <main className="page-container consensus-page">{back}<div className="panel status-panel">This case does not belong to the image in the link. <Link to={consensusPaths.image(projectId, batchItemId)}>Open the image evidence</Link>.</div></main>
  }

  return <WorkItemEditor
    key={workItem.id}
    projectId={projectId}
    evidence={evidence.data!}
    workItem={workItem}
    classes={bootstrap.data!.classes}
    people={members.data?.items ?? []}
    userId={user?.id ?? ''}
    token={token!}
    refresh={() => Promise.all([
      queryClient.invalidateQueries({ queryKey: consensusKeys.evidence(projectId, batchItemId) }),
      queryClient.invalidateQueries({ queryKey: consensusKeys.queues(projectId) }),
      queryClient.invalidateQueries({ queryKey: ['project-batches', projectId] }),
    ])}
  />
}

type EditorProps = {
  projectId: string
  evidence: ImageEvidence
  workItem: WorkItemView
  classes: ProjectClassInput[]
  people: People
  userId: string
  token: string
  refresh: () => Promise<unknown>
}

function WorkItemEditor({ projectId, evidence, workItem, classes, people, userId, token, refresh }: EditorProps) {
  const lease = useEditLease(projectId, workItem.id, token)
  const proposal = proposalObjects(evidence, workItem)
  const [draft, setDraftState] = useState<AdjudicationDraft | null>(null)
  const [recovered, setRecovered] = useState(() => loadAdjudicationRecovery(projectId, workItem.id, userId))
  const [startKind, setStartKind] = useState<EditStart['kind']>(proposal ? 'proposal' : 'blank')
  const [submissionId, setSubmissionId] = useState(
    evidence.submissions.find((entry) => entry.current_generation)?.id ?? evidence.submissions[0]?.id ?? '',
  )
  const [tool, setTool] = useState<AnnotationTool>(defaultTool(evidence.task_type))
  const [selectedClassId, setSelectedClassId] = useState<string | null>(classes[0]?.id ?? null)
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  const [dialog, setDialog] = useState<DialogKind | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [failure, setFailure] = useState<unknown>(null)
  const [result, setResult] = useState<AdjudicationResponse | null>(null)
  const [copyConfirmed, setCopyConfirmed] = useState(false)
  const sources = useMemo(() => evidenceSources(evidence), [evidence])
  const view = useEvidenceView(sources)

  const open = workItem.status === 'review_required'
  const contributor = isContributor(evidence, userId)
  const blocked = contributor && evidence.require_independent_adjudicator
  const context = { contributor, overridingExpert: overridesExpert(evidence) }
  const serverLease = leaseState(workItem.lease, userId, Date.now())
  const foreign = lease.status !== 'held' && serverLease.kind === 'other' ? serverLease.lease : null
  const conflict = Boolean(draft && !sameVersions(draft.base, evidence.versions))
  const editing = Boolean(draft && lease.status === 'held' && !conflict && open && !blocked)
  const dirty = Boolean(draft && draftChanged(draft))
  const region = workItemRegion(evidence, workItem)

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  function setDraft(next: AdjudicationDraft) {
    setDraftState(next)
    saveAdjudicationRecovery(projectId, workItem.id, userId, next)
  }

  function setObjects(objects: AnnotationObject[]) {
    if (draft && editing) setDraft({ ...draft, objects })
  }

  const decide = useMutation({
    mutationFn: (body: AdjudicationRequest) => adjudicate(projectId, workItem.id, body, token),
    onSuccess: async (response) => {
      clearAdjudicationRecovery(projectId, workItem.id, userId)
      setDraftState(null)
      setDialog(null)
      setFailure(null)
      setResult(response)
      await lease.release()
      await refresh()
    },
    onError: async (error) => {
      const code = errorCode(error)
      if (code === 'lease_required') lease.markLost(error)
      if (!code || !MOVED.includes(code)) return
      setDialog(null)
      setFailure(error)
      await refresh()
    },
  })
  const revoke = useMutation({
    mutationFn: (reason: string) => revokeLease(projectId, workItem.id, reason, token),
    onSuccess: async () => {
      setDialog(null)
      setMessage('The lease was revoked. The case can be edited again.')
      await refresh()
    },
  })

  async function startEditing() {
    setFailure(null)
    const start: EditStart = startKind === 'submission' ? { kind: 'submission', submissionId } : { kind: startKind }
    if (await lease.acquire()) {
      setDraft(startDraft(evidence, workItem, start))
      setSelectedObjectId(null)
    }
  }

  async function resumeDraft() {
    if (!recovered) return
    setDraftState(recovered.draft)
    setRecovered(null)
    if (open && !blocked) await lease.acquire()
  }

  async function discardDraft() {
    clearAdjudicationRecovery(projectId, workItem.id, userId)
    setDraftState(null)
    setRecovered(null)
    setDialog(null)
    setCopyConfirmed(false)
    await lease.release()
  }

  function copyOntoNewVersion() {
    if (!draft) return
    setDraft({ ...draft, base: evidence.versions })
    setCopyConfirmed(false)
    setFailure(null)
    setMessage('Your draft now builds on the new version. Review it before you submit.')
  }

  function selectClass(classId: string) {
    setSelectedClassId(classId)
    if (!draft || !editing) return
    if (evidence.task_type === 'classification') {
      const existing = draft.objects.find((item) => item.class_id === classId)
      setObjects(existing
        ? draft.objects.filter((item) => item.id !== existing.id)
        : [...draft.objects, { id: crypto.randomUUID(), class_id: classId, geometry: null, attributes: {} }])
      return
    }
    if (selectedObjectId) setObjects(draft.objects.map((item) => item.id === selectedObjectId ? { ...item, class_id: classId } : item))
  }

  function removeSelected() {
    if (!draft || !selectedObjectId) return
    setObjects(draft.objects.filter((item) => item.id !== selectedObjectId))
    setSelectedObjectId(null)
  }

  useEffect(() => {
    if (!editing) return
    function keyboard(event: KeyboardEvent) {
      if (isEditingText(event.target)) return
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedObjectId) {
        event.preventDefault()
        removeSelected()
      }
      if (event.key.toLowerCase() === 'v') setTool('select')
      if (event.key.toLowerCase() === 'h') setTool('pan')
      if (event.key.toLowerCase() === 'b' && evidence.task_type === 'detection') setTool('box')
      if (event.key.toLowerCase() === 'p' && evidence.task_type === 'segmentation') setTool('polygon')
      const classItem = classes[Number(event.key) - 1]
      if (classItem) selectClass(classItem.id)
    }
    window.addEventListener('keydown', keyboard)
    return () => window.removeEventListener('keydown', keyboard)
  })

  const resolution = currentResolution(evidence)
  const submitAction = draft?.action ?? 'edit_proposal'

  return <main className="page-container consensus-page">
    <div className="page-heading">
      <div>
        <Link className="back-link back-link--flow" to={consensusPaths.image(projectId, evidence.batch_item_id)}><ArrowLeft size={17} /> Image evidence</Link>
        <p className="eyebrow">{scopeLabel(workItem.scope, workItem.candidate_ordinal)} · {WORK_ITEM_STATUS_LABELS[workItem.status]}</p>
        <h1>{evidence.media.relative_path}</h1>
        <p className="muted">{reasonLabel(workItem.reason)}. {workItem.scope === 'image'
          ? 'Your decision covers the whole image.'
          : 'Your decision covers only this object; zero objects means nothing exists here. The image resolution is composed once every case is decided.'}</p>
      </div>
    </div>

    {blocked && <p className="form-error" role="alert">This batch requires an independent adjudicator. You contributed evidence to this image, so you cannot decide this case.</p>}
    {contributor && !blocked && <p className="consensus-note">You contributed evidence to this image. Your decision is recorded as a conflict and needs a rationale.</p>}
    {message && <p className="consensus-note" role="status">{message}</p>}
    {failure !== null && <ErrorNotice error={failure} />}

    {result && <section className="panel decision-panel" aria-labelledby="result-heading">
      <h2 id="result-heading">Decision recorded</h2>
      <p>{result.resolution
        ? `Resolution v${result.resolution.version} of the image was composed (${SOURCE_LABELS[result.resolution.source].toLowerCase()}).`
        : 'The image resolution is composed once its other cases are decided.'}</p>
      <div className="consensus-actions">
        <Link className="button button--secondary" to={consensusPaths.image(projectId, evidence.batch_item_id)}>Open the image evidence</Link>
        <Link className="button button--primary" to={consensusPaths.queue(projectId)}>Back to the queue</Link>
      </div>
    </section>}

    <LeasePanel
      leaseStatus={lease.status}
      held={lease.lease}
      error={lease.error}
      foreign={foreign}
      people={people}
      userId={userId}
      onReacquire={() => void lease.acquire()}
      onRevoke={() => setDialog('revoke')}
    />

    {recovered && !draft && <section className="panel decision-panel" aria-labelledby="recovery-heading">
      <h2 id="recovery-heading">Unsaved draft found</h2>
      <p>A draft from {new Date(recovered.savedAt).toLocaleString()} was kept in this tab. It builds on evidence generation {recovered.draft.base.evidence_generation} and resolution version {recovered.draft.base.resolution_version}.</p>
      <div className="consensus-actions">
        <Button onClick={() => void resumeDraft()}>Resume the draft</Button>
        <Button variant="secondary" onClick={() => void discardDraft()}>Discard the draft</Button>
      </div>
    </section>}

    {draft && conflict && <ReconcilePanel
      draft={draft}
      evidence={evidence}
      workItem={workItem}
      classes={classes}
      open={open && !blocked}
      leaseHeld={lease.status === 'held'}
      confirmed={copyConfirmed}
      onConfirm={setCopyConfirmed}
      onAcquire={() => void lease.acquire()}
      onCopy={copyOntoNewVersion}
      onDiscard={() => setDialog('discard')}
    />}

    {!draft && !recovered && !result && open && !blocked && <section className="panel decision-panel" aria-labelledby="decide-heading">
      <h2 id="decide-heading">Decide this case</h2>
      <div className="decision-options">
        <div className="decision-option">
          <h3>Accept the proposal</h3>
          <p>{proposal ? `Proposed: ${objectsText(proposal, classes, workItem.scope)}` : 'There is no proposal to accept; the run produced none.'}</p>
          <Button disabled={!proposal || Boolean(foreign) || decide.isPending} onClick={() => setDialog('accept')}><Check size={16} /> Accept proposal</Button>
        </div>
        <fieldset className="decision-option">
          <legend>Or edit, starting from</legend>
          <label><input type="radio" name="edit-start" checked={startKind === 'proposal'} disabled={!proposal} onChange={() => setStartKind('proposal')} /> The resolution proposal</label>
          <label><input type="radio" name="edit-start" checked={startKind === 'submission'} disabled={!evidence.submissions.length} onChange={() => setStartKind('submission')} /> A raw submission</label>
          {startKind === 'submission' && <label className="queue-filter">Submission
            <select value={submissionId} onChange={(event) => setSubmissionId(event.target.value)}>
              {evidence.submissions.map((entry) => <option key={entry.id} value={entry.id}>{submissionLabel(entry)}{entry.current_generation ? '' : ' (earlier generation)'}</option>)}
            </select>
          </label>}
          <label><input type="radio" name="edit-start" checked={startKind === 'blank'} onChange={() => setStartKind('blank')} /> A blank document (replacement)</label>
          <Button disabled={Boolean(foreign) || lease.status === 'acquiring'} onClick={() => void startEditing()}><KeyRound size={16} /> Take the lease and start editing</Button>
        </fieldset>
      </div>
    </section>}

    {!open && !result && <section className="panel decision-panel">
      <h2>This case does not await a decision</h2>
      <p>It is {WORK_ITEM_STATUS_LABELS[workItem.status].toLowerCase()}.{resolution ? ` The image's current resolution is v${resolution.version}.` : ''}</p>
    </section>}

    {draft && <section className="adjudication-editor" aria-labelledby="editor-heading">
      <header className="adjudication-editor__header">
        <h2 id="editor-heading">{draft.action === 'edit_proposal' ? 'Editing the proposal' : draft.action === 'edit_submission' ? 'Editing a raw submission' : 'Writing a replacement'}</h2>
        <div className="consensus-actions">
          <Button disabled={!editing || decide.isPending} onClick={() => setDialog('submit')}><Check size={16} /> Submit decision</Button>
          <Button variant="secondary" onClick={() => dirty ? setDialog('discard') : void discardDraft()}>Stop editing</Button>
        </div>
      </header>
      <div className="annotation-toolbar" role="toolbar" aria-label="Adjudication tools">
        <button className={tool === 'select' ? 'active' : ''} onClick={() => setTool('select')} title="Select (V)"><MousePointer2 size={19} /><span>Select</span></button>
        <button className={tool === 'pan' ? 'active' : ''} onClick={() => setTool('pan')} title="Pan (H or Space)"><Hand size={19} /><span>Pan</span></button>
        {evidence.task_type === 'detection' && <button className={tool === 'box' ? 'active' : ''} disabled={!editing} onClick={() => setTool('box')} title="Bounding box (B)"><Square size={19} /><span>Box</span></button>}
        {evidence.task_type === 'segmentation' && <button className={tool === 'polygon' ? 'active' : ''} disabled={!editing} onClick={() => setTool('polygon')} title="Polygon (P)"><Pentagon size={19} /><span>Polygon</span></button>}
        <button disabled={!editing || !selectedObjectId} onClick={removeSelected} title="Delete selected (Delete)"><Trash2 size={18} /><span>Delete selected</span></button>
      </div>
      <div className="adjudication-layout">
        <div className="adjudication-canvas">
          <ImageStage
            media={evidence.media}
            document={{ media_id: evidence.media.id, task_type: evidence.task_type, version: draft.base.resolution_version, objects: draft.objects }}
            classes={classes}
            tool={tool}
            selectedClassId={selectedClassId}
            selectedObjectId={selectedObjectId}
            locked={!editing}
            samPending={false}
            onChange={(document) => setObjects(document.objects)}
            onSelectObject={setSelectedObjectId}
            onSamPoint={() => undefined}
            onNotice={setMessage}
            overlay={<EvidenceShapes
              sources={view.shown}
              regions={view.showRegions && region ? [{ key: workItem.candidate_key, label: 'This case', passed: false, region }] : []}
              classes={classes}
              alpha={view.alpha}
            />}
          />
        </div>
        <aside className="adjudication-side">
          <div className="class-picker" role="group" aria-label="Classes">
            {classes.map((item, index) => {
              const assigned = draft.objects.some((object) => object.class_id === item.id)
              return <button
                key={item.id}
                type="button"
                className={selectedClassId === item.id ? 'selected' : ''}
                aria-pressed={evidence.task_type === 'classification' ? assigned : selectedClassId === item.id}
                disabled={!editing}
                onClick={() => selectClass(item.id)}
              ><i style={{ background: item.color }} aria-hidden="true" />{item.name}<small>Key {index + 1}</small></button>
            })}
          </div>
          <h3>Objects in your draft</h3>
          <ul className="draft-objects">
            {draft.objects.map((object, index) => <li key={object.id}>
              <button type="button" aria-pressed={selectedObjectId === object.id} onClick={() => { setSelectedObjectId(object.id); setSelectedClassId(object.class_id) }}>
                {index + 1}. {classLabel(classes, object.class_id)} · {geometrySummary(object)}
              </button>
            </li>)}
            {!draft.objects.length && <li className="muted">{workItem.scope === 'candidate' ? 'No objects: the decision is that nothing exists here.' : 'No objects yet.'}</li>}
          </ul>
          {evidence.task_type !== 'classification' && <SourceToggles
            sources={sources}
            visible={view.visible}
            onToggle={view.toggle}
            onHideAll={view.hideAll}
            regions={{ checked: view.showRegions, onChange: view.setShowRegions }}
            alpha={evidence.task_type === 'segmentation' ? { value: view.alpha, onChange: view.setAlpha } : undefined}
          />}
        </aside>
      </div>
    </section>}

    {dialog === 'accept' && <ConfirmDialog
      title="Accept the proposal"
      effect={`This accepts the resolver's proposal for this case: ${proposal ? objectsText(proposal, classes, workItem.scope) : 'nothing'}. ${workItem.scope === 'image' ? 'It decides the whole image.' : 'The image resolution is composed once every case is decided.'}`}
      confirmLabel="Accept proposal"
      rationale={rationaleRule('accept_proposal', context)}
      notes={rationaleReasons('accept_proposal', context)}
      pending={decide.isPending}
      error={decide.error}
      onConfirm={(rationale) => decide.mutate(acceptRequest(evidence.versions, rationale))}
      onCancel={() => { setDialog(null); decide.reset() }}
    />}
    {dialog === 'submit' && draft && <ConfirmDialog
      title="Submit your decision"
      effect={submitEffect(draft, evidence, workItem.scope)}
      confirmLabel="Submit decision"
      rationale={rationaleRule(submitAction, context)}
      notes={rationaleReasons(submitAction, context)}
      pending={decide.isPending}
      error={decide.error}
      onConfirm={(rationale) => decide.mutate(editRequest(draft, rationale))}
      onCancel={() => { setDialog(null); decide.reset() }}
    />}
    {dialog === 'revoke' && foreign && <ConfirmDialog
      title="Revoke the edit lease"
      effect={`This ends ${personName(foreign.holder_id, people, userId)}'s edit lease so the case can be edited again. Their unsaved draft stays in their browser.`}
      confirmLabel="Revoke lease"
      rationale="required"
      rationaleLabel="Reason (required)"
      pending={revoke.isPending}
      error={revoke.error}
      onConfirm={(reason) => revoke.mutate(reason)}
      onCancel={() => { setDialog(null); revoke.reset() }}
    />}
    {dialog === 'discard' && <ConfirmDialog
      title="Discard your draft"
      effect="This deletes your unconfirmed draft from this tab and releases the edit lease. Nothing is sent to the server."
      confirmLabel="Discard draft"
      rationale="none"
      onConfirm={() => void discardDraft()}
      onCancel={() => setDialog(null)}
    />}
  </main>
}

function LeasePanel({ leaseStatus, held, error, foreign, people, userId, onReacquire, onRevoke }: {
  leaseStatus: ReturnType<typeof useEditLease>['status']
  held: ReturnType<typeof useEditLease>['lease']
  error: unknown
  foreign: WorkItemView['lease']
  people: People
  userId: string
  onReacquire: () => void
  onRevoke: () => void
}) {
  if (leaseStatus === 'held' && held) {
    return <p className="consensus-note lease-note" role="status">You hold the edit lease until {formatTime(held.expires_at)}. It renews every 5 minutes while you edit; its two-hour limit is {formatTime(held.cap_at)}.</p>
  }
  if (leaseStatus === 'lost') {
    return <div className="consensus-note lease-note" role="alert">
      <p>Your edit lease was lost: {errorText(error)} Your draft is kept in this tab, and editing is paused until you hold the lease again.</p>
      <Button variant="secondary" onClick={onReacquire}><KeyRound size={16} /> Reacquire the lease</Button>
    </div>
  }
  if (foreign) {
    return <div className="consensus-note lease-note" role="status">
      <p>{personName(foreign.holder_id, people, userId)} holds the edit lease until {formatTime(foreign.expires_at)}. Decisions on this image wait until it is released or expires.</p>
      <Button variant="secondary" onClick={onRevoke}>Revoke the lease</Button>
    </div>
  }
  return <>
    {error !== null && <ErrorNotice error={error} />}
    {leaseStatus === 'acquiring' && <p className="consensus-note" role="status">Taking the edit lease…</p>}
  </>
}

function ReconcilePanel({ draft, evidence, workItem, classes, open, leaseHeld, confirmed, onConfirm, onAcquire, onCopy, onDiscard }: {
  draft: AdjudicationDraft
  evidence: ImageEvidence
  workItem: WorkItemView
  classes: ProjectClassInput[]
  open: boolean
  leaseHeld: boolean
  confirmed: boolean
  onConfirm: (value: boolean) => void
  onAcquire: () => void
  onCopy: () => void
  onDiscard: () => void
}) {
  const latest = proposalObjects(evidence, workItem)
  const resolution = currentResolution(evidence)
  const configurationChanged = draft.base.configuration_fingerprint !== evidence.versions.configuration_fingerprint
  return <section className="panel reconcile-panel" aria-labelledby="reconcile-heading">
    <h2 id="reconcile-heading">The evidence changed since your draft was based on it</h2>
    <p>Your draft is kept in this tab and was not rebased. Compare the three versions, then keep your draft on top of the new version or discard it.</p>
    <div className="reconcile-grid">
      <ObjectColumn
        title="Source"
        subtitle={`${sourceText(draft, evidence)} at evidence generation ${draft.base.evidence_generation}, resolution version ${draft.base.resolution_version}`}
        objects={draft.sourceObjects}
        classes={classes}
        scope={workItem.scope}
      />
      <ObjectColumn title="Your draft" subtitle="Your unconfirmed local edit" objects={draft.objects} classes={classes} scope={workItem.scope} />
      <ObjectColumn
        title="New version"
        subtitle={`Evidence generation ${evidence.versions.evidence_generation}, resolution version ${evidence.versions.resolution_version}${configurationChanged ? ', new resolver configuration' : ''}. Case ${WORK_ITEM_STATUS_LABELS[workItem.status].toLowerCase()}${resolution ? `; current resolution v${resolution.version}` : ''}. Its proposal for this case:`}
        objects={latest ?? []}
        classes={classes}
        scope={workItem.scope}
        empty={latest ? undefined : 'No proposal for this case.'}
      />
    </div>
    {!open && <p className="form-error">This case no longer awaits a decision, so the draft cannot be copied onto it.</p>}
    <label className="reconcile-confirm">
      <input type="checkbox" checked={confirmed} disabled={!open} onChange={(event) => onConfirm(event.target.checked)} />
      I compared the new version and want to keep my draft unchanged on top of it.
    </label>
    <div className="consensus-actions">
      {!leaseHeld && open && <Button variant="secondary" onClick={onAcquire}><KeyRound size={16} /> Acquire the edit lease</Button>}
      <Button disabled={!open || !leaseHeld || !confirmed} onClick={onCopy}>Copy my draft onto the new version</Button>
      <Button variant="secondary" onClick={onDiscard}>Discard my draft</Button>
    </div>
  </section>
}

function ObjectColumn({ title, subtitle, objects, classes, scope, empty }: {
  title: string
  subtitle: string
  objects: AnnotationObject[]
  classes: ProjectClassInput[]
  scope: WorkItemView['scope']
  empty?: string
}) {
  return <section className="reconcile-column" aria-label={title}>
    <h3>{title}</h3>
    <p className="muted">{subtitle}</p>
    <ul>
      {objects.map((object) => <li key={object.id}>{classLabel(classes, object.class_id)} · {geometrySummary(object)}</li>)}
      {!objects.length && <li>{empty ?? (scope === 'candidate' ? 'No objects: nothing exists here.' : 'No objects.')}</li>}
    </ul>
  </section>
}

function objectsText(objects: AnnotationObject[], classes: ProjectClassInput[], scope: WorkItemView['scope']) {
  if (!objects.length) return scope === 'candidate' ? 'nothing exists here' : 'no objects'
  return objects.map((object) => `${classLabel(classes, object.class_id)}${object.geometry ? ` (${geometrySummary(object)})` : ''}`).join(', ')
}

function sourceText(draft: AdjudicationDraft, evidence: ImageEvidence) {
  if (draft.action === 'edit_proposal') return 'The resolution proposal'
  if (draft.action === 'replace') return 'A blank document'
  const submission = evidence.submissions.find((entry) => entry.id === draft.sourceSubmissionId)
  return submission ? `${submission.annotator_name}'s submission` : 'A raw submission'
}

function submitEffect(draft: AdjudicationDraft, evidence: ImageEvidence, scope: WorkItemView['scope']) {
  const start = draft.action === 'edit_proposal'
    ? 'This records your edited proposal as the expert decision for this case.'
    : draft.action === 'edit_submission'
      ? `This records your edit of a raw submission (${sourceText(draft, evidence)}) as the expert decision for this case. The submission itself does not change.`
      : 'This replaces the proposal with your new annotation as the expert decision for this case.'
  const count = draft.objects.length
  const contents = !count && scope === 'candidate'
    ? ' With no objects, the decision is that nothing exists here.'
    : ` It contains ${count} object${count === 1 ? '' : 's'}.`
  return start + contents
}

function defaultTool(taskType: TaskType): AnnotationTool {
  if (taskType === 'detection') return 'box'
  if (taskType === 'segmentation') return 'polygon'
  return 'select'
}

function isEditingText(target: EventTarget | null) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement ||
    (target instanceof HTMLElement && target.isContentEditable)
}
