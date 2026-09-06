import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useRef, useState, type ChangeEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { hashImages, scanImageFiles, type LocalImage } from './ingest'
import {
  createClass,
  createProjectWithDataset,
  cancelUpload,
  getAnnotationPolicy,
  getProject,
  listClasses,
  listMembers,
  removeClass,
  updateClass,
  updateProject,
} from './project-api'
import { loadSetup, saveSetup } from './setup-recovery'
import type { ProjectClass, ProjectDraft } from './types'

export function DraftProjectSetupPage() {
  const { projectId = '' } = useParams()
  const { token } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [images, setImages] = useState<LocalImage[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => getProject(projectId, token!), enabled: Boolean(token && projectId) })
  const classes = useQuery({ queryKey: ['project-classes', projectId], queryFn: () => listClasses(projectId, token!), enabled: Boolean(token && projectId) })
  const members = useQuery({ queryKey: ['project-members', projectId], queryFn: () => listMembers(projectId, token!), enabled: Boolean(token && projectId) })
  const policy = useQuery({ queryKey: ['project-policy', projectId], queryFn: () => getAnnotationPolicy(projectId, token!), enabled: Boolean(token && projectId) })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    queryClient.invalidateQueries({ queryKey: ['project-classes', projectId] })
  }
  const editProject = useMutation({ mutationFn: (form: HTMLFormElement) => updateProject(projectId, { name: new FormData(form).get('name') as string, description: (new FormData(form).get('description') as string) || null, version: project.data!.version }, token!), onSuccess: refresh })
  const saveClass = useMutation({ mutationFn: (entry: ProjectClass) => updateClass(projectId, entry.id, { name: entry.name, color: entry.color, display_order: entry.display_order, version: entry.version }, token!), onSuccess: refresh })
  const addClass = useMutation({ mutationFn: () => createClass(projectId, { name: 'New class', color: '#6558D3', display_order: classes.data?.items.length ?? 0 }, token!), onSuccess: refresh })
  const deleteClass = useMutation({ mutationFn: (id: string) => removeClass(projectId, id, token!), onSuccess: refresh })
  const resume = useMutation({
    mutationFn: () => createProjectWithDataset(buildDraft(), images, token!, (progress, text) => setMessage(`${progress}% — ${text}`), projectId),
    onSuccess: () => navigate('/projects', { replace: true }),
  })
  const activeUploadId = loadSetup()?.projectId === projectId ? loadSetup()?.uploadId : undefined
  const cancel = useMutation({
    mutationFn: () => cancelUpload(activeUploadId!, token!),
    onSuccess: () => { saveSetup({ projectId, stage: 'policy' }); setMessage('The upload was cancelled and its temporary files were permanently purged.') },
  })

  function buildDraft(): ProjectDraft {
    const current = project.data!
    const policyMembers = new Map((members.data?.items ?? []).map((member) => [member.user_id, member.username]))
    return {
      name: current.name, description: current.description ?? '', taskType: current.task_type,
      classes: (classes.data?.items ?? []).map(({ id, name, color }) => ({ id, name, color })),
      initialTrainingSize: current.initial_training_size, testSetSize: current.test_set_size,
      iterationBatchSize: current.iteration_batch_size,
      collaborators: (members.data?.items ?? []).filter((member) => member.role !== 'owner').map((member) => member.username),
      annotationPolicy: policy.data?.mode === 'consensus' ? { mode: 'consensus', annotatorUsernames: policy.data.annotator_ids.map((id) => policyMembers.get(id)).filter((name): name is string => Boolean(name)), resolver: policy.data.resolver ?? '', reviewThreshold: policy.data.review_thresholds?.agreement ?? .75 } : { mode: 'single' },
    }
  }
  async function selectFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = event.currentTarget.files
    if (!files?.length) return
    setMessage('Checking selected images…')
    try {
      setImages(await hashImages(scanImageFiles(files).images, () => {}))
      setMessage(null)
    } catch { setMessage('The selected images could not be read. Choose the folder again.') }
  }
  function changeClass(entry: ProjectClass, patch: Partial<ProjectClass>) { saveClass.mutate({ ...entry, ...patch }) }

  if (project.isLoading || classes.isLoading || members.isLoading || policy.isLoading) return <main className="page-container"><div className="panel status-panel">Loading draft setup…</div></main>
  if (project.isError || classes.isError || members.isError || policy.isError) return <main className="page-container"><div className="panel error-panel" role="alert">This draft could not be loaded.</div></main>
  if (project.data?.status !== 'draft' && project.data?.status !== 'ingesting') return <main className="page-container"><div className="panel status-panel">This project no longer needs setup. <Link to="/projects">Return to projects</Link>.</div></main>

  return <main className="wizard-page"><div className="wizard-heading"><Link className="back-link" to="/projects">Projects</Link><p className="eyebrow">Draft project</p><h1>Resume setup</h1><p className="muted">These fields come from the saved project. Changes are saved before uploading.</p></div>
    <section className="wizard-card"><div className="wizard-section">
      <form className="field-grid" onSubmit={(event) => { event.preventDefault(); editProject.mutate(event.currentTarget) }}><label className="field">Project name<input name="name" key={project.data!.version} defaultValue={project.data!.name} /></label><label className="field">Description<input name="description" key={project.data!.updated_at} defaultValue={project.data!.description ?? ''} /></label><Button disabled={editProject.isPending}>{editProject.isPending ? 'Saving…' : 'Save project details'}</Button></form>
      <div><h2>Classes</h2><div className="class-list">{classes.data!.items.map((entry) => <div className="class-row" key={entry.id}><span className="class-index">{entry.display_order + 1}</span><label className="color-control" aria-label={`Color for ${entry.name}`}><input type="color" defaultValue={entry.color} onChange={(event) => changeClass(entry, { color: event.target.value.toUpperCase() })} /></label><input aria-label={`Name for ${entry.name}`} defaultValue={entry.name} onBlur={(event) => { const name = event.target.value.trim(); if (name && name !== entry.name) changeClass(entry, { name }) }} /><Button variant="ghost" aria-label={`Remove ${entry.name}`} title={`Remove ${entry.name}`} onClick={() => deleteClass.mutate(entry.id)} disabled={classes.data!.items.length <= 1}><Trash2 size={18} aria-hidden="true" /></Button></div>)}</div><div className="class-actions"><Button variant="secondary" onClick={() => addClass.mutate()} disabled={addClass.isPending}>Add class</Button></div></div>
      <div><h2>Team and strategy</h2><p className="muted">Manage members and the annotation policy before resuming the dataset upload.</p><Link className="button button--secondary" to={`/projects/${projectId}/settings`}>Open project settings</Link></div>
      <div><h2>Dataset</h2><input ref={(node) => { fileInput.current = node; node?.setAttribute('webkitdirectory', '') }} className="sr-only" type="file" multiple accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" onChange={selectFiles} /><Button variant="secondary" onClick={() => fileInput.current?.click()}>Choose image folder</Button>{activeUploadId && <Button variant="ghost" disabled={cancel.isPending} onClick={() => { if (window.confirm('Cancel this upload? Its temporary files will be permanently purged.')) cancel.mutate() }}>{cancel.isPending ? 'Cancelling…' : 'Cancel interrupted upload'}</Button>}{images.length > 0 && <p className="notice">{images.length} images ready. Upload resumes from the server-confirmed byte offset.</p>}</div>
      {(message || resume.isError || editProject.isError || saveClass.isError || deleteClass.isError) && <p className="form-error" role="alert">{message ?? errorText(resume.error ?? editProject.error ?? saveClass.error ?? deleteClass.error)}</p>}
      <Button onClick={() => { saveSetup({ projectId, stage: 'policy' }); resume.mutate() }} disabled={!images.length || resume.isPending}>{resume.isPending ? 'Resuming…' : 'Resume upload and activate'}</Button>
    </div></section>
  </main>
}

function errorText(error: unknown) {
  if (error instanceof ApiError && error.status === 409) return 'The draft changed elsewhere. Refresh, review the saved values, and try again.'
  return error instanceof Error ? error.message : 'The draft could not be updated.'
}
