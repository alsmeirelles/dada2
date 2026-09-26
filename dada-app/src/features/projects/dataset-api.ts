import { apiRequest } from '../../api/client'
import { selectedRelativePaths, sha256Hex } from './ingest'
import { loadSetup, setupKey } from './setup-recovery'
import type {
  AnnotationImport,
  DatasetLayoutSummary,
  ImportFormat,
  Project,
  TaskType,
} from './types'

export type LabelFile = {
  clientFileId: string
  file: File
  relativePath: string
  sizeBytes: number
  sha256: string
}

/** YOLO sidecars label detection projects; COCO documents label segmentation. */
export const IMPORT_FORMATS: Partial<Record<TaskType, ImportFormat>> = {
  detection: 'yolo_detection',
  segmentation: 'coco_segmentation',
}

const LABEL_EXTENSIONS: Record<ImportFormat, string> = {
  yolo_detection: '.txt',
  coco_segmentation: '.json',
}

/** Reuses the setup's stable key when this project is the one being set up. */
function operationKey(projectId: string, operation: 'prepare' | 'activate') {
  const snapshot = loadSetup()
  return setupKey(snapshot?.projectId === projectId ? snapshot : null, operation)
}

export function getDatasetLayout(projectId: string, token: string) {
  return apiRequest<DatasetLayoutSummary>(
    `/api/v1/projects/${projectId}/dataset-layout`,
    { token },
  )
}

export function prepareDataset(projectId: string, token: string) {
  return apiRequest<DatasetLayoutSummary>(
    `/api/v1/projects/${projectId}/dataset-layout/prepare`,
    {
      method: 'POST',
      token,
      headers: { 'Idempotency-Key': operationKey(projectId, 'prepare') },
      body: {},
    },
  )
}

export function resetDataset(projectId: string, token: string) {
  return apiRequest<void>(`/api/v1/projects/${projectId}/dataset-layout`, {
    method: 'DELETE',
    token,
  })
}

export function activateProject(projectId: string, token: string) {
  return apiRequest<Project>(`/api/v1/projects/${projectId}/activate`, {
    method: 'POST',
    token,
    headers: { 'Idempotency-Key': operationKey(projectId, 'activate') },
    body: {},
  })
}

/** Keeps the files of the import's format, with paths relative to the selection. */
export async function readLabelFiles(
  files: Iterable<File>,
  format: ImportFormat,
): Promise<LabelFile[]> {
  const extension = LABEL_EXTENSIONS[format]
  const labels: LabelFile[] = []
  for (const { file, relativePath } of selectedRelativePaths(files)) {
    if (!relativePath.toLowerCase().endsWith(extension)) continue
    labels.push({
      clientFileId: crypto.randomUUID(),
      file,
      relativePath,
      sizeBytes: file.size,
      sha256: await sha256Hex(file),
    })
  }
  return labels
}

export function getImport(importId: string, token: string) {
  return apiRequest<AnnotationImport>(`/api/v1/annotation-imports/${importId}`, {
    token,
  })
}

/** Creates the import, sends every file whole, and returns the review report. */
export async function importLabels(
  projectId: string,
  format: ImportFormat,
  labels: LabelFile[],
  token: string,
  onProgress?: (sent: number, total: number) => void,
): Promise<AnnotationImport> {
  const created = await apiRequest<AnnotationImport>(
    `/api/v1/projects/${projectId}/annotation-imports`,
    {
      method: 'POST',
      token,
      body: {
        format,
        files: labels.map((label) => ({
          client_file_id: label.clientFileId,
          relative_path: label.relativePath,
          size_bytes: label.sizeBytes,
          sha256: label.sha256,
        })),
      },
    },
  )
  for (const [index, label] of labels.entries()) {
    await apiRequest(
      `/api/v1/annotation-imports/${created.id}/files/${encodeURIComponent(label.clientFileId)}`,
      {
        method: 'POST',
        token,
        rawBody: label.file,
        headers: { 'Content-Type': 'application/octet-stream' },
      },
    )
    onProgress?.(index + 1, labels.length)
  }
  return apiRequest<AnnotationImport>(
    `/api/v1/annotation-imports/${created.id}/validate`,
    { method: 'POST', token, body: {} },
  )
}

export function acceptImport(importId: string, token: string) {
  return apiRequest<AnnotationImport>(
    `/api/v1/annotation-imports/${importId}/accept`,
    { method: 'POST', token, body: {} },
  )
}

export function discardImport(importId: string, token: string) {
  return apiRequest<void>(`/api/v1/annotation-imports/${importId}`, {
    method: 'DELETE',
    token,
  })
}
