import {
  ArrowLeft,
  ArrowRight,
  Check,
  FolderUp,
  Plus,
  Trash2,
  Users,
} from 'lucide-react'
import { useMemo, useRef, useState, type ChangeEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { createProjectWithDataset } from './project-api'
import {
  findDuplicateGroups,
  hashImages,
  scanImageFiles,
  type LocalImage,
  type RejectedLocalFile,
} from './ingest'
import type { ProjectClassInput, ProjectDraft, TaskType } from './types'
import './projects.css'

const steps = ['Basics', 'Classes', 'Learning', 'Team', 'Dataset', 'Review']
const taskOptions: Array<{ value: TaskType; title: string; description: string }> = [
  { value: 'classification', title: 'Classification', description: 'Assign one or more labels to an image.' },
  { value: 'detection', title: 'Object detection', description: 'Locate objects with bounding boxes.' },
  { value: 'segmentation', title: 'Segmentation', description: 'Trace precise object polygons and masks.' },
]
const defaultColors = ['#6558D3', '#E5484D', '#16A085', '#E67E22', '#2980B9']

const initialDraft: ProjectDraft = {
  name: '', description: '', taskType: 'detection',
  classes: [{ id: crypto.randomUUID(), name: '', color: defaultColors[0]! }],
  initialTrainingSize: 20, testSetSize: 10, iterationBatchSize: 20,
  collaborators: [],
}

export function NewProjectPage() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState(initialDraft)
  const [collaboratorInput, setCollaboratorInput] = useState('')
  const [images, setImages] = useState<LocalImage[]>([])
  const [rejected, setRejected] = useState<RejectedLocalFile[]>([])
  const [hashProgress, setHashProgress] = useState<number | null>(null)
  const [submitProgress, setSubmitProgress] = useState(0)
  const [submitMessage, setSubmitMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const duplicateGroups = useMemo(() => findDuplicateGroups(images), [images])
  const totalBytes = images.reduce((sum, image) => sum + image.sizeBytes, 0)

  const validationError = validateStep(step, draft, images)

  function updateDraft(patch: Partial<ProjectDraft>) {
    setDraft((current) => ({ ...current, ...patch }))
  }

  function updateClass(id: string, patch: Partial<ProjectClassInput>) {
    updateDraft({
      classes: draft.classes.map((item) => item.id === id ? { ...item, ...patch } : item),
    })
  }

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files
    if (!files?.length) return
    setError(null)
    const scan = scanImageFiles(files)
    setRejected(scan.rejected)
    setHashProgress(0)
    try {
      const hashed = await hashImages(scan.images, (done, total) => {
        setHashProgress(Math.round((done / total) * 100))
      })
      setImages(hashed)
    } catch {
      setImages([])
      setError('The selected images could not be read. Please choose the folder again.')
    } finally {
      setHashProgress(null)
    }
  }

  async function submit() {
    if (!token || validateAll(draft, images)) return
    setIsSubmitting(true)
    setError(null)
    try {
      await createProjectWithDataset(draft, images, token, (progress, message) => {
        setSubmitProgress(progress)
        setSubmitMessage(message)
      })
      navigate('/projects', { replace: true })
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? `${reason.message}${reason.traceId ? ` (trace ${reason.traceId})` : ''}`
          : reason instanceof Error ? reason.message : 'Project creation failed.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="wizard-page">
      <div className="wizard-heading">
        <Link to="/projects" className="back-link"><ArrowLeft size={17} /> Projects</Link>
        <p className="eyebrow">New project</p>
        <h1>Set up an annotation project</h1>
      </div>

      <ol className="stepper" aria-label="Project setup progress">
        {steps.map((label, index) => (
          <li key={label} className={index === step ? 'current' : index < step ? 'complete' : ''}>
            <span>{index < step ? <Check size={14} /> : index + 1}</span>{label}
          </li>
        ))}
      </ol>

      <section className="wizard-card" aria-labelledby={`step-${step}-title`}>
        {step === 0 && (
          <div className="wizard-section">
            <div><p className="eyebrow">Step 1</p><h2 id="step-0-title">Project basics</h2><p className="muted">Name the dataset and select its computer-vision task.</p></div>
            <div className="field-grid">
              <label className="field field--wide">Project name
                <input value={draft.name} maxLength={120} autoFocus onChange={(e) => updateDraft({ name: e.target.value })} placeholder="Road surface defects" />
              </label>
              <label className="field field--wide">Description <span className="optional">Optional</span>
                <textarea value={draft.description} maxLength={500} onChange={(e) => updateDraft({ description: e.target.value })} placeholder="What should annotators know?" />
              </label>
            </div>
            <fieldset className="task-picker"><legend>Annotation task</legend>
              {taskOptions.map((task) => (
                <label key={task.value} className={draft.taskType === task.value ? 'task-option selected' : 'task-option'}>
                  <input type="radio" name="task" value={task.value} checked={draft.taskType === task.value} onChange={() => updateDraft({ taskType: task.value })} />
                  <span><strong>{task.title}</strong><small>{task.description}</small></span>
                </label>
              ))}
            </fieldset>
          </div>
        )}

        {step === 1 && (
          <div className="wizard-section">
            <div><p className="eyebrow">Step 2</p><h2 id="step-1-title">Object classes</h2><p className="muted">Colors keep labels recognizable throughout annotation.</p></div>
            <div className="class-list">
              {draft.classes.map((item, index) => (
                <div className="class-row" key={item.id}>
                  <span className="class-index">{index + 1}</span>
                  <label className="color-control" aria-label={`Color for class ${index + 1}`}><input type="color" value={item.color} onChange={(e) => updateClass(item.id, { color: e.target.value.toUpperCase() })} /></label>
                  <label className="sr-only" htmlFor={`class-${item.id}`}>Class {index + 1} name</label>
                  <input id={`class-${item.id}`} value={item.name} maxLength={80} onChange={(e) => updateClass(item.id, { name: e.target.value })} placeholder={index === 0 ? 'Pothole' : 'Class name'} />
                  <Button variant="ghost" aria-label={`Remove class ${index + 1}`} disabled={draft.classes.length === 1} onClick={() => updateDraft({ classes: draft.classes.filter((entry) => entry.id !== item.id) })}><Trash2 size={17} /></Button>
                </div>
              ))}
            </div>
            <Button variant="secondary" onClick={() => updateDraft({ classes: [...draft.classes, { id: crypto.randomUUID(), name: '', color: defaultColors[draft.classes.length % defaultColors.length]! }] })}><Plus size={17} /> Add class</Button>
          </div>
        )}

        {step === 2 && (
          <div className="wizard-section">
            <div><p className="eyebrow">Step 3</p><h2 id="step-2-title">Active-learning sizes</h2><p className="muted">Choose how images are allocated when the project starts.</p></div>
            <div className="number-grid">
              <NumberField label="Initial training set" help="Images used to establish the first model." value={draft.initialTrainingSize} onChange={(value) => updateDraft({ initialTrainingSize: value })} />
              <NumberField label="Random test set" help="Held out from active-learning acquisition." value={draft.testSetSize} onChange={(value) => updateDraft({ testSetSize: value })} />
              <NumberField label="Images per iteration" help="New annotations requested in each cycle." value={draft.iterationBatchSize} onChange={(value) => updateDraft({ iterationBatchSize: value })} />
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="wizard-section">
            <div><p className="eyebrow">Step 4</p><h2 id="step-3-title">Annotation team</h2><p className="muted">Invite existing DADA users. You remain the project owner.</p></div>
            <div className="team-callout"><Users aria-hidden="true" /><div><strong>Collaborative by design</strong><p>Images are leased to one annotator at a time during each iteration.</p></div></div>
            <label className="field">Annotator usernames <span className="optional">Optional</span>
              <textarea value={collaboratorInput} onChange={(e) => { setCollaboratorInput(e.target.value); updateDraft({ collaborators: parseCollaborators(e.target.value) }) }} placeholder={'ana\nbruno'} />
              <small>Enter one username per line or separate them with commas.</small>
            </label>
          </div>
        )}

        {step === 4 && (
          <div className="wizard-section">
            <div><p className="eyebrow">Step 5</p><h2 id="step-4-title">Select image folder</h2><p className="muted">Subfolders are scanned recursively. Relative paths are preserved; the local root path is never uploaded.</p></div>
            <input ref={(node) => { fileInputRef.current = node; node?.setAttribute('webkitdirectory', '') }} className="sr-only" type="file" multiple accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" onChange={handleFiles} />
            <button className="folder-drop" type="button" onClick={() => fileInputRef.current?.click()} disabled={hashProgress !== null}>
              <FolderUp size={34} aria-hidden="true" />
              <strong>{images.length ? 'Choose a different folder' : 'Choose a folder'}</strong>
              <span>JPEG, PNG, and WebP · nested folders included</span>
            </button>
            {hashProgress !== null && <Progress value={hashProgress} label={`Checking images… ${hashProgress}%`} />}
            {images.length > 0 && (
              <div className="scan-summary">
                <SummaryStat value={images.length} label="Images ready" />
                <SummaryStat value={formatBytes(totalBytes)} label="Total size" />
                <SummaryStat value={rejected.length} label="Files skipped" />
                <SummaryStat value={duplicateGroups.length} label="Duplicate groups" />
              </div>
            )}
            {rejected.length > 0 && <p className="notice">Skipped {rejected.length} hidden, empty, or unsupported file(s).</p>}
          </div>
        )}

        {step === 5 && (
          <div className="wizard-section">
            <div><p className="eyebrow">Step 6</p><h2 id="step-5-title">Review and create</h2><p className="muted">The project remains recoverable as a draft if an upload is interrupted.</p></div>
            <div className="review-grid">
              <ReviewItem label="Project" value={draft.name} detail={draft.taskType} />
              <ReviewItem label="Dataset" value={`${images.length} images`} detail={formatBytes(totalBytes)} />
              <ReviewItem label="Classes" value={`${draft.classes.length}`} detail={draft.classes.map((item) => item.name).join(', ')} />
              <ReviewItem label="Team" value={`${draft.collaborators.length} collaborator${draft.collaborators.length === 1 ? '' : 's'}`} detail={draft.collaborators.join(', ') || 'Owner only'} />
              <ReviewItem label="Initial / test" value={`${draft.initialTrainingSize} / ${draft.testSetSize}`} detail="images" />
              <ReviewItem label="Iteration batch" value={`${draft.iterationBatchSize}`} detail="images per cycle" />
            </div>
            {duplicateGroups.length > 0 && <p className="notice">{duplicateGroups.length} duplicate content group(s) will be reported to the API for deduplication.</p>}
            {isSubmitting && <Progress value={submitProgress} label={submitMessage} />}
            {error && <div className="form-error" role="alert">{error}<small>The project may have been saved as a draft. Return to Projects before retrying if creation reached the API.</small></div>}
          </div>
        )}

        <footer className="wizard-actions">
          <Button variant="secondary" onClick={() => setStep((current) => current - 1)} disabled={step === 0 || isSubmitting}><ArrowLeft size={17} /> Back</Button>
          <span className="validation-message" aria-live="polite">{validationError}</span>
          {step < steps.length - 1 ? (
            <Button onClick={() => setStep((current) => current + 1)} disabled={Boolean(validationError) || hashProgress !== null}>Continue <ArrowRight size={17} /></Button>
          ) : (
            <Button onClick={submit} disabled={Boolean(validateAll(draft, images)) || isSubmitting}>{isSubmitting ? 'Creating…' : 'Create project'} <Check size={17} /></Button>
          )}
        </footer>
      </section>
    </main>
  )
}

function NumberField({ label, help, value, onChange }: { label: string; help: string; value: number; onChange: (value: number) => void }) {
  return <label className="number-field"><span>{label}</span><input type="number" min={1} step={1} value={value} onChange={(e) => onChange(Math.max(0, Number(e.target.value)))} /><small>{help}</small></label>
}

function SummaryStat({ value, label }: { value: string | number; label: string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>
}

function ReviewItem({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="review-item"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
}

function Progress({ value, label }: { value: number; label: string }) {
  return <div className="progress-block"><div className="progress-label"><span>{label}</span><span>{value}%</span></div><progress max="100" value={value}>{value}%</progress></div>
}

function parseCollaborators(value: string) {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]
}

function validateStep(step: number, draft: ProjectDraft, images: LocalImage[]) {
  if (step === 0 && draft.name.trim().length < 3) return 'Use at least 3 characters for the project name.'
  if (step === 1) {
    if (draft.classes.some((item) => !item.name.trim())) return 'Every class needs a name.'
    const unique = new Set(draft.classes.map((item) => item.name.trim().toLocaleLowerCase()))
    if (unique.size !== draft.classes.length) return 'Class names must be unique.'
  }
  if (step === 2 && [draft.initialTrainingSize, draft.testSetSize, draft.iterationBatchSize].some((size) => !Number.isInteger(size) || size < 1)) return 'All set sizes must be positive whole numbers.'
  if (step === 4) {
    if (!images.length) return 'Select a folder containing supported images.'
    if (draft.initialTrainingSize + draft.testSetSize > images.length) return `The initial and test sets need ${draft.initialTrainingSize + draft.testSetSize} images; this folder has ${images.length}.`
  }
  return ''
}

function validateAll(draft: ProjectDraft, images: LocalImage[]) {
  for (const candidate of [0, 1, 2, 4]) {
    const error = validateStep(candidate, draft, images)
    if (error) return error
  }
  return ''
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = units[0]!
  for (let index = 1; value >= 1024 && index < units.length; index += 1) {
    value /= 1024
    unit = units[index]!
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${unit}`
}
