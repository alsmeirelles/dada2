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
  PanelRightClose,
  PanelRightOpen,
  Save,
  Tags,
} from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import {
  acquireLease,
  completeAnnotation,
  getQueue,
  getWorkspaceBootstrap,
  releaseLease,
  renewLease,
  saveAnnotationDraft,
} from './annotation-api'
import { ImageStage } from './ImageStage'
import type { AnnotationDocument, Lease, QueueItem } from './types'
import './annotation.css'

type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

export function AnnotationWorkspacePage() {
  const { projectId = '' } = useParams()
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [lease, setLease] = useState<Lease | null>(null)
  const [document, setDocument] = useState<AnnotationDocument | null>(null)
  const documentRef = useRef<AnnotationDocument | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [leaseLost, setLeaseLost] = useState(false)
  const [panMode, setPanMode] = useState(false)
  const [creatingObject, setCreatingObject] = useState(false)
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null)
  const [showClasses, setShowClasses] = useState(true)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const classPanelRef = useRef<HTMLElement>(null)

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

  const setCurrentDocument = useCallback((value: AnnotationDocument | null) => {
    documentRef.current = value
    setDocument(value)
  }, [])

  const saveNow = useCallback(async () => {
    const current = documentRef.current
    if (!lease || !current || leaseLost || saveState === 'saving') return current
    setSaveState('saving')
    try {
      const saved = await saveAnnotationDraft(lease.lease_id, current, token!)
      setCurrentDocument(saved)
      setSaveState('saved')
      return saved
    } catch (error) {
      setSaveState('error')
      if (isLeaseConflict(error)) setLeaseLost(true)
      throw error
    }
  }, [lease, leaseLost, saveState, setCurrentDocument, token])

  useEffect(() => {
    if (saveState !== 'dirty' || !lease || leaseLost) return
    const timer = window.setTimeout(() => void saveNow(), 1_500)
    return () => window.clearTimeout(timer)
  }, [lease, leaseLost, saveNow, saveState])

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
      setLease(nextLease)
      setCurrentDocument(nextLease.annotation)
      setSelectedClassId(nextLease.annotation.objects[0]?.class_id ?? bootstrap.data?.classes[0]?.id ?? null)
      setSaveState('idle')
      setLeaseLost(false)
      setNotice(null)
      void queryClient.invalidateQueries({ queryKey: ['annotation-queue', projectId] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : 'The image is no longer available.'),
  })

  async function openItem(item: QueueItem) {
    if (item.status === 'leased' && item.media_id !== lease?.media.id) return
    if (lease?.media.id === item.media_id) return
    try {
      if (saveState === 'dirty') await saveNow()
      if (lease && !leaseLost) await releaseLease(lease.lease_id, token!)
      setLease(null)
      setCurrentDocument(null)
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
      setLease(null)
      setCurrentDocument(null)
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
    const currentIndex = queue.data.items.findIndex((item) => item.media_id === lease?.media.id)
    const nextIndex = Math.min(queue.data.items.length - 1, Math.max(0, currentIndex + direction))
    const item = queue.data.items[nextIndex]
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
      if (event.key === 'ArrowLeft') navigateQueue(-1)
      if (event.key === 'ArrowRight') navigateQueue(1)
      if (event.key.toLowerCase() === 'n' && lease && !leaseLost) setCreatingObject((value) => !value)
      if (event.key.toLowerCase() === 'c') {
        setShowClasses(true)
        window.setTimeout(() => classPanelRef.current?.focus(), 0)
      }
      const classIndex = Number(event.key) - 1
      const classItem = classIndex >= 0 ? bootstrap.data?.classes[classIndex] : undefined
      if (classItem) setSelectedClassId(classItem.id)
      if (event.key === '?') setShowShortcuts((value) => !value)
    }
    window.addEventListener('keydown', keyboard)
    return () => window.removeEventListener('keydown', keyboard)
  }, [bootstrap.data, lease, leaseLost, navigateQueue, saveNow])

  if (bootstrap.isLoading) return <div className="centered-status">Loading annotation workspace…</div>
  if (bootstrap.isError) return <WorkspaceError error={bootstrap.error} />
  if (!bootstrap.data?.iteration) return <NoIteration projectName={bootstrap.data?.project.name ?? 'Project'} />

  const available = queue.data?.items.filter((item) => item.status === 'available') ?? []

  return (
    <main className={`annotation-workspace ${showClasses ? '' : 'annotation-workspace--classes-hidden'}`}>
      <header className="annotation-header">
        <Link to="/projects" aria-label="Back to projects"><ArrowLeft size={19} /></Link>
        <div><strong>{bootstrap.data.project.name}</strong><span>Iteration {bootstrap.data.iteration.number}</span></div>
        <div className="iteration-progress"><span>{queue.data?.completed_count ?? 0} of {bootstrap.data.iteration.total_count} complete</span><progress max={bootstrap.data.iteration.total_count || 1} value={queue.data?.completed_count ?? 0} /></div>
        <SaveIndicator state={saveState} />
        <Button variant="ghost" onClick={() => setShowShortcuts((value) => !value)} aria-label="Keyboard shortcuts"><CircleHelp size={19} /></Button>
        <Button onClick={complete} disabled={!lease || leaseLost || saveState === 'saving'}><Check size={17} /> Complete</Button>
      </header>

      <aside className="annotation-queue" aria-label="Annotation queue">
        <div className="queue-heading"><strong>Images</strong><span>{available.length} available</span></div>
        <div className="queue-list">
          {queue.isLoading && <p className="queue-message">Loading queue…</p>}
          {queue.data?.items.map((item, index) => (
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
          <button className={!panMode ? 'active' : ''} onClick={() => setPanMode(false)} title="Select (V)"><MousePointer2 size={19} /><span>Select</span></button>
          <button className={panMode ? 'active' : ''} onClick={() => setPanMode(true)} title="Pan (hold Space)"><Hand size={19} /><span>Pan</span></button>
          <span className="tool-divider" />
          <button className={creatingObject ? 'active' : ''} onClick={() => setCreatingObject((value) => !value)} disabled={!lease || leaseLost} title="New object (N)"><Tags size={19} /><span>{creatingObject ? 'Finish' : 'New'}</span></button>
          {!showClasses && <button onClick={() => setShowClasses(true)} title="Show classes (C)"><PanelRightOpen size={19} /><span>Classes</span></button>}
        </div>
        {lease ? (
          <ImageStage media={lease.media} panMode={panMode} locked={leaseLost} />
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
              <button key={item.id} className={selectedClassId === item.id ? 'selected' : ''} onClick={() => setSelectedClassId(item.id)}>
                <i style={{ background: item.color }} /><span><strong>{item.name}</strong><small>Key {index + 1}</small></span>{selectedClassId === item.id && <Check size={15} />}
              </button>
            ))}
          </div>
          <div className="object-panel"><strong>Objects</strong><span>{document?.objects.length ?? 0}</span><p>Task-specific annotation objects appear here in task 5.</p></div>
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
  return <div className="shortcut-popover" role="dialog" aria-modal="false" aria-label="Keyboard shortcuts"><div><strong>Keyboard shortcuts</strong><button onClick={onClose}>×</button></div><dl><dt>N</dt><dd>Start or finish object</dd><dt>C</dt><dd>Focus classes</dd><dt>← / →</dt><dd>Previous / next image</dd><dt>Space</dt><dd>Pan image</dd><dt>+ / −</dt><dd>Zoom</dd><dt>0</dt><dd>Fit image</dd><dt>Ctrl S</dt><dd>Save draft</dd></dl></div>
}

function validateDocument(document: AnnotationDocument) {
  if (!document.objects.length) return 'Add at least one annotation before completing this image.'
  if (document.objects.some((item) => !item.class_id)) return 'Every annotation needs a class.'
  return ''
}

function isLeaseConflict(error: unknown) {
  return error instanceof ApiError && (error.status === 409 || error.code === 'lease_expired')
}

function isEditingText(target: EventTarget | null) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || (target instanceof HTMLElement && target.isContentEditable)
}
