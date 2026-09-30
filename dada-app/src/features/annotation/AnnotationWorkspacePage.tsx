import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Hand,
  MousePointer2,
  Pentagon,
  PanelRightClose,
  PanelRightOpen,
  Save,
  Sparkles,
  Square,
  Trash2,
  Undo2,
  Redo2,
  Radio,
} from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import type { BatchPurpose } from '../projects/types'
import {
  getAssignment,
  getWorkspaceBootstrap,
  listAssignments,
  predictSegmentation,
  saveDraft,
  submitAssignment,
} from './annotation-api'
import {
  AUTOSAVE_MS,
  STATUS_LABELS,
  filterAssignments,
  isEditable,
  neighbor,
  openWork,
  validateDocument,
} from './assignment-view'
import { ImageStage } from './ImageStage'
import { clearRecovery, loadRecovery, saveRecovery, type RecoverySnapshot } from './recovery'
import { useProjectEvents } from './useProjectEvents'
import type {
  AnnotationDocument,
  AnnotationObject,
  AnnotationTool,
  AssignmentDetail,
  AssignmentQueueItem,
  QueueState,
} from './types'
import './annotation.css'

type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

const PURPOSE_LABELS: Record<BatchPurpose, string> = {
  initial_annotation: 'Static batch',
  initial_training: 'First training',
  validation: 'Validation',
  test: 'Test',
  acquisition: 'Acquisition',
}

