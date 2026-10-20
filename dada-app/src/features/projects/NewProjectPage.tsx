import {
  ArrowLeft,
  ArrowRight,
  Check,
  FolderUp,
  Plus,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { getCapabilities, type PipelineCapability } from '../../api/capabilities'
import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { DatasetPreparationPanel } from './DatasetPreparationPanel'
import {
  createProjectWithDataset,
  deleteProject,
  listEligibleAnnotators,
  minimumDatasetSize,
  resolveDraftSplitSize,
  resolvedFirstTrainingSize,
} from './project-api'
import { ResolverConfigForm } from './ResolverConfigForm'
import { configurationIsValid, defaultConfiguration, summarizeSettings } from './resolver-config'
import { resolverLabel } from './resolver-label'
import { clearSetup, loadSetup } from './setup-recovery'
import {
  findDuplicateGroups,
  hashImages,
  mergeSelections,
  scanImageFiles,
  type LocalImage,
  type RejectedLocalFile,
} from './ingest'
import type { Project, ProjectClassInput, ProjectDraft, TaskType } from './types'

const steps = ['Basics', 'Classes', 'Learning', 'Team', 'Dataset', 'Review', 'Prepare']
const PREPARE_STEP = steps.length - 1
const taskOptions: Array<{ value: TaskType; title: string; description: string }> = [
  { value: 'classification', title: 'Classification', description: 'Assign one or more labels to an image.' },
  { value: 'detection', title: 'Object detection', description: 'Locate objects with bounding boxes.' },
  { value: 'segmentation', title: 'Segmentation', description: 'Trace precise object polygons and masks.' },
]
const defaultColors = ['#6558D3', '#E5484D', '#16A085', '#E67E22', '#2980B9']
const IMAGE_ACCEPT = 'image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp'
const RANDOM_ACQUISITION = 'Randomly selected from the remaining eligible training images.'

const initialDraft: ProjectDraft = {
  name: '', description: '', taskType: 'detection',
  classes: [{ id: crypto.randomUUID(), name: '', color: defaultColors[0]! }],
  acquisitionStrategy: 'random',
  datasetLayout: 'split',
  initialTrainingSize: null,
  testSetSize: 10,
  testSetUnit: 'count',
  validationSetSize: 10,
  validationSetUnit: 'percentage',
  iterationBatchSize: 20,
  collaborators: [],
  annotationPolicy: { mode: 'single' },
}

export function NewProjectPage() {
  const { token, user } = useAuth()
  const navigate = useNavigate()
  const folderInputRef = useRef<HTMLInputElement>(null)
  const filesInputRef = useRef<HTMLInputElement>(null)
  const [serverProjectId, setServerProjectId] = useState<string | null>(null)
  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState(initialDraft)
  const [images, setImages] = useState<LocalImage[]>([])
  const [rejected, setRejected] = useState<RejectedLocalFile[]>([])
  const [hashProgress, setHashProgress] = useState<number | null>(null)
  const [submitProgress, setSubmitProgress] = useState(0)
  const [submitMessage, setSubmitMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<Project | null>(null)
  const duplicateGroups = useMemo(() => findDuplicateGroups(images), [images])
  const totalBytes = images.reduce((sum, image) => sum + image.sizeBytes, 0)
  const consensusPolicy = draft.annotationPolicy.mode === 'consensus' ? draft.annotationPolicy : null
  const capabilities = useQuery({
    queryKey: ['capabilities'],
    queryFn: getCapabilities,
    staleTime: Infinity,
  })
  const pipeline = capabilities.data?.consensus_pipelines[draft.taskType]
  const users = useQuery({
    queryKey: ['eligible-annotators'],
    queryFn: () => listEligibleAnnotators(token!),
    enabled: Boolean(token),
    staleTime: 60_000,
  })
  const selectableAnnotators = (users.data ?? []).filter((candidate) => candidate.id !== user?.id)
  const usersByUsername = new Map((users.data ?? []).map((candidate) => [candidate.username, candidate]))
  const consensusUsernames = [...new Set([
    ...(user ? [user.username] : []),
    ...draft.collaborators,
  ])]

  const validationError = validateStep(step, draft, images, pipeline)

  useEffect(() => {
    if (!pipeline || draft.annotationPolicy.mode !== 'consensus' || draft.annotationPolicy.resolver === pipeline.id) return
    setDraft((current) => current.annotationPolicy.mode === 'consensus'
      ? { ...current, annotationPolicy: { ...current.annotationPolicy, resolver: pipeline.id, configuration: defaultConfiguration(current.taskType, pipeline) } }
      : current)
  }, [draft.annotationPolicy, pipeline])

  function updateDraft(patch: Partial<ProjectDraft>) {
    setDraft((current) => ({ ...current, ...patch }))
  }

  function updateClass(id: string, patch: Partial<ProjectClassInput>) {
    updateDraft({
      classes: draft.classes.map((item) => item.id === id ? { ...item, ...patch } : item),
    })
  }

  function toggleCollaborator(username: string, selected: boolean) {
    setDraft((current) => {
      const collaborators = selected
        ? [...new Set([...current.collaborators, username])]
        : current.collaborators.filter((candidate) => candidate !== username)
      const annotationPolicy = current.annotationPolicy.mode === 'consensus'
        ? {
            ...current.annotationPolicy,
            annotatorUsernames: selected
              ? [...new Set([...current.annotationPolicy.annotatorUsernames, username])]
              : current.annotationPolicy.annotatorUsernames.filter((candidate) => candidate !== username),
          }
        : current.annotationPolicy
      return { ...current, collaborators, annotationPolicy }
    })
  }

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    // The browser's FileList is live: copy it before clearing the input so the same folder can be picked again.
    const files = [...(event.currentTarget.files ?? [])]
    event.currentTarget.value = ''
    if (!files.length) return
    setError(null)
    const scan = scanImageFiles(files)
    setHashProgress(0)
    try {
      const hashed = await hashImages(scan.images, (done, total) => {
        setHashProgress(Math.round((done / total) * 100))
      })
      const merged = mergeSelections(images, hashed)
      setImages(merged.images)
      setRejected([...rejected, ...scan.rejected, ...merged.rejected])
    } catch {
      setError('The selected images could not be read. Please choose them again.')
    } finally {
      setHashProgress(null)
    }
  }

  function clearSelection() {
    setImages([])
    setRejected([])
  }

  async function submit() {
    if (!token || validateAll(draft, images, pipeline)) return
    setIsSubmitting(true)
    setError(null)
    const before = loadSetup()?.projectId
    try {
      const project = await createProjectWithDataset(draft, images, token, (progress, message) => {
        setSubmitProgress(progress)
        setSubmitMessage(message)
      }, serverProjectId ?? undefined)
      setServerProjectId(project.id)
      setCreated(project)
      setStep(PREPARE_STEP)
    } catch (reason) {
      const saved = loadSetup()?.projectId
      const draftId = saved && saved !== before ? saved : serverProjectId
      setServerProjectId(draftId)
      const detail = reason instanceof ApiError
        ? `${reason.message}${reason.traceId ? ` (trace ${reason.traceId})` : ''}`
        : reason instanceof Error ? reason.message : 'Project creation failed.'
      setError(
        draftId
          ? `${detail} The project was saved as a draft — try again to resume where it stopped, or cancel it.`
          : detail,
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  async function cancelCreation() {
    const message = serverProjectId
      ? 'Cancel this project? The draft and everything already uploaded will be permanently deleted.'
      : 'Cancel this project? Everything entered so far will be discarded.'
    if (!window.confirm(message)) return
    try {
      if (serverProjectId && token) await deleteProject(serverProjectId, token)
      if (serverProjectId && loadSetup()?.projectId === serverProjectId) clearSetup()
      navigate('/projects', { replace: true })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The project could not be cancelled.')
    }
  }

  return (
    <main className="wizard-page">
      <div className="wizard-heading">
        <Link to="/projects" className="back-link"><ArrowLeft size={17} /> Projects</Link>
        <p className="eyebrow">New project</p>
        <h1>Set up an annotation project</h1>
        <Button variant="ghost" className="wizard-cancel" onClick={cancelCreation} disabled={isSubmitting}><X size={17} /> Cancel project creation</Button>
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
                <input value={draft.name} maxLength={120} onChange={(e) => updateDraft({ name: e.target.value })} placeholder="Road surface defects" />
              </label>
              <label className="field field--wide">Description <span className="optional">Optional</span>
                <textarea value={draft.description} maxLength={500} onChange={(e) => updateDraft({ description: e.target.value })} placeholder="What should annotators know?" />
              </label>
            </div>
            <fieldset className="task-picker"><legend>Annotation task</legend>
              {taskOptions.map((task) => (
                <label aria-label={task.title} htmlFor={`task-${task.value}`} key={task.value} className={draft.taskType === task.value ? 'task-option selected' : 'task-option'}>
                  <input id={`task-${task.value}`} type="radio" name="task" value={task.value} checked={draft.taskType === task.value} onChange={() => updateDraft({ taskType: task.value })} />
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
            <div><p className="eyebrow">Step 3</p><h2 id="step-2-title">Acquisition, layout, and sizes</h2><p className="muted">The acquisition strategy only decides how later training batches are chosen. It never changes the fixed validation and test sets or the initial annotation batches.</p></div>
            <fieldset className="task-picker"><legend>Acquisition strategy</legend>
              <label aria-label="Random acquisition" htmlFor="acquisition-random" className={draft.acquisitionStrategy === 'random' ? 'task-option selected' : 'task-option'}>
                <input id="acquisition-random" type="radio" name="acquisition-strategy" checked={draft.acquisitionStrategy === 'random'} onChange={() => updateDraft({ acquisitionStrategy: 'random' })} />
                <span><strong>Random acquisition</strong><small>{RANDOM_ACQUISITION}</small></span>
              </label>
              <label aria-label="Active learning" htmlFor="acquisition-active-learning" className={draft.acquisitionStrategy === 'active_learning' ? 'task-option selected' : 'task-option'}>
                <input id="acquisition-active-learning" type="radio" name="acquisition-strategy" checked={draft.acquisitionStrategy === 'active_learning'} onChange={() => updateDraft({ acquisitionStrategy: 'active_learning', datasetLayout: 'split' })} />
                <span><strong>Active learning</strong><small>A learning model chooses later training batches once the learning adapter is available.</small></span>
              </label>
            </fieldset>
            <fieldset className="task-picker"><legend>Dataset layout</legend>
              <label aria-label="Split dataset" htmlFor="layout-split" className={draft.datasetLayout === 'split' ? 'task-option selected' : 'task-option'}>
                <input id="layout-split" type="radio" name="dataset-layout" checked={draft.datasetLayout === 'split'} onChange={() => updateDraft({ datasetLayout: 'split' })} />
                <span><strong>Split dataset</strong><small>Fixed validation and test sets, a first training batch, then acquisition batches.</small></span>
              </label>
              <label aria-label="One static annotation batch" htmlFor="layout-single-batch" className={draft.datasetLayout === 'single_batch' ? 'task-option selected' : 'task-option'}>
                <input id="layout-single-batch" type="radio" name="dataset-layout" disabled={draft.acquisitionStrategy === 'active_learning'} checked={draft.datasetLayout === 'single_batch'} onChange={() => updateDraft({ datasetLayout: 'single_batch' })} />
                <span><strong>One static annotation batch</strong><small>{draft.acquisitionStrategy === 'active_learning' ? 'Only available with random acquisition.' : 'Every image is annotated once. No training, evaluation, or acquisition loop.'}</small></span>
              </label>
            </fieldset>
            {draft.datasetLayout === 'split' ? <>
              <div className="number-grid">
                <SplitSizeField label="Validation set" help="Fixed when the dataset is prepared; every image is annotated." value={draft.validationSetSize} unit={draft.validationSetUnit} onValueChange={(value) => updateDraft({ validationSetSize: value })} onUnitChange={(unit) => updateDraft({ validationSetUnit: unit })} />
                <SplitSizeField label="Test set" help="Fixed when the dataset is prepared and held out from acquisition." value={draft.testSetSize} unit={draft.testSetUnit} onValueChange={(value) => updateDraft({ testSetSize: value })} onUnitChange={(unit) => updateDraft({ testSetUnit: unit })} />
                <NumberField label="Images per iteration" help="Size of each later acquisition batch." value={draft.iterationBatchSize} onChange={(value) => updateDraft({ iterationBatchSize: value })} />
                <OptionalNumberField label="First training batch" help={`Optional. Leave empty to use the images-per-iteration size (${draft.iterationBatchSize}).`} value={draft.initialTrainingSize} onChange={(value) => updateDraft({ initialTrainingSize: value })} />
              </div>
              <p className="notice">Preparation annotates every validation and test image plus the first training batch. The other training images stay in the unlabeled pool until acquisition, which starts only after every initial image has an accepted resolution. Validation and test images are never eligible, and a final batch may be smaller than the images-per-iteration size.</p>
            </> : <p className="notice">Single or consensus annotation still applies. The project closes when its one batch is resolved.</p>}
          </div>
        )}

        {step === 3 && (
          <div className="wizard-section">
            <div><p className="eyebrow">Step 4</p><h2 id="step-3-title">Team and annotation strategy</h2><p className="muted">Invite existing DADA users, then choose independent single or consensus annotation.</p></div>
            <div className="team-callout"><Users aria-hidden="true" /><div><strong>Independent assignments</strong><p>Consensus members annotate the same images independently. Ambiguous results are sent to manager review.</p></div></div>
            <fieldset className="user-picker"><legend>Project annotators <span className="optional">Optional</span></legend>
              {users.isPending && <p className="muted">Loading active users…</p>}
              {users.isError && <p className="form-error" role="alert">Active users could not be loaded. Reload the page to try again.</p>}
              {users.isSuccess && selectableAnnotators.length === 0 && <p className="muted">There are no other active users to add.</p>}
              {selectableAnnotators.map((candidate) => (
                <label key={candidate.id}>
                  <input type="checkbox" aria-label={`${candidate.display_name} (@${candidate.username})`} checked={draft.collaborators.includes(candidate.username)} onChange={(event) => toggleCollaborator(candidate.username, event.target.checked)} />
                  <span><strong>{candidate.display_name}</strong><small>@{candidate.username}</small></span>
                </label>
              ))}
              <small>Only active DADA users are shown. Selected users join the project as annotators.</small>
            </fieldset>
            <fieldset className="task-picker"><legend>Annotation strategy</legend>
              <label aria-label="Single annotation" htmlFor="annotation-mode-single" className={draft.annotationPolicy.mode === 'single' ? 'task-option selected' : 'task-option'}>
                <input id="annotation-mode-single" type="radio" name="annotation-mode" checked={draft.annotationPolicy.mode === 'single'} onChange={() => updateDraft({ annotationPolicy: { mode: 'single' } })} />
                <span><strong>Single annotation</strong><small>One submission resolves each selected image.</small></span>
              </label>
              <label aria-label="Consensus annotation" htmlFor="annotation-mode-consensus" className={draft.annotationPolicy.mode === 'consensus' ? 'task-option selected' : 'task-option'}>
                <input id="annotation-mode-consensus" type="radio" name="annotation-mode" checked={draft.annotationPolicy.mode === 'consensus'} onChange={() => updateDraft({ annotationPolicy: { mode: 'consensus', annotatorUsernames: consensusUsernames, requiredAnnotations: 2, requiredReviewers: 1, resolver: pipeline?.id ?? '', configuration: pipeline ? defaultConfiguration(draft.taskType, pipeline) : { parameters: {}, review_thresholds: {} }, requireIndependentAdjudicator: false } })} />
                <span><strong>Consensus annotation</strong><small>A fixed cohort labels each image independently.</small></span>
              </label>
            </fieldset>
            {consensusPolicy && (
              <div className="field-grid">
                <label className="field" htmlFor="consensus-annotators">Consensus annotators
                  <select id="consensus-annotators" multiple value={consensusPolicy.annotatorUsernames} onChange={(event) => updateDraft({ annotationPolicy: { ...consensusPolicy, annotatorUsernames: [...event.currentTarget.selectedOptions].map((option) => option.value) } })}>
                    {consensusUsernames.map((username) => <option key={username} value={username}>{username === user?.username ? `${username} (you, owner)` : `${usersByUsername.get(username)?.display_name ?? username} (@${username})`}</option>)}
                  </select>
                  <small>The pool must fit the initial cohort and distinct review cohort. You, as the project owner, may annotate too.</small>
                </label>
                <NumberField label="Initial annotations per image" help="Exact number of independent full-image assignments." value={consensusPolicy.requiredAnnotations} onChange={(value) => updateDraft({ annotationPolicy: { ...consensusPolicy, requiredAnnotations: value } })} />
                <NumberField label="Additional reviewers per escalated candidate" help="Created only when automatic resolution needs more evidence." value={consensusPolicy.requiredReviewers} onChange={(value) => updateDraft({ annotationPolicy: { ...consensusPolicy, requiredReviewers: value } })} />
              </div>
            )}
            {consensusPolicy && (pipeline && consensusPolicy.resolver === pipeline.id
              ? <ResolverConfigForm
                taskType={draft.taskType}
                pipeline={pipeline}
                value={consensusPolicy.configuration}
                onChange={(configuration) => updateDraft({ annotationPolicy: { ...consensusPolicy, configuration } })}
                eligibility={{ status: 'no_project' }}
                requireIndependentAdjudicator={consensusPolicy.requireIndependentAdjudicator}
                onRequireIndependentAdjudicatorChange={(requireIndependentAdjudicator) => updateDraft({ annotationPolicy: { ...consensusPolicy, requireIndependentAdjudicator } })}
              />
              : <p className="notice">{capabilities.isError ? 'The resolver catalog could not be loaded from the API. Reload the page to try again.' : 'Loading the resolver catalog from the API…'}</p>)}
          </div>
        )}

        {step === 4 && (
          <div className="wizard-section">
            <div><p className="eyebrow">Step 5</p><h2 id="step-4-title">Select images</h2><p className="muted">Add one or more folders, or individual files. Subfolders are scanned recursively. Relative paths are preserved; the local root path is never uploaded.</p></div>
            <input ref={(node) => { folderInputRef.current = node; node?.setAttribute('webkitdirectory', '') }} className="sr-only" type="file" multiple accept={IMAGE_ACCEPT} onChange={handleFiles} aria-label="Image folder" />
            <input ref={filesInputRef} className="sr-only" type="file" multiple accept={IMAGE_ACCEPT} onChange={handleFiles} aria-label="Image files" />
            <button className="folder-drop" type="button" onClick={() => folderInputRef.current?.click()} disabled={hashProgress !== null}>
              <FolderUp size={34} aria-hidden="true" />
              <strong>{images.length ? 'Add another folder' : 'Choose a folder'}</strong>
              <span>JPEG, PNG, and WebP · nested folders included</span>
            </button>
            <div className="selection-actions">
              <Button variant="secondary" onClick={() => filesInputRef.current?.click()} disabled={hashProgress !== null}><Plus size={17} /> {images.length ? 'Add more files' : 'Choose files'}</Button>
              {images.length > 0 && <Button variant="ghost" onClick={clearSelection} disabled={hashProgress !== null}><Trash2 size={17} /> Clear selection</Button>}
            </div>
            {hashProgress !== null && <Progress value={hashProgress} label={`Checking images… ${hashProgress}%`} />}
            {images.length > 0 && (
              <div className="scan-summary">
                <SummaryStat value={images.length} label="Images ready" />
                <SummaryStat value={formatBytes(totalBytes)} label="Total size" />
                <SummaryStat value={rejected.length} label="Files skipped" />
                <SummaryStat value={duplicateGroups.length} label="Duplicate groups" />
              </div>
            )}
            {rejected.length > 0 && <p className="notice">Skipped {rejected.length} hidden, empty, unsupported, or already-selected file(s).</p>}
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
              {draft.datasetLayout === 'split' ? <>
                <ReviewItem label="Validation / test / first training" value={splitSummary(draft, images.length)} detail="fixed when the dataset is prepared" />
                <ReviewItem label="Unlabeled training pool" value={`${trainingPoolSize(draft, images.length)} images`} detail={`later batches of ${draft.iterationBatchSize}`} />
                <ReviewItem label="Acquisition" value={draft.acquisitionStrategy === 'random' ? 'Random acquisition' : 'Active learning'} detail={draft.acquisitionStrategy === 'random' ? 'Randomly selected from the eligible unlabeled training pool after the preceding image batch has an accepted canonical resolution' : 'Chosen by the learning adapter once it is available'} />
              </> : <ReviewItem label="Dataset layout" value="One static batch" detail="every image annotated once; random acquisition, no later batches" />}
              <ReviewItem label="Strategy" value={draft.annotationPolicy.mode === 'single' ? 'Single annotation' : 'Consensus'} detail={strategySummary(draft, images.length)} />
              {draft.annotationPolicy.mode === 'consensus' && <>
                <ReviewItem label="Review escalation" value={`${draft.annotationPolicy.requiredReviewers} additional reviewer${draft.annotationPolicy.requiredReviewers === 1 ? '' : 's'} per candidate`} detail="Total review work depends on automatic resolution outcomes" />
                <ReviewItem label="Resolver" value={resolverLabel(draft.annotationPolicy.resolver)} detail={settingsLine(draft.annotationPolicy.configuration.parameters)} />
                <ReviewItem label="Review thresholds" value={settingsLine(draft.annotationPolicy.configuration.review_thresholds)} detail="Results below these values go to review" />
                <ReviewItem label="Adjudicator" value={draft.annotationPolicy.requireIndependentAdjudicator ? 'Must be independent' : 'Contributors may adjudicate'} detail={draft.annotationPolicy.requireIndependentAdjudicator ? 'Contributors to an image cannot decide it' : 'With a rationale; the conflict is recorded'} />
              </>}
            </div>
            {duplicateGroups.length > 0 && <p className="notice">{duplicateGroups.length} duplicate content group(s) will be reported to the API for deduplication.</p>}
            {isSubmitting && <Progress value={submitProgress} label={submitMessage} />}
          </div>
        )}

        {error && <div className="form-error" role="alert">{error}</div>}

        {step === PREPARE_STEP && created && (
          <DatasetPreparationPanel project={created} onActivated={() => navigate('/projects', { replace: true })} />
        )}

        {step !== PREPARE_STEP && <footer className="wizard-actions">
          <Button variant="secondary" onClick={() => setStep((current) => current - 1)} disabled={step === 0 || isSubmitting}><ArrowLeft size={17} /> Back</Button>
          <span className="validation-message" aria-live="polite">{validationError}</span>
          {step < PREPARE_STEP - 1 ? (
            <Button onClick={() => setStep((current) => current + 1)} disabled={Boolean(validationError) || hashProgress !== null}>Continue <ArrowRight size={17} /></Button>
          ) : (
            <Button onClick={submit} disabled={Boolean(validateAll(draft, images, pipeline)) || isSubmitting}>{isSubmitting ? 'Creating…' : 'Create and prepare'} <Check size={17} /></Button>
          )}
        </footer>}
      </section>
    </main>
  )
}

function NumberField({ label, help, value, onChange }: { label: string; help: string; value: number; onChange: (value: number) => void }) {
  return <label className="number-field"><span>{label}</span><input type="number" min={1} step={1} value={value} onChange={(e) => onChange(Math.max(0, Number(e.target.value)))} /><small>{help}</small></label>
}

function OptionalNumberField({ label, help, value, onChange }: { label: string; help: string; value: number | null; onChange: (value: number | null) => void }) {
  return <label className="number-field"><span>{label} <span className="optional">Optional</span></span><input type="number" min={1} step={1} value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? null : Math.max(0, Number(e.target.value)))} /><small>{help}</small></label>
}

function SplitSizeField({ label, help, value, unit, onValueChange, onUnitChange }: {
  label: string
  help: string
  value: number
  unit: ProjectDraft['testSetUnit']
  onValueChange: (value: number) => void
  onUnitChange: (unit: ProjectDraft['testSetUnit']) => void
}) {
  return <label className="number-field split-size-field"><span>{label}</span><span className="split-size-control"><input type="number" min={unit === 'count' ? 1 : 0.1} max={unit === 'percentage' ? 99.9 : undefined} step={unit === 'count' ? 1 : 0.1} value={value} onChange={(event) => onValueChange(Math.max(0, Number(event.target.value)))} /><select aria-label={`${label} unit`} value={unit} onChange={(event) => onUnitChange(event.target.value as ProjectDraft['testSetUnit'])}><option value="count">images</option><option value="percentage">%</option></select></span><small>{help}</small></label>
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

function settingsLine(settings: Record<string, unknown>) {
  return summarizeSettings(settings).map((line) => `${line.label}: ${line.value}`).join(' · ')
}

function validateStep(step: number, draft: ProjectDraft, images: LocalImage[], pipeline: PipelineCapability | undefined) {
  if (step === 0 && draft.name.trim().length < 3) return 'Use at least 3 characters for the project name.'
  if (step === 1) {
    if (draft.classes.some((item) => !item.name.trim())) return 'Every class needs a name.'
    const unique = new Set(draft.classes.map((item) => item.name.trim().toLocaleLowerCase()))
    if (unique.size !== draft.classes.length) return 'Class names must be unique.'
  }
  if (step === 2 && draft.datasetLayout === 'split') {
    if (!Number.isInteger(draft.iterationBatchSize) || draft.iterationBatchSize < 1) return 'Images per iteration must be a positive whole number.'
    if (draft.initialTrainingSize !== null && (!Number.isInteger(draft.initialTrainingSize) || draft.initialTrainingSize < 1)) return 'The first training batch must be empty or a positive whole number.'
    for (const [value, unit] of [[draft.testSetSize, draft.testSetUnit], [draft.validationSetSize, draft.validationSetUnit]] as const) {
      if (value <= 0 || (unit === 'count' && !Number.isInteger(value)) || (unit === 'percentage' && value >= 100)) return 'Validation and test sizes must be positive whole-image counts or percentages below 100.'
    }
    if (minimumDatasetSize(draft) === null) return 'Together, the validation and test percentages must stay below 100% to leave room for training images.'
  }
  if (step === 3 && draft.annotationPolicy.mode === 'consensus') {
    if (!Number.isInteger(draft.annotationPolicy.requiredAnnotations) || draft.annotationPolicy.requiredAnnotations < 2) return 'Initial consensus annotations must be a whole number of at least two.'
    if (!Number.isInteger(draft.annotationPolicy.requiredReviewers) || draft.annotationPolicy.requiredReviewers < 1) return 'Additional reviewers must be a positive whole number.'
    if (draft.annotationPolicy.annotatorUsernames.length < draft.annotationPolicy.requiredAnnotations + draft.annotationPolicy.requiredReviewers) return 'The eligible pool must fit the initial annotators and distinct additional reviewers.'
    if (!pipeline || draft.annotationPolicy.resolver !== pipeline.id) return 'The resolver catalog has not loaded from the API yet.'
    if (!configurationIsValid(draft.taskType, pipeline, draft.annotationPolicy.configuration)) return 'Fix the resolver settings marked above.'
  }
  if (step === 4) {
    if (!images.length) return 'Select a folder or files containing supported images.'
    if (draft.datasetLayout === 'split') {
      const minimum = minimumDatasetSize(draft)
      if (minimum === null) return 'The validation and test percentages leave no room for training images. Lower them in step 3.'
      if (minimum > images.length) {
        const growing = draft.validationSetUnit === 'percentage' || draft.testSetUnit === 'percentage'
          ? ' This already allows for the percentage-sized sets growing with the dataset.'
          : ''
        return `The validation, test, and first training sets need at least ${minimum} images; ${images.length} are selected. Add ${minimum - images.length} more from another folder or more files.${growing}`
      }
    }
  }
  return ''
}

function initialSizes(draft: ProjectDraft, totalMedia: number) {
  return {
    validation: resolveDraftSplitSize(totalMedia, draft.validationSetSize, draft.validationSetUnit),
    test: resolveDraftSplitSize(totalMedia, draft.testSetSize, draft.testSetUnit),
    firstTraining: resolvedFirstTrainingSize(draft),
  }
}

function strategySummary(draft: ProjectDraft, totalMedia: number) {
  const multiplier = draft.annotationPolicy.mode === 'consensus'
    ? draft.annotationPolicy.requiredAnnotations
    : 1
  const describe = (label: string, images: number) => `${label}: ${images * multiplier} work items`
  if (draft.datasetLayout === 'single_batch') return describe('All images', totalMedia)
  const { validation, test, firstTraining } = initialSizes(draft, totalMedia)
  return [
    describe('Validation', validation),
    describe('Test', test),
    describe('First training batch', firstTraining),
    describe('One acquisition batch', draft.iterationBatchSize),
  ].join(' · ')
}

function splitSummary(draft: ProjectDraft, totalMedia: number) {
  const { validation, test, firstTraining } = initialSizes(draft, totalMedia)
  return `${validation} / ${test} / ${firstTraining}`
}

function trainingPoolSize(draft: ProjectDraft, totalMedia: number) {
  const { validation, test, firstTraining } = initialSizes(draft, totalMedia)
  return Math.max(0, totalMedia - validation - test - firstTraining)
}

function validateAll(draft: ProjectDraft, images: LocalImage[], pipeline: PipelineCapability | undefined) {
  for (const candidate of [0, 1, 2, 3, 4]) {
    const error = validateStep(candidate, draft, images, pipeline)
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
