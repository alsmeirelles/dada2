import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FileUp, RotateCcw, Trash2 } from 'lucide-react'
import { useRef, useState, type ChangeEvent } from 'react'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import {
  IMPORT_FORMATS,
  acceptImport,
  activateProject,
  discardImport,
  getDatasetLayout,
  getImport,
  importLabels,
  prepareDataset,
  readLabelFiles,
  resetDataset,
} from './dataset-api'
import { clearSetup } from './setup-recovery'
import type { AnnotationImport, Project } from './types'

const FORMAT_HELP = {
  yolo_detection: 'Choose the folder of YOLO .txt label files. Each label matches the image with the same relative path, e.g. camera-a/0001.txt labels camera-a/0001.jpg.',
  coco_segmentation: 'Choose one or more COCO JSON files. images[].file_name must equal the image path relative to the uploaded folder.',
} as const

/**
 * The step between upload and activation: shows the prepared layout, lets an
 * owner or manager review an optional label import, and activates the project.
 */
export function DatasetPreparationPanel({ project, onActivated }: {
  project: Project
  onActivated: () => void
}) {
  const token = useAuth().token!
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [progress, setProgress] = useState<string | null>(null)
  const format = IMPORT_FORMATS[project.task_type]
  const layout = useQuery({
    queryKey: ['dataset-layout', project.id],
    queryFn: () => getDatasetLayout(project.id, token),
  })
  const importId = layout.data?.annotation_import_id ?? null
  const labelImport = useQuery({
    queryKey: ['annotation-import', importId],
    queryFn: () => getImport(importId!, token),
    enabled: Boolean(importId),
  })
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['project', project.id] }),
    queryClient.invalidateQueries({ queryKey: ['dataset-layout', project.id] }),
    queryClient.invalidateQueries({ queryKey: ['annotation-import'] }),
  ])
  const prepare = useMutation({ mutationFn: () => prepareDataset(project.id, token), onSuccess: refresh })
  const reset = useMutation({ mutationFn: () => resetDataset(project.id, token), onSuccess: refresh })
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const labels = await readLabelFiles(files, format!)
      if (!labels.length) throw new Error(`No ${format === 'yolo_detection' ? '.txt' : '.json'} label files were selected.`)
      return importLabels(project.id, format!, labels, token, (sent, total) => setProgress(`Uploading label files… ${sent}/${total}`))
    },
    onSettled: () => { setProgress(null); return refresh() },
  })
  const accept = useMutation({ mutationFn: (id: string) => acceptImport(id, token), onSuccess: refresh })
  const discard = useMutation({ mutationFn: (id: string) => discardImport(id, token), onSuccess: refresh })
  const activate = useMutation({
    mutationFn: () => activateProject(project.id, token),
    onSuccess: () => { clearSetup(); onActivated() },
  })
  const failure = [prepare, reset, upload, accept, discard, activate].find((mutation) => mutation.isError)?.error
  const busy = [prepare, reset, upload, accept, discard, activate].some((mutation) => mutation.isPending)
  const current = importId ? labelImport.data : undefined
  const importBlocksActivation = Boolean(importId) && current?.status !== 'accepted'

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    // Copied first: resetting the input empties the live FileList it returned.
    const files = [...(event.currentTarget.files ?? [])]
    event.currentTarget.value = ''
    if (files.length) upload.mutate(files)
  }

  if (layout.isLoading) return <div className="panel status-panel">Loading dataset preparation…</div>
  if (layout.isError) return <div className="panel error-panel" role="alert">The dataset preparation could not be loaded.</div>

  const summary = layout.data!
  if (!summary.prepared_at) {
    return <section className="wizard-section" aria-labelledby="prepare-title">
      <div><h2 id="prepare-title">Prepare dataset</h2><p className="muted">{project.dataset_layout === 'single_batch' ? 'Every uploaded image will be annotated once in one static batch.' : 'Preparation fixes the validation and test sets and selects the first training batch from the uploaded images.'}</p></div>
      {failure && <p className="form-error" role="alert">{preparationError(failure)}</p>}
      <Button onClick={() => prepare.mutate()} disabled={busy}>{prepare.isPending ? 'Preparing…' : 'Prepare dataset'}</Button>
    </section>
  }

  return <section className="wizard-section" aria-labelledby="prepared-title">
    <div><h2 id="prepared-title">Prepare dataset and import labels</h2><p className="muted">Review the prepared annotation work, optionally import existing labels, then activate the project.</p></div>
    <div className="review-grid">
      {summary.dataset_layout === 'split' ? <>
        <ReviewItem label="Validation" value={`${summary.validation_size} images`} detail="every image is annotated" />
        <ReviewItem label="Test" value={`${summary.test_size} images`} detail="every image is annotated" />
        <ReviewItem label="First training batch" value={`${summary.first_training_batch_size ?? 0} images`} detail={`${summary.train_size} images in the training split`} />
        <ReviewItem label="Unlabeled training pool" value={`${summary.training_pool_size} images`} detail="eligible for later acquisition batches" />
      </> : <ReviewItem label="Static batch" value="All images" detail="no training or acquisition loop" />}
    </div>
    {summary.dataset_layout === 'split' && <p className="notice">The first acquisition batch can only start after every validation, test, and first-training image has an accepted resolution.</p>}

    {format ? <div className="import-panel">
      <h3>Import existing labels <span className="optional">Optional</span></h3>
      <p className="muted">{FORMAT_HELP[format]} Imported labels prefill each annotator's own work; they are never counted as a submission or a resolution.</p>
      <input ref={(node) => { fileInput.current = node; if (format === 'yolo_detection') node?.setAttribute('webkitdirectory', '') }} className="sr-only" type="file" multiple accept={format === 'yolo_detection' ? '.txt' : '.json,application/json'} onChange={chooseFiles} aria-label="Label files" />
      {!importId && <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy}><FileUp size={16} />{format === 'yolo_detection' ? 'Choose label folder' : 'Choose COCO files'}</Button>}
      {progress && <p className="muted" role="status">{progress}</p>}
      {current && <ImportReview labelImport={current} busy={busy} onAccept={() => accept.mutate(current.id)} onDiscard={() => discard.mutate(current.id)} />}
      <p className="notice">Changing classes or media, or resetting the preparation, discards imported labels.</p>
    </div> : <p className="muted">Label import is available for detection and segmentation projects.</p>}

    {failure && <p className="form-error" role="alert">{preparationError(failure)}</p>}
    <div className="batch-actions">
      <Button variant="ghost" disabled={busy} onClick={() => { if (window.confirm('Reset the prepared dataset? The split, the initial batches, and any imported labels are discarded.')) reset.mutate() }}><RotateCcw size={16} />Reset preparation</Button>
      <Button onClick={() => activate.mutate()} disabled={busy || importBlocksActivation}><Check size={16} />{activate.isPending ? 'Activating…' : 'Activate project'}</Button>
    </div>
    {importBlocksActivation && <p className="validation-message">Accept or discard the label import before activating.</p>}
  </section>
}