export function AnnotationWorkspacePage() {
  const { projectId = '' } = useParams()
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [assignment, setAssignment] = useState<AssignmentDetail | null>(null)
  const [document, setDocument] = useState<AnnotationDocument | null>(null)
  const documentRef = useRef<AnnotationDocument | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [conflict, setConflict] = useState<RecoverySnapshot | null>(null)
  const [purposeFilter, setPurposeFilter] = useState<BatchPurpose | 'all'>('all')
  const [stateFilter, setStateFilter] = useState<QueueState | 'all'>('all')
  const [tool, setTool] = useState<AnnotationTool>('select')
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null)
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  const undoStack = useRef<AnnotationDocument[]>([])
  const redoStack = useRef<AnnotationDocument[]>([])
  const [showClasses, setShowClasses] = useState(true)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const classPanelRef = useRef<HTMLElement>(null)

  const bootstrap = useQuery({
    queryKey: ['annotation-workspace', projectId],
    queryFn: () => getWorkspaceBootstrap(projectId, token!),
    enabled: Boolean(projectId && token),
  })
  const queue = useQuery({
    queryKey: ['annotation-queue', projectId],
    queryFn: () => listAssignments(projectId, token!),
    enabled: Boolean(projectId && token),
    refetchInterval: 30_000,
  })

  const handleProjectEvent = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['annotation-queue', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['annotation-workspace', projectId] })
  }, [projectId, queryClient])
  const realtimeStatus = useProjectEvents(projectId, token, handleProjectEvent)

  const editable = Boolean(assignment && isEditable(assignment.status) && !conflict)

  const setCurrentDocument = useCallback((value: AnnotationDocument | null) => {
    documentRef.current = value
    setDocument(value)
  }, [])

  const remember = useCallback((value: AnnotationDocument) => {
    if (assignment) saveRecovery(projectId, assignment.id, value.version, value)
  }, [assignment, projectId])

  const changeDocument = useCallback((value: AnnotationDocument) => {
    const current = documentRef.current
    if (current) undoStack.current.push(current)
    if (undoStack.current.length > 100) undoStack.current.shift()
    redoStack.current = []
    setCurrentDocument(value)
    remember(value)
    setSaveState('dirty')
  }, [remember, setCurrentDocument])

  const undo = useCallback(() => {
    const previous = undoStack.current.pop()
    const current = documentRef.current
    if (!previous || !current) return
    redoStack.current.push(current)
    const value = { ...previous, version: current.version }
    setCurrentDocument(value)
    remember(value)
    setSelectedObjectId(null)
    setSaveState('dirty')
  }, [remember, setCurrentDocument])

  const redo = useCallback(() => {
    const next = redoStack.current.pop()
    const current = documentRef.current
    if (!next || !current) return
    undoStack.current.push(current)
    const value = { ...next, version: current.version }
    setCurrentDocument(value)
    remember(value)
    setSelectedObjectId(null)
    setSaveState('dirty')
  }, [remember, setCurrentDocument])

  const removeSelected = useCallback(() => {
    const current = documentRef.current
    if (!current || !selectedObjectId) return
    changeDocument({ ...current, objects: current.objects.filter((item) => item.id !== selectedObjectId) })
    setSelectedObjectId(null)
  }, [changeDocument, selectedObjectId])

  const show = useCallback((detail: AssignmentDetail, message?: string) => {
    const opened = openWork(detail, loadRecovery(projectId, detail.id, detail.media.id))
    setAssignment(detail)
    setCurrentDocument(opened.document)
    setConflict(opened.conflict)
    undoStack.current = []
    redoStack.current = []
    setSelectedObjectId(null)
    setSelectedClassId(opened.document.objects[0]?.class_id ?? bootstrap.data?.classes[0]?.id ?? null)
    setTool(defaultTool(opened.document.task_type))
    setSaveState(opened.dirty ? 'dirty' : 'idle')
    setNotice(message ?? opened.notice)
  }, [bootstrap.data?.classes, projectId, setCurrentDocument])

  const opening = useMutation({
    mutationFn: (assignmentId: string) => getAssignment(projectId, assignmentId, token!),
    onSuccess: (detail) => show(detail),
    onError: (error) => setNotice(error instanceof Error ? error.message : 'The image could not be opened.'),
  })

  const refresh = useCallback(async (message: string) => {
    if (!assignment) return
    const detail = await getAssignment(projectId, assignment.id, token!)
    if (detail.status === 'submitted') clearRecovery(projectId, detail.id)
    show(detail, message)
    void queue.refetch()
  }, [assignment, projectId, queue, show, token])

  const handleWriteError = useCallback(async (error: unknown) => {
    const code = error instanceof ApiError ? error.code : undefined
    if (code === 'version_conflict' || code === 'idempotency_conflict') {
      await refresh('This image changed on the server. Your work was kept in this browser; choose which version to keep.')
    } else if (code === 'assignment_already_submitted') {
      await refresh('This image was already submitted. The server copy is shown.')
    } else if (code === 'assignment_not_active' || code === 'assignment_not_owned') {
      await refresh('A manager changed this assignment. Your unsaved work stays in this browser.')
    } else {
      setNotice(error instanceof Error ? error.message : 'The annotation could not be saved.')
    }
  }, [refresh])

  const saveNow = useCallback(async () => {
    const current = documentRef.current
    if (!assignment || !current || !editable || saveState === 'saving') return
    setSaveState('saving')
    try {
      const saved = await saveDraft(projectId, assignment.id, current.version, current.objects, token!)
      const latest = documentRef.current ?? current
      setCurrentDocument({ ...latest, version: saved.version })
      setAssignment((value) => value && { ...value, status: saved.status, version: saved.version, draft_saved_at: saved.draft_saved_at })
      if (latest === current) {
        clearRecovery(projectId, assignment.id)
        setSaveState('saved')
      } else {
        saveRecovery(projectId, assignment.id, saved.version, { ...latest, version: saved.version })
        setSaveState('dirty')
      }
    } catch (error) {
      setSaveState('error')
      await handleWriteError(error)
      throw error
    }
  }, [assignment, editable, handleWriteError, projectId, saveState, setCurrentDocument, token])

  useEffect(() => {
    if (saveState !== 'dirty' || !editable) return
    const timer = window.setTimeout(() => void saveNow().catch(() => undefined), AUTOSAVE_MS)
    return () => window.clearTimeout(timer)
  }, [editable, saveNow, saveState])

  const sam = useMutation({
    mutationFn: (point: { x: number; y: number }) => predictSegmentation(
      projectId,
      assignment!,
      [{ type: 'point', coordinates: [point.x, point.y], label: 'foreground' }],
      token!,
    ),
    onSuccess: (prediction) => {
      const current = documentRef.current
      if (!current || !selectedClassId) return
      const objects: AnnotationObject[] = prediction.polygons
        .map((polygon) => Array.isArray(polygon) ? polygon : polygon.coordinates)
        .filter((coordinates) => (coordinates[0]?.length ?? 0) >= 6)
        .map((coordinates) => ({
          id: crypto.randomUUID(),
          class_id: selectedClassId,
          geometry: { type: 'polygon', coordinates },
          attributes: { assisted: true },
        }))
      if (!objects.length) return setNotice('The model did not return a usable mask for that point.')
      changeDocument({ ...current, objects: [...current.objects, ...objects] })
      setSelectedObjectId(objects[0]!.id)
      setNotice(`Added ${objects.length} assisted mask${objects.length === 1 ? '' : 's'}.`)
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : 'Assisted segmentation failed.'),
  })

  const selectClass = useCallback((classId: string) => {
    setSelectedClassId(classId)
    const current = documentRef.current
    if (!current || !editable) return
    if (current.task_type !== 'classification') {
      if (!selectedObjectId) return
      changeDocument({
        ...current,
        objects: current.objects.map((item) => item.id === selectedObjectId
          ? { ...item, class_id: classId }
          : item),
      })
      return
    }
    const existing = current.objects.find((item) => item.class_id === classId)
    const objects: AnnotationObject[] = existing
      ? current.objects.filter((item) => item.id !== existing.id)
      : [...current.objects, { id: crypto.randomUUID(), class_id: classId, geometry: null, attributes: {} }]
    changeDocument({ ...current, objects })
  }, [changeDocument, editable, selectedObjectId])

  async function openItem(item: AssignmentQueueItem) {
    if (assignment?.id === item.id) return
    try {
      if (saveState === 'dirty') await saveNow()
      opening.mutate(item.id)
    } catch {
      setNotice('Save the current annotation before changing images.')
    }
  }

  function keepMine() {
    if (!conflict || !assignment) return
    const value = { ...conflict.document, version: assignment.version }
    setConflict(null)
    setCurrentDocument(value)
    remember(value)
    setSaveState('dirty')
    setNotice('Your version is kept on top of the server copy. Save to store it.')
  }

  function takeServerVersion() {
    if (!assignment) return
    clearRecovery(projectId, assignment.id)
    setConflict(null)
    setNotice(null)
  }

  async function submit() {
    if (!assignment || !document || !editable) return
    const problem = validateDocument(document)
    if (problem) return setNotice(problem)
    if (!document.objects.length && !window.confirm('Submit this image as empty? This records that it contains no objects.')) return
    try {
      setSaveState('saving')
      await submitAssignment(projectId, assignment.id, document.version, document.objects, token!)
      clearRecovery(projectId, assignment.id)
      show(await getAssignment(projectId, assignment.id, token!), 'Submission received.')
      void queue.refetch()
    } catch (error) {
      setSaveState('error')
      await handleWriteError(error)
    }
  }

  const visible = useMemo(
    () => filterAssignments(queue.data?.items ?? [], purposeFilter, stateFilter),
    [purposeFilter, queue.data?.items, stateFilter],
  )
  const navigateQueue = useCallback((direction: -1 | 1) => {
    const item = neighbor(visible, assignment?.id ?? null, direction)
    if (item) void openItem(item)
    // openItem deliberately owns the save-before-switch sequencing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignment?.id, visible])

  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      if (isEditingText(event.target)) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault(); void saveNow().catch(() => undefined); return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault(); if (event.shiftKey) redo(); else undo(); return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault(); redo(); return
      }
      if (event.key === 'ArrowLeft') navigateQueue(-1)
      if (event.key === 'ArrowRight') navigateQueue(1)
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedObjectId && editable) {
        event.preventDefault(); removeSelected()
      }
      if (event.key.toLowerCase() === 'v') setTool('select')
      if (event.key.toLowerCase() === 'h') setTool('pan')
      if (event.key.toLowerCase() === 'b' && bootstrap.data?.project.task_type === 'detection') setTool('box')
      if (event.key.toLowerCase() === 'p' && bootstrap.data?.project.task_type === 'segmentation') setTool('polygon')
      if (event.key.toLowerCase() === 'm' && bootstrap.data?.project.task_type === 'segmentation') setTool('sam-point')
      if (event.key.toLowerCase() === 'n' && editable && bootstrap.data?.project.task_type !== 'classification') {
        setTool(bootstrap.data?.project.task_type === 'detection' ? 'box' : 'polygon')
      }
      if (event.key.toLowerCase() === 'c') {
        setShowClasses(true)
        window.setTimeout(() => classPanelRef.current?.focus(), 0)
      }
      const classIndex = Number(event.key) - 1
      const classItem = classIndex >= 0 ? bootstrap.data?.classes[classIndex] : undefined
      if (classItem) selectClass(classItem.id)
      if (event.key === '?') setShowShortcuts((value) => !value)
    }
    window.addEventListener('keydown', keyboard)
    return () => window.removeEventListener('keydown', keyboard)
  }, [bootstrap.data, editable, navigateQueue, redo, removeSelected, saveNow, selectClass, selectedObjectId, undo])

  if (bootstrap.isLoading) return <div className="centered-status">Loading annotation workspace…</div>
  if (bootstrap.isError) return <WorkspaceError error={bootstrap.error} />
  if (!bootstrap.data) return null

  const counts = queue.data?.counts ?? { pending: 0, in_progress: 0, submitted: 0 }
  const total = counts.pending + counts.in_progress + counts.submitted
  const purposes = [...new Set((queue.data?.items ?? []).map((item) => item.batch_purpose))]

  return (
    <main className={`annotation-workspace ${showClasses ? '' : 'annotation-workspace--classes-hidden'}`}>
      <header className="annotation-header">
        <Link to="/projects" aria-label="Back to projects"><ArrowLeft size={19} /></Link>
        <div><strong>{bootstrap.data.project.name}</strong><span>My assignments</span></div>
        <div className="iteration-progress"><span>{counts.submitted} of {total} submitted</span><progress max={total || 1} value={counts.submitted} /></div>
        <SaveIndicator state={saveState} />
        <span className={`realtime-indicator realtime-indicator--${realtimeStatus}`} title={realtimeStatus === 'live' ? 'Live updates connected' : 'Polling for updates'}><Radio size={13} />{realtimeStatus === 'live' ? 'Live' : 'Polling'}</span>
        <Button variant="ghost" onClick={() => setShowShortcuts((value) => !value)} aria-label="Keyboard shortcuts"><CircleHelp size={19} /></Button>
        <div className="annotation-actions">
          <Button variant="secondary" onClick={() => void saveNow().catch(() => undefined)} disabled={!editable || saveState === 'saving'}><Save size={16} /> Save</Button>
          <Button onClick={submit} disabled={!editable || saveState === 'saving'}><Check size={17} /> Submit</Button>
        </div>
      </header>

      <aside className="annotation-queue" aria-label="My assignments">
        <div className="queue-heading"><strong>My assignments</strong><span>{counts.pending} available · {counts.in_progress} in progress · {counts.submitted} submitted</span></div>
        <div className="queue-filters">
          <label>Batch<select value={purposeFilter} onChange={(event) => setPurposeFilter(event.target.value as BatchPurpose | 'all')}>
            <option value="all">All batches</option>
            {purposes.map((purpose) => <option key={purpose} value={purpose}>{PURPOSE_LABELS[purpose]}</option>)}
          </select></label>
          <label>State<select value={stateFilter} onChange={(event) => setStateFilter(event.target.value as QueueState | 'all')}>
            <option value="all">All states</option>
            <option value="pending">Available</option>
            <option value="in_progress">In progress</option>
            <option value="submitted">Submitted</option>
          </select></label>
        </div>
        <div className="queue-list">
          {queue.isLoading && <p className="queue-message">Loading assignments…</p>}
          {queue.data && !visible.length && <p className="queue-message">No assignments match these filters.</p>}
          {visible.map((item, index) => (
            <button key={item.id} className={`queue-item queue-item--${item.status} ${assignment?.id === item.id ? 'selected' : ''}`} onClick={() => void openItem(item)} aria-current={assignment?.id === item.id}>
              <span className="queue-thumb">{index + 1}</span>
              <span><strong>{item.relative_path.split('/').at(-1)}</strong><small>{PURPOSE_LABELS[item.batch_purpose]} · {STATUS_LABELS[item.status]}</small></span>
              {item.status === 'submitted' && <Check size={14} />}
            </button>
          ))}
        </div>
      </aside>

      <section className="annotation-main">
        <div className="annotation-toolbar" aria-label="Annotation tools">
          <button className={tool === 'select' ? 'active' : ''} onClick={() => setTool('select')} title="Select (V)"><MousePointer2 size={19} /><span>Select</span></button>
          <button className={tool === 'pan' ? 'active' : ''} onClick={() => setTool('pan')} title="Pan (H or Space)"><Hand size={19} /><span>Pan</span></button>
          <span className="tool-divider" />
          {bootstrap.data.project.task_type === 'detection' && <button className={tool === 'box' ? 'active' : ''} onClick={() => setTool('box')} disabled={!editable} title="Bounding box (B)"><Square size={19} /><span>Box</span></button>}
          {bootstrap.data.project.task_type === 'segmentation' && <>
            <button className={tool === 'polygon' ? 'active' : ''} onClick={() => setTool('polygon')} disabled={!editable} title="Polygon (P)"><Pentagon size={19} /><span>Polygon</span></button>
            <button className={tool === 'sam-point' ? 'active' : ''} onClick={() => setTool('sam-point')} disabled={!editable || sam.isPending} title="Assisted mask point (M)"><Sparkles size={19} /><span>Assist</span></button>
          </>}
          <span className="tool-divider" />
          <button onClick={undo} disabled={!undoStack.current.length || !editable} title="Undo (Ctrl Z)"><Undo2 size={18} /><span>Undo</span></button>
          <button onClick={redo} disabled={!redoStack.current.length || !editable} title="Redo (Ctrl Y)"><Redo2 size={18} /><span>Redo</span></button>
          <button onClick={removeSelected} disabled={!selectedObjectId || !editable} title="Delete selected"><Trash2 size={18} /><span>Delete</span></button>
          {!showClasses && <button onClick={() => setShowClasses(true)} title="Show classes (C)"><PanelRightOpen size={19} /><span>Classes</span></button>}
        </div>
        {assignment && document ? (
          <ImageStage
            media={assignment.media}
            document={document}
            classes={bootstrap.data.classes}
            tool={tool}
            selectedClassId={selectedClassId}
            selectedObjectId={selectedObjectId}
            locked={!editable}
            samPending={sam.isPending}
            onChange={changeDocument}
            onSelectObject={setSelectedObjectId}
            onSamPoint={(point) => sam.mutate(point)}
            onNotice={setNotice}
          />
        ) : (
          <div className="canvas-empty">
            <MousePointer2 size={38} />
            <h1>Select an image to begin</h1>
            <p>{queue.data?.items.length ? 'Your assigned images are listed on the left.' : 'You have no assigned images in this project yet.'}</p>
          </div>
        )}
        {conflict && (
          <div className="workspace-notice workspace-notice--conflict" role="alert">
            <AlertTriangle size={17} />
            <span>This image changed on the server after your unsaved work from {new Date(conflict.savedAt).toLocaleTimeString()}.</span>
            <button onClick={keepMine}>Keep my version</button>
            <button onClick={takeServerVersion}>Use server version</button>
          </div>
        )}
        {notice && !conflict && <div className="workspace-notice" role="status"><AlertTriangle size={17} /><span>{notice}</span><button onClick={() => setNotice(null)}>Dismiss</button></div>}
        <div className="image-navigation">
          <Button variant="ghost" onClick={() => navigateQueue(-1)} aria-label="Previous image"><ChevronLeft size={18} /></Button>
          <span>{assignment ? `${assignment.media.relative_path} · ${STATUS_LABELS[assignment.status]}` : 'No image selected'}</span>
          <Button variant="ghost" onClick={() => navigateQueue(1)} aria-label="Next image"><ChevronRight size={18} /></Button>
        </div>
      </section>

      {showClasses && (
        <aside className="class-panel" ref={classPanelRef} tabIndex={-1} aria-label="Classes">
          <div className="class-panel__heading"><div><strong>Classes</strong><span>Press C to focus</span></div><Button variant="ghost" onClick={() => setShowClasses(false)} aria-label="Close classes"><PanelRightClose size={17} /></Button></div>
          <div className="class-options">
            {bootstrap.data.classes.map((item, index) => (
              <button key={item.id} className={selectedClassId === item.id ? 'selected' : ''} onClick={() => selectClass(item.id)}>
                <i style={{ background: item.color }} /><span><strong>{item.name}</strong><small>{bootstrap.data.project.task_type === 'classification' && document?.objects.some((object) => object.class_id === item.id) ? 'Assigned' : `Key ${index + 1}`}</small></span>{(selectedClassId === item.id || document?.objects.some((object) => object.class_id === item.id)) && <Check size={15} />}
              </button>
            ))}
          </div>
          <div className="object-panel"><strong>{bootstrap.data.project.task_type === 'classification' ? 'Labels' : 'Objects'}</strong><span>{document?.objects.length ?? 0}</span>
            <div className="object-list">
              {document?.objects.map((object, index) => {
                const objectClass = bootstrap.data.classes.find((item) => item.id === object.class_id)
                return <button key={object.id} className={selectedObjectId === object.id ? 'selected' : ''} onClick={() => { setSelectedObjectId(object.id); setSelectedClassId(object.class_id) }}><i style={{ background: objectClass?.color }} /><span>{index + 1}. {objectClass?.name ?? 'Unknown class'}</span><small>{object.geometry?.type ?? 'label'}</small></button>
              })}
              {!document?.objects.length && <p>No annotations yet.</p>}
            </div>
          </div>
        </aside>
      )}

      {showShortcuts && <ShortcutPanel onClose={() => setShowShortcuts(false)} />}
    </main>
  )
}

