/** One image format the App can select: its MIME type, file extensions, and display name. */
export type ImageFormat = { mediaType: string; extensions: string[]; label: string }

/**
 * Every format the App knows (P7-06). The API's `supported_image_media_types`
 * decides which of them are offered; HEIC and HEIF are uploaded as they are
 * and shown through the API's lossless WebP copy.
 */
export const IMAGE_FORMATS: ImageFormat[] = [
  { mediaType: 'image/jpeg', extensions: ['jpg', 'jpeg'], label: 'JPEG' },
  { mediaType: 'image/png', extensions: ['png'], label: 'PNG' },
  { mediaType: 'image/webp', extensions: ['webp'], label: 'WebP' },
  { mediaType: 'image/heic', extensions: ['heic'], label: 'HEIC' },
  { mediaType: 'image/heif', extensions: ['heif'], label: 'HEIF' },
]

/** The known formats the API accepts; every known format until its capabilities arrive. */
export function supportedFormats(mediaTypes?: string[]) {
  if (!mediaTypes) return IMAGE_FORMATS
  const accepted = new Set(mediaTypes.map((type) => type.toLowerCase()))
  return IMAGE_FORMATS.filter((format) => accepted.has(format.mediaType))
}

/** The `accept` value of a file input: MIME types first, then extensions, for files without a type. */
export function acceptValue(formats: ImageFormat[]) {
  return [
    ...formats.map((format) => format.mediaType),
    ...formats.flatMap((format) => format.extensions.map((extension) => `.${extension}`)),
  ].join(',')
}

/** The formats as a readable list, such as `JPEG, PNG, and WebP`. */
export function formatList(formats: ImageFormat[]) {
  const labels = formats.map((format) => format.label)
  if (labels.length < 3) return labels.join(' and ')
  return `${labels.slice(0, -1).join(', ')}, and ${labels.at(-1)}`
}

export type LocalImage = {
  clientFileId: string
  file: File
  /** The path sent to the API; it depends on every folder selected so far. */
  relativePath: string
  /** The selected folder's own name, or null for individually chosen files. */
  selectionRoot: string | null
  /** The path inside the selected folder. */
  pathInSelection: string
  mediaType: string
  sizeBytes: number
  sha256?: string
}

export type RejectedLocalFile = {
  relativePath: string
  reason: 'hidden' | 'unsupported' | 'empty' | 'invalid_path' | 'duplicate_path'
}

export type ScanResult = {
  images: LocalImage[]
  rejected: RejectedLocalFile[]
  totalBytes: number
}

/** Paths relative to the selected folder, so its own name is never sent. */
export function selectedRelativePaths(files: Iterable<File>) {
  const candidates = [...files].map((file) => ({
    file,
    sourcePath: normalizeRelativePath(file.webkitRelativePath || file.name),
  }))
  const selectedRoot = commonSelectedRoot(candidates.map((item) => item.sourcePath))
  return candidates.map(({ file, sourcePath }) => ({
    file,
    sourcePath,
    selectedRoot,
    relativePath: selectedRoot ? sourcePath.split('/').slice(1).join('/') : sourcePath,
  }))
}

export function scanImageFiles(files: Iterable<File>, formats: ImageFormat[] = IMAGE_FORMATS): ScanResult {
  const images: LocalImage[] = []
  const rejected: RejectedLocalFile[] = []
  let totalBytes = 0

  for (const { file, sourcePath, selectedRoot, relativePath } of selectedRelativePaths(files)) {
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
    const mediaType = imageMediaType(file, formats)
    if (!mediaType) {
      rejected.push({ relativePath, reason: 'unsupported' })
      continue
    }

    images.push({
      clientFileId: crypto.randomUUID(),
      file,
      relativePath,
      selectionRoot: selectedRoot,
      pathInSelection: relativePath,
      mediaType,
      sizeBytes: file.size,
    })
    totalBytes += file.size
  }

  return { images, rejected, totalBytes }
}

/**
 * Adds another folder or file selection to the images already chosen.
 *
 * One folder is sent relative to its own root, so its name never leaves the
 * browser. Once images come from two or more folders, every folder image keeps
 * its folder's name as the first path segment, as if their common parent had
 * been selected; otherwise `north/0001.jpg` and `south/0001.jpg` would collide.
 * A path that is still taken is skipped and reported, because the API refuses
 * two images at one path.
 */
export function mergeSelections(current: LocalImage[], added: LocalImage[]) {
  const roots = new Set([...current, ...added].map((image) => image.selectionRoot).filter(Boolean))
  const taken = new Set<string>()
  const images: LocalImage[] = []
  const rejected: RejectedLocalFile[] = []
  for (const image of [...current, ...added]) {
    const relativePath = roots.size > 1 && image.selectionRoot
      ? `${image.selectionRoot}/${image.pathInSelection}`
      : image.pathInSelection
    if (taken.has(relativePath)) {
      rejected.push({ relativePath, reason: 'duplicate_path' })
    } else {
      taken.add(relativePath)
      images.push({ ...image, relativePath })
    }
  }
  return { images, rejected }
}

export async function hashImages(
  images: LocalImage[],
  onProgress?: (completed: number, total: number) => void,
): Promise<LocalImage[]> {
  const hashed: LocalImage[] = []
  for (const [index, image] of images.entries()) {
    hashed.push({ ...image, sha256: await sha256Hex(image.file) })
    onProgress?.(index + 1, images.length)
  }
  return hashed
}

export async function sha256Hex(blob: Blob) {
  return toHex(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))
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

/** The file's media type when it is a selectable format: its own type, or the one of its extension. */
export function imageMediaType(file: File, formats: ImageFormat[]) {
  const type = file.type.toLowerCase()
  if (formats.some((format) => format.mediaType === type)) return type
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  return formats.find((format) => format.extensions.includes(extension))?.mediaType ?? null
}

function toHex(buffer: ArrayBuffer) {
  return [...new Uint8Array(buffer)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}