function ImportReview({ labelImport, busy, onAccept, onDiscard }: {
  labelImport: AnnotationImport
  busy: boolean
  onAccept: () => void
  onDiscard: () => void
}) {
  const report = labelImport.report
  const paths = new Map(labelImport.files.map((file) => [file.client_file_id, file.relative_path]))
  return <div className="import-review" aria-label="Label import review">
    <p><strong>{importStatusLabel(labelImport.status)}</strong> · {labelImport.files.length} file(s) · {labelImport.parser_version}</p>
    {report && <p className="muted">{report.labelled_images} labelled images · {report.objects} objects · {report.unlabelled_images} images without labels</p>}
    {report && report.errors.length > 0 && <ul className="import-errors">
      {report.errors.map((error, index) => <li key={index}><code>{error.code}</code> {paths.get(error.client_file_id) ?? error.client_file_id}: {error.detail}</li>)}
    </ul>}
    {labelImport.status !== 'accepted' && <div className="batch-actions">
      <Button variant="ghost" onClick={onDiscard} disabled={busy}><Trash2 size={16} />Discard import</Button>
      {labelImport.status === 'validated' && <Button variant="secondary" onClick={onAccept} disabled={busy}><Check size={16} />Accept labels</Button>}
    </div>}
  </div>
}

function ReviewItem({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="review-item"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
}

function importStatusLabel(status: AnnotationImport['status']) {
  if (status === 'accepted') return 'Labels accepted'
  if (status === 'validated') return 'Labels validated — ready to accept'
  if (status === 'rejected') return 'Labels rejected — discard and import corrected files'
  return 'Upload incomplete'
}

function preparationError(error: Error) {
  if (error instanceof ApiError && error.code === 'preparation_incomplete') return 'The dataset cannot be prepared yet. Check that classes and enough images for the validation, test, and first training sets exist.'
  if (error instanceof ApiError && error.code === 'activation_incomplete') return 'Activation is blocked. Accept or discard the label import and make sure the dataset is prepared.'
  return error.message || 'The dataset could not be updated.'
}
