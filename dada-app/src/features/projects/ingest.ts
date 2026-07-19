export const SUPPORTED_IMAGE_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
])

const SUPPORTED_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp'])

export type LocalImage = {
  clientFileId: string
  file: File
  relativePath: string
  mediaType: string
  sizeBytes: number
  sha256?: string
}

export type RejectedLocalFile = {
  relativePath: string
  reason: 'hidden' | 'unsupported' | 'empty' | 'invalid_path'
}

export type ScanResult = {
  images: LocalImage[]
  rejected: RejectedLocalFile[]
  totalBytes: number
}

export function scanImageFiles(files: Iterable<File>): ScanResult {
  const images: LocalImage[] = []
  const rejected: RejectedLocalFile[] = []
  let totalBytes = 0
  const candidates = [...files].map((file) => ({
    file,
    sourcePath: normalizeRelativePath(file.webkitRelativePath || file.name),
  }))
  const selectedRoot = commonSelectedRoot(candidates.map((item) => item.sourcePath))

  for (const { file, sourcePath } of candidates) {
    const relativePath = selectedRoot
      ? sourcePath.split('/').slice(1).join('/')
      : sourcePath
    const segments = relativePath.split('/')

    if (!relativePath || segments.includes('..')) {
      rejected.push({ relativePath: relativePath || sourcePath, reason: 'invalid_path' })
      continue
    }
    if (segments.some((part) => part.startsWith('.'))) {
      rejected.push({ relativePath, reason: 'hidden' })
      continue
    }
    if (file.size === 0) {
      rejected.push({ relativePath, reason: 'empty' })
      continue
    }
    if (!isSupportedImage(file)) {
      rejected.push({ relativePath, reason: 'unsupported' })
      continue
    }

    images.push({
      clientFileId: crypto.randomUUID(),
      file,
      relativePath,
      mediaType: inferMediaType(file),
      sizeBytes: file.size,
    })
    totalBytes += file.size
  }

  return { images, rejected, totalBytes }
}

export async function hashImages(
  images: LocalImage[],
  onProgress?: (completed: number, total: number) => void,
): Promise<LocalImage[]> {
  const hashed: LocalImage[] = []
  for (const [index, image] of images.entries()) {
    const digest = await crypto.subtle.digest('SHA-256', await image.file.arrayBuffer())
    hashed.push({ ...image, sha256: toHex(digest) })
    onProgress?.(index + 1, images.length)
  }
  return hashed
}

export function findDuplicateGroups(images: LocalImage[]): LocalImage[][] {
  const byDigest = new Map<string, LocalImage[]>()
  for (const image of images) {
    if (!image.sha256) continue
    const key = `${image.sha256}:${image.sizeBytes}`
    byDigest.set(key, [...(byDigest.get(key) ?? []), image])
  }
  return [...byDigest.values()].filter((group) => group.length > 1)
}

function normalizeRelativePath(path: string) {
  return path.replaceAll('\\', '/').replace(/^\/+/, '')
}

function commonSelectedRoot(paths: string[]) {
  if (!paths.length || paths.some((path) => !path.includes('/'))) return null
  const root = paths[0]?.split('/')[0]
  return root && paths.every((path) => path.split('/')[0] === root) ? root : null
}

function isSupportedImage(file: File) {
  if (SUPPORTED_IMAGE_TYPES.has(file.type.toLowerCase())) return true
  const extension = file.name.split('.').pop()?.toLowerCase()
  return extension ? SUPPORTED_EXTENSIONS.has(extension) : false
}

function inferMediaType(file: File) {
  if (SUPPORTED_IMAGE_TYPES.has(file.type.toLowerCase())) return file.type.toLowerCase()
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (extension === 'png') return 'image/png'
  if (extension === 'webp') return 'image/webp'
  return 'image/jpeg'
}

function toHex(buffer: ArrayBuffer) {
  return [...new Uint8Array(buffer)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}
