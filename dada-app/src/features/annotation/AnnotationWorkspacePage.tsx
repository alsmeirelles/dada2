import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Hand,
  Lock,
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
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import {
  acquireLease,
  closeIteration,
  completeAnnotation,
  getQueue,
  getWorkspaceBootstrap,
  predictSegmentation,
  releaseLease,
  renewLease,
  saveAnnotationDraft,
} from './annotation-api'
import { ImageStage } from './ImageStage'
import { clearRecovery, loadRecovery, saveRecovery } from './recovery'
import { useProjectEvents } from './useProjectEvents'
import type { AnnotationDocument, AnnotationObject, AnnotationTool, Lease, QueueItem } from './types'
import './annotation.css'

type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

export function AnnotationWorkspacePage() {
  const { projectId = '' } = useParams()
  const { token } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [lease, setLease] = useState<Lease | null>(null)
  const [document, setDocument] = useState<AnnotationDocument | null>(null)
  const documentRef = useRef<AnnotationDocument | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [leaseLost, setLeaseLost] = useState(false)
  const [tool, setTool] = useState<AnnotationTool>('select')
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null)
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null)
  const undoStack = useRef<AnnotationDocument[]>([])
  const redoStack = useRef<AnnotationDocument[]>([])
  const [showClasses, setShowClasses] = useState(true)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const classPanelRef = useRef<HTMLElement>(null)
  const closeAttemptRef = useRef<string | null>(null)

  const bootstrap = useQuery({
    queryKey: ['annotation-workspace', projectId],
    queryFn: () => getWorkspaceBootstrap(projectId, token!),
    enabled: Boolean(projectId && token),
  })
  const iterationId = bootstrap.data?.iteration?.id
  const queue = useQuery({
    queryKey: ['annotation-queue', projectId, iterationId],
    queryFn: () => getQueue(projectId, iterationId!, token!),
    enabled: Boolean(iterationId && token),
    refetchInterval: lease ? 15_000 : 5_000,
  })

  const handleProjectEvent = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['annotation-queue', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['annotation-workspace', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['project-activity', projectId] })
  }, [projectId, queryClient])
  const realtimeStatus = useProjectEvents(projectId, token, handleProjectEvent)

  const closeCurrentIteration = useMutation({
    mutationFn: () => closeIteration(projectId, iterationId!, token!),
    onSuccess: () => navigate(`/projects/${projectId}/activity`, { replace: true }),
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'iteration_incomplete') {
        void queue.refetch()
        window.setTimeout(() => {
          closeAttemptRef.current = null
          void queue.refetch()
        }, 5_000)
      } else {
        setNotice(error instanceof Error ? error.message : 'The iteration could not be closed.')
      }
    },
  })

  useEffect(() => {
    const current = queue.data
    if (!iterationId || !current || closeCurrentIteration.isPending) return
    const total = current.available_count + current.leased_count + current.completed_count
    const signature = `${iterationId}:${current.available_count}:${current.leased_count}:${current.completed_count}`
    if (total > 0 && current.completed_count === total && closeAttemptRef.current !== signature) {
      closeAttemptRef.current = signature
      closeCurrentIteration.mutate()
    }
  }, [closeCurrentIteration, iterationId, queue.data, queue.dataUpdatedAt])

  const setCurrentDocument = useCallback((value: AnnotationDocument | null) => {
    documentRef.current = value
    setDocument(value)
  }, [])

  const changeDocument = useCallback((value: AnnotationDocument) => {
    const current = documentRef.current
    if (current) undoStack.current.push(current)
    if (undoStack.current.length > 100) undoStack.current.shift()
    redoStack.current = []
    setCurrentDocument(value)
    saveRecovery(projectId, value)
    setSaveState('dirty')
  }, [projectId, setCurrentDocument])

  const undo = useCallback(() => {
    const previous = undoStack.current.pop()
    const current = documentRef.current
    if (!previous || !current) return
    redoStack.current.push(current)
    setCurrentDocument({ ...previous, version: current.version })
    setSelectedObjectId(null)
    setSaveState('dirty')
  }, [setCurrentDocument])

  const redo = useCallback(() => {
    const next = redoStack.current.pop()
    const current = documentRef.current
    if (!next || !current) return
    undoStack.current.push(current)
    setCurrentDocument({ ...next, version: current.version })
    setSelectedObjectId(null)
    setSaveState('dirty')
  }, [setCurrentDocument])

  const removeSelected = useCallback(() => {
    const current = documentRef.current
    if (!current || !selectedObjectId) return
    changeDocument({ ...current, objects: current.objects.filter((item) => item.id !== selectedObjectId) })
    setSelectedObjectId(null)
  }, [changeDocument, selectedObjectId])

  const saveNow = useCallback(async () => {
    const current = documentRef.current
    if (!lease || !current || leaseLost || saveState === 'saving') return current
    setSaveState('saving')
    try {
      const saved = await saveAnnotationDraft(lease.lease_id, current, token!)
      const latest = documentRef.current
      if (latest === current) {
        setCurrentDocument(saved)
        setSaveState('saved')
        clearRecovery(projectId, saved.media_id)
      } else if (latest) {
        setCurrentDocument({ ...latest, version: saved.version })
        setSaveState('dirty')
      }
      return saved
    } catch (error) {
      setSaveState('error')
      if (isLeaseConflict(error)) setLeaseLost(true)
      else if (error instanceof ApiError && error.status === 409) {
        setNotice('This annotation changed on the server. Your local recovery snapshot was retained; reopen the image to reconcile it.')
      }
      throw error
    }
  }, [lease, leaseLost, projectId, saveState, setCurrentDocument, token])

  useEffect(() => {
    if (saveState !== 'dirty' || !lease || leaseLost) return
    const current = documentRef.current
    if (current) saveRecovery(projectId, current)
    const timer = window.setTimeout(() => void saveNow().catch(() => undefined), 1_500)
    return () => window.clearTimeout(timer)
  }, [lease, leaseLost, projectId, saveNow, saveState])

  useEffect(() => {
    if (!lease || leaseLost) return
    const delay = Math.max(5, lease.renew_after) * 1_000
    const timer = window.setInterval(async () => {
      try {
        const renewed = await renewLease(lease.lease_id, token!)
        setLease((current) => current ? { ...current, ...renewed } : null)
      } catch (error) {
        if (isLeaseConflict(error)) setLeaseLost(true)
        else setNotice('The lease could not be renewed. Retrying shortly…')
      }
    }, delay)
    return () => window.clearInterval(timer)
  }, [lease, leaseLost, token])

  const acquire = useMutation({
    mutationFn: (mediaId: string | null) => acquireLease(projectId, iterationId!, mediaId, token!),
    onSuccess: (nextLease) => {
      const recovered = loadRecovery(projectId, nextLease.media.id)
      const usingRecovery = Boolean(recovered && recovered.version >= nextLease.annotation.version)
      const recoveredDocument = usingRecovery && recovered
        ? { ...recovered, version: nextLease.annotation.version }
        : nextLease.annotation
      setLease(nextLease)
      setCurrentDocument(recoveredDocument)
      undoStack.current = []
      redoStack.current = []
      setSelectedObjectId(null)
      setSelectedClassId(recoveredDocument.objects[0]?.class_id ?? bootstrap.data?.classes[0]?.id ?? null)
      setTool(defaultTool(recoveredDocument.task_type))
      setSaveState(usingRecovery ? 'dirty' : 'idle')
      setLeaseLost(false)
      setNotice(usingRecovery ? 'Recovered unsaved annotations from this browser tab.' : null)
      void queryClient.invalidateQueries({ queryKey: ['annotation-queue', projectId] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : 'The image is no longer available.'),
  })

  const sam = useMutation({
    mutationFn: (point: { x: number; y: number }) => predictSegmentation(
      projectId,
      lease!,
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
    if (!current) return
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
  }, [changeDocument, selectedObjectId])

  async function openItem(item: QueueItem) {
    if (item.status === 'leased' && item.media_id !== lease?.media.id) return
    if (lease?.media.id === item.media_id) return
    try {
      if (saveState === 'dirty') await saveNow()
      if (lease && !leaseLost) await releaseLease(lease.lease_id, token!)
      setLease(null)
      setCurrentDocument(null)
      setSelectedObjectId(null)
      acquire.mutate(item.media_id)
    } catch {
      setNotice('Save the current annotation before changing images.')
    }
  }

  async function complete() {
    if (!lease || !document) return
    const validation = validateDocument(document)
    if (validation) {
      setNotice(validation)
      return
    }
    try {
      setSaveState('saving')
      await completeAnnotation(lease.lease_id, document, token!)
      clearRecovery(projectId, document.media_id)
      setLease(null)
      setCurrentDocument(null)
      setSelectedObjectId(null)
      setSaveState('idle')
      await queue.refetch()
      setNotice('Annotation completed. Choose the next available image.')
    } catch (error) {
      setSaveState('error')
      if (isLeaseConflict(error)) setLeaseLost(true)
      setNotice(error instanceof Error ? error.message : 'Annotation could not be completed.')
    }
  }

  const navigateQueue = useCallback((direction: -1 | 1) => {
    if (!queue.data?.items.length) return
    const navigable = queue.data.items.filter((item) => item.status !== 'leased' || item.media_id === lease?.media.id)
    const currentIndex = navigable.findIndex((item) => item.media_id === lease?.media.id)
    const nextIndex = Math.min(navigable.length - 1, Math.max(0, currentIndex + direction))
    const item = navigable[nextIndex]
    if (item) void openItem(item)
    // openItem deliberately owns save/release sequencing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lease?.media.id, queue.data?.items])

  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      if (isEditingText(event.target)) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault(); void saveNow(); return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault(); if (event.shiftKey) redo(); else undo(); return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault(); redo(); return
      }
      if (event.key === 'ArrowLeft') navigateQueue(-1)
      if (event.key === 'ArrowRight') navigateQueue(1)
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedObjectId) {
        event.preventDefault(); removeSelected()
      }
      if (event.key.toLowerCase() === 'v') setTool('select')
      if (event.key.toLowerCase() === 'h') setTool('pan')
      if (event.key.toLowerCase() === 'b' && bootstrap.data?.project.task_type === 'detection') setTool('box')
      if (event.key.toLowerCase() === 'p' && bootstrap.data?.project.task_type === 'segmentation') setTool('polygon')
      if (event.key.toLowerCase() === 'm' && bootstrap.data?.project.task_type === 'segmentation') setTool('sam-point')
      if (event.key.toLowerCase() === 'n' && lease && !leaseLost && bootstrap.data?.project.task_type !== 'classification') {
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
  }, [bootstrap.data, lease, leaseLost, navigateQueue, redo, removeSelected, saveNow, selectClass, selectedObjectId, undo])

  if (bootstrap.isLoading) return <div className="centered-status">Loading annotation workspace…</div>
  if (bootstrap.isError) return <WorkspaceError error={bootstrap.error} />
  if (!bootstrap.data?.iteration) return <NoIteration projectName={bootstrap.data?.project.name ?? 'Project'} />

  const available = queue.data?.items.filter((item) => item.status === 'available') ?? []
  const visibleQueueItems = queue.data?.items.filter((item) => item.status !== 'leased' || item.media_id === lease?.media.id) ?? []

  return (
    <main className={`annotation-workspace ${showClasses ? '' : 'annotation-workspace--classes-hidden'}`}>
      <header className="annotation-header">
        <Link to="/projects" aria-label="Back to projects"><ArrowLeft size={19} /></Link>
        <div><strong>{bootstrap.data.project.name}</strong><span>Iteration {bootstrap.data.iteration.number}</span></div>
        <div className="iteration-progress"><span>{queue.data?.completed_count ?? 0} of {bootstrap.data.iteration.total_count} complete</span><progress max={bootstrap.data.iteration.total_count || 1} value={queue.data?.completed_count ?? 0} /></div>
        <SaveIndicator state={saveState} />
        <span className={`realtime-indicator realtime-indicator--${realtimeStatus}`} title={realtimeStatus === 'live' ? 'Live collaboration connected' : 'Polling for collaboration updates'}><Radio size={13} />{realtimeStatus === 'live' ? 'Live' : 'Polling'}</span>
        <Button variant="ghost" onClick={() => setShowShortcuts((value) => !value)} aria-label="Keyboard shortcuts"><CircleHelp size={19} /></Button>
        <Button onClick={complete} disabled={!lease || leaseLost || saveState === 'saving'}><Check size={17} /> Complete</Button>
      </header>

      <aside className="annotation-queue" aria-label="Annotation queue">
        <div className="queue-heading"><strong>Images</strong><span>{available.length} available · {queue.data?.leased_count ?? 0} in use</span></div>
        <div className="queue-list">
          {queue.isLoading && <p className="queue-message">Loading queue…</p>}
          {visibleQueueItems.map((item, index) => (
            <button key={item.media_id} className={`queue-item queue-item--${item.status} ${lease?.media.id === item.media_id ? 'selected' : ''}`} onClick={() => void openItem(item)} disabled={item.status === 'leased' && lease?.media.id !== item.media_id}>
              <span className="queue-thumb">{item.thumbnail_url ? <img src={item.thumbnail_url} alt="" /> : index + 1}</span>
              <span><strong>{item.relative_path.split('/').at(-1)}</strong><small>{item.status === 'leased' ? item.leased_by?.display_name ?? 'In use' : item.status}</small></span>
              {item.status === 'leased' && <Lock size={13} />}
              {item.status === 'completed' && <Check size={14} />}
            </button>
          ))}
        </div>
      </aside>

      <section className="annotation-main">
        <div className="annotation-toolbar" aria-label="Annotation tools">
          <button className={tool === 'select' ? 'active' : ''} onClick={() => setTool('select')} title="Select (V)"><MousePointer2 size={19} /><span>Select</span></button>
          <button className={tool === 'pan' ? 'active' : ''} onClick={() => setTool('pan')} title="Pan (H or Space)"><Hand size={19} /><span>Pan</span></button>
          <span className="tool-divider" />
          {bootstrap.data.project.task_type === 'detection' && <button className={tool === 'box' ? 'active' : ''} onClick={() => setTool('box')} disabled={!lease || leaseLost} title="Bounding box (B)"><Square size={19} /><span>Box</span></button>}
          {bootstrap.data.project.task_type === 'segmentation' && <>
            <button className={tool === 'polygon' ? 'active' : ''} onClick={() => setTool('polygon')} disabled={!lease || leaseLost} title="Polygon (P)"><Pentagon size={19} /><span>Polygon</span></button>
            <button className={tool === 'sam-point' ? 'active' : ''} onClick={() => setTool('sam-point')} disabled={!lease || leaseLost || sam.isPending} title="Assisted mask point (M)"><Sparkles size={19} /><span>Assist</span></button>
          </>}
          <span className="tool-divider" />
          <button onClick={undo} disabled={!undoStack.current.length || !lease || leaseLost} title="Undo (Ctrl Z)"><Undo2 size={18} /><span>Undo</span></button>
          <button onClick={redo} disabled={!redoStack.current.length || !lease || leaseLost} title="Redo (Ctrl Y)"><Redo2 size={18} /><span>Redo</span></button>
          <button onClick={removeSelected} disabled={!selectedObjectId || leaseLost} title="Delete selected"><Trash2 size={18} /><span>Delete</span></button>
          {!showClasses && <button onClick={() => setShowClasses(true)} title="Show classes (C)"><PanelRightOpen size={19} /><span>Classes</span></button>}
        </div>
        {lease ? (
          <ImageStage
            media={lease.media}
            document={document!}
            classes={bootstrap.data.classes}
            tool={tool}
            selectedClassId={selectedClassId}
            selectedObjectId={selectedObjectId}
            locked={leaseLost}
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
            <p>{available.length ? 'Available images are listed on the left.' : 'There are no available images in this iteration.'}</p>
            {available.length > 0 && <Button onClick={() => acquire.mutate(null)} disabled={acquire.isPending}>{acquire.isPending ? 'Claiming…' : 'Claim next image'}</Button>}
          </div>
        )}
        {notice && <div className="workspace-notice" role="status"><AlertTriangle size={17} /><span>{notice}</span><button onClick={() => setNotice(null)}>Dismiss</button></div>}
        <div className="image-navigation">
          <Button variant="ghost" onClick={() => navigateQueue(-1)} aria-label="Previous image"><ChevronLeft size={18} /></Button>
          <span>{lease?.media.relative_path ?? 'No image selected'}</span>
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
  return <div className="centered-status"><div><AlertTriangle size={32} /><h1>Workspace unavailable</h1><p>{error instanceof ApiError && error.status === 404 ? 'The annotation API endpoints are not available yet.' : error.message}</p><Link to="/projects">Return to projects</Link></div></div>
}

function NoIteration({ projectName }: { projectName: string }) {
  return <div className="centered-status"><div><h1>{projectName}</h1><p>No annotation iteration is currently available.</p><Link to="/projects">Return to projects</Link></div></div>
}

function ShortcutPanel({ onClose }: { onClose: () => void }) {
  return <div className="shortcut-popover" role="dialog" aria-modal="false" aria-label="Keyboard shortcuts"><div><strong>Keyboard shortcuts</strong><button onClick={onClose}>×</button></div><dl><dt>N / Enter</dt><dd>Start or finish object</dd><dt>B / P / M</dt><dd>Box / polygon / assisted mask</dd><dt>V / H</dt><dd>Select / pan</dd><dt>1–9</dt><dd>Choose class</dd><dt>C</dt><dd>Focus classes</dd><dt>Delete</dt><dd>Remove selected object</dd><dt>Ctrl Z / Y</dt><dd>Undo / redo</dd><dt>← / →</dt><dd>Previous / next image</dd><dt>Space</dt><dd>Pan image</dd><dt>+ / −</dt><dd>Zoom</dd><dt>0</dt><dd>Fit image</dd><dt>Ctrl S</dt><dd>Save draft</dd></dl></div>
}

function validateDocument(document: AnnotationDocument) {
  if (!document.objects.length) return 'Add at least one annotation before completing this image.'
  if (document.objects.some((item) => !item.class_id)) return 'Every annotation needs a class.'
  if (document.task_type === 'detection' && document.objects.some((item) => item.geometry?.type !== 'rectangle')) return 'Detection annotations must use bounding boxes.'
  if (document.task_type === 'segmentation' && document.objects.some((item) => item.geometry?.type !== 'polygon')) return 'Segmentation annotations must use polygons or masks.'
  if (document.task_type === 'classification' && document.objects.some((item) => item.geometry !== null)) return 'Classification labels cannot contain geometry.'
  return ''
}

function defaultTool(taskType: AnnotationDocument['task_type']): AnnotationTool {
  if (taskType === 'detection') return 'box'
  if (taskType === 'segmentation') return 'polygon'
  return 'select'
}

function isLeaseConflict(error: unknown) {
  return error instanceof ApiError && [
    'lease_expired', 'lease_conflict', 'lease_not_owned', 'lease_revoked',
  ].includes(error.code ?? '')
}

function isEditingText(target: EventTarget | null) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || (target instanceof HTMLElement && target.isContentEditable)
}
