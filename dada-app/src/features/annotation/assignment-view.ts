import type { BatchPurpose } from '../projects/types'
import type { RecoverySnapshot } from './recovery'
import type {
  AnnotationDocument,
  AssignmentDetail,
  AssignmentQueueItem,
  AssignmentStatus,
  QueueState,
} from './types'

export const AUTOSAVE_MS = 10 * 60 * 1_000

export const STATUS_LABELS: Record<AssignmentStatus, string> = {
  pending: 'Available',
  in_progress: 'In progress',
  submitted: 'Submitted',
  reassigned: 'Reassigned',
  cancelled: 'Cancelled',
}

export function isEditable(status: AssignmentStatus) {
  return status === 'pending' || status === 'in_progress'
}

export function filterAssignments(
  items: AssignmentQueueItem[],
  purpose: BatchPurpose | 'all',
  state: QueueState | 'all',
) {
  return items.filter((item) =>
    (purpose === 'all' || item.batch_purpose === purpose) && (state === 'all' || item.status === state))
}

export function neighbor(items: AssignmentQueueItem[], currentId: string | null, direction: -1 | 1) {
  const index = items.findIndex((item) => item.id === currentId)
  if (index === -1) return items[0]
  return items[Math.min(items.length - 1, Math.max(0, index + direction))]
}

export function toDocument(assignment: AssignmentDetail): AnnotationDocument {
  return {
    media_id: assignment.media.id,
    task_type: assignment.task_type,
    version: assignment.version,
    objects: assignment.objects,
  }
}

export type OpenedWork = {
  document: AnnotationDocument
  dirty: boolean
  conflict: RecoverySnapshot | null
  notice: string | null
}

/**
 * Decide what the annotator sees when an assignment opens.
 *
 * Local work built on the current server version is newer than the server
 * draft and is restored. Local work built on an older version means the
 * server changed meanwhile, so the annotator chooses which one to keep.
 */
export function openWork(assignment: AssignmentDetail, local: RecoverySnapshot | null): OpenedWork {
  const server = toDocument(assignment)
  const savedAt = local ? new Date(local.savedAt).toLocaleTimeString() : ''
  if (assignment.status === 'reassigned' || assignment.status === 'cancelled') {
    const verb = assignment.status === 'reassigned' ? 'reassigned this image to another annotator' : 'cancelled this image'
    const kept = local ? ' Your unsaved work stays in this browser.' : ''
    return { document: server, dirty: false, conflict: null, notice: `A manager ${verb}.${kept}` }
  }
  if (assignment.status === 'submitted') {
    return { document: server, dirty: false, conflict: null, notice: 'Submission received. This image is read-only.' }
  }
  if (local && local.baseVersion === assignment.version) {
    return {
      document: { ...local.document, version: assignment.version },
      dirty: true,
      conflict: null,
      notice: `Recovered unsaved work from this browser, saved at ${savedAt}.`,
    }
  }
  if (local) {
    return {
      document: server,
      dirty: false,
      conflict: local,
      notice: `This image changed on the server after your unsaved work from ${savedAt}. Choose which version to keep.`,
    }
  }
  const seeded = assignment.seeded_from_import && assignment.status === 'pending'
    ? 'This image starts from imported labels. What you save and submit is your own work.'
    : null
  return { document: server, dirty: false, conflict: null, notice: seeded }
}

export function validateDocument(document: AnnotationDocument) {
  if (document.task_type === 'classification' && !document.objects.length) return 'Choose at least one class before submitting.'
  if (document.objects.some((item) => !item.class_id)) return 'Every annotation needs a class.'
  if (document.task_type === 'detection' && document.objects.some((item) => item.geometry?.type !== 'rectangle')) return 'Detection annotations must use bounding boxes.'
  if (document.task_type === 'segmentation' && document.objects.some((item) => item.geometry?.type !== 'polygon')) return 'Segmentation annotations must use polygons or masks.'
  if (document.task_type === 'classification' && document.objects.some((item) => item.geometry !== null)) return 'Classification labels cannot contain geometry.'
  return ''
}
