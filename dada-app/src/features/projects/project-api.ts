import { apiRequest } from '../../api/client'
import { config } from '../../config/env'
import type { LocalImage } from './ingest'
import type { AnnotationPolicy, Page, Project, ProjectDraft } from './types'

type UploadDisposition = 'upload_required' | 'already_present' | 'rejected'
type UploadItem = {
  client_file_id: string
  disposition: UploadDisposition
  reason?: string
}
type UploadSession = {
  id: string
  status: 'pending' | 'uploading' | 'processing' | 'completed' | 'failed'
  items: UploadItem[]
  error?: { message: string }
}

type ProjectMember = { user_id: string; username: string; role: string }

export async function listProjects(token: string): Promise<Page<Project>> {
  return apiRequest('/api/v1/projects', { token })
}

export async function createProjectWithDataset(
  draft: ProjectDraft,
  images: LocalImage[],
  token: string,
  onProgress: (progress: number, message: string) => void,
): Promise<Project> {
  onProgress(2, 'Creating project…')
  const project = await apiRequest<Project>('/api/v1/projects', {
    method: 'POST',
    token,
    headers: idempotencyHeaders(),
    body: {
      name: draft.name.trim(),
      description: draft.description.trim() || null,
      task_type: draft.taskType,
      initial_training_size: draft.initialTrainingSize,
      test_set_size: draft.testSetSize,
      iteration_batch_size: draft.iterationBatchSize,
    },
  })

  onProgress(8, 'Saving classes…')
  for (const [index, item] of draft.classes.entries()) {
    await apiRequest(`/api/v1/projects/${project.id}/classes`, {
      method: 'POST', token,
      body: { name: item.name.trim(), color: item.color, display_order: index },
    })
  }

  onProgress(12, 'Inviting collaborators…')
  const members = await Promise.all(draft.collaborators.map(async (username) => {
    return apiRequest<ProjectMember>(`/api/v1/projects/${project.id}/members`, {
      method: 'POST', token,
      body: { username, role: 'annotator' },
    })
  }))

  onProgress(14, 'Saving annotation strategy…')
  const memberIds = new Map(members.map((member) => [member.username, member.user_id]))
  const policy = draft.annotationPolicy.mode === 'single'
    ? { mode: 'single', annotator_ids: [] }
    : {
        mode: 'consensus',
        annotator_ids: draft.annotationPolicy.annotatorUsernames.map((username) => {
          const userId = memberIds.get(username)
          if (!userId) throw new Error(`The API did not return a member ID for ${username}.`)
          return userId
        }),
        resolver: draft.annotationPolicy.resolver,
        parameters: {},
        review_thresholds: { agreement: draft.annotationPolicy.reviewThreshold },
      }
  await apiRequest<AnnotationPolicy>(`/api/v1/projects/${project.id}/annotation-policy`, {
    method: 'PUT', token, headers: idempotencyHeaders(), body: policy,
  })

  onProgress(15, 'Preparing upload…')
  const upload = await apiRequest<UploadSession>(
    `/api/v1/projects/${project.id}/uploads`,
    {
      method: 'POST', token,
      headers: idempotencyHeaders(),
      body: {
        files: images.map((image) => ({
          client_file_id: image.clientFileId,
          relative_path: image.relativePath,
          file_name: image.file.name,
          media_type: image.mediaType,
          size_bytes: image.sizeBytes,
          sha256: image.sha256,
        })),
      },
    },
  )

  const required = upload.items.filter((item) => item.disposition === 'upload_required')
  const rejected = upload.items.filter((item) => item.disposition === 'rejected')
  if (rejected.length) throw new Error(`${rejected.length} image(s) were rejected by the API.`)

  for (const [fileIndex, item] of required.entries()) {
    const image = images.find((candidate) => candidate.clientFileId === item.client_file_id)
    if (!image) throw new Error('The API requested an unknown local image.')
    await uploadFile(upload.id, image, token, (fraction) => {
      const overall = (fileIndex + fraction) / Math.max(required.length, 1)
      onProgress(15 + Math.round(overall * 78), `Uploading ${image.relativePath}…`)
    })
  }

  onProgress(94, 'Verifying dataset…')
  await apiRequest(`/api/v1/uploads/${upload.id}/complete`, {
    method: 'POST', token, headers: idempotencyHeaders(), body: {},
  })
  await waitForUploadProcessing(upload.id, token, (message) => onProgress(96, message))

  onProgress(98, 'Activating project…')
  const activated = await apiRequest<Project>(`/api/v1/projects/${project.id}/activate`, {
    method: 'POST', token, headers: idempotencyHeaders(), body: {},
  })
  onProgress(100, 'Project ready')
  return activated
}

async function waitForUploadProcessing(
  uploadId: string,
  token: string,
  onProgress: (message: string) => void,
) {
  const deadline = Date.now() + 10 * 60_000
  while (Date.now() < deadline) {
    const upload = await apiRequest<UploadSession>(`/api/v1/uploads/${uploadId}`, { token })
    if (upload.status === 'completed') return
    if (upload.status === 'failed') {
      throw new Error(upload.error?.message ?? 'The API could not process the dataset.')
    }
    onProgress('Processing images on the API…')
    await delay(1_500)
  }
  throw new Error('Dataset processing is still running. The project remains available as a draft.')
}

async function uploadFile(
  uploadId: string,
  image: LocalImage,
  token: string,
  onProgress: (fraction: number) => void,
) {
  const chunkSize = config.uploadChunkBytes
  let offset = 0
  while (offset < image.file.size) {
    const chunk = image.file.slice(offset, Math.min(offset + chunkSize, image.file.size))
    const end = offset + chunk.size
    const checksum = await sha256(chunk)
    await apiRequest(
      `/api/v1/uploads/${uploadId}/files/${encodeURIComponent(image.clientFileId)}`,
      {
        method: 'PUT', token, rawBody: chunk,
        headers: {
          'Content-Type': 'application/octet-stream',
          'Content-Range': `bytes ${offset}-${end - 1}/${image.file.size}`,
          'Upload-Offset': String(offset),
          'X-Chunk-SHA256': checksum,
        },
      },
    )
    offset = end
    onProgress(offset / image.file.size)
  }
}

async function sha256(blob: Blob) {
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

function idempotencyHeaders() {
  return { 'Idempotency-Key': crypto.randomUUID() }
}

function delay(milliseconds: number) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}