function SaveIndicator({ state }: { state: SaveState }) {
  const labels: Record<SaveState, string> = { idle: 'No changes', dirty: 'Unsaved', saving: 'Saving…', saved: 'Saved', error: 'Save failed' }
  return <span className={`save-indicator save-indicator--${state}`}><Save size={14} />{labels[state]}</span>
}

function WorkspaceError({ error }: { error: Error }) {
  return <div className="centered-status"><div><AlertTriangle size={32} /><h1>Workspace unavailable</h1><p>{error.message}</p><Link to="/projects">Return to projects</Link></div></div>
}

function ShortcutPanel({ onClose }: { onClose: () => void }) {
  return <div className="shortcut-popover" role="dialog" aria-modal="false" aria-label="Keyboard shortcuts"><div><strong>Keyboard shortcuts</strong><button onClick={onClose}>×</button></div><dl><dt>N / Enter</dt><dd>Start or finish object</dd><dt>B / P / M</dt><dd>Box / polygon / assisted mask</dd><dt>V / H</dt><dd>Select / pan</dd><dt>1–9</dt><dd>Choose class</dd><dt>C</dt><dd>Focus classes</dd><dt>Delete</dt><dd>Remove selected object</dd><dt>Ctrl Z / Y</dt><dd>Undo / redo</dd><dt>← / →</dt><dd>Previous / next image</dd><dt>Space</dt><dd>Pan image</dd><dt>+ / −</dt><dd>Zoom</dd><dt>0</dt><dd>Fit image</dd><dt>Ctrl S</dt><dd>Save draft</dd></dl></div>
}

function defaultTool(taskType: AnnotationDocument['task_type']): AnnotationTool {
  if (taskType === 'detection') return 'box'
  if (taskType === 'segmentation') return 'polygon'
  return 'select'
}

function isEditingText(target: EventTarget | null) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || (target instanceof HTMLElement && target.isContentEditable)
}
