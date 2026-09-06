const KEY = 'dada.project-setup'
const CREATE_KEY = 'dada.project-setup-create-key'

export const SETUP_STAGES = [
  'created',
  'classes',
  'members',
  'policy',
  'uploaded',
  'activated',
] as const

export type SetupStage = (typeof SETUP_STAGES)[number]

export type SetupSnapshot = {
  projectId: string
  stage: SetupStage
  /** Server session to query after an interrupted browser upload. */
  uploadId?: string
  /** Stable operation keys make a retry safe when its response was lost. */
  keys?: Partial<Record<'project' | 'upload' | 'complete' | 'activate', string>>
}

export function stageIndex(stage: SetupStage) {
  return SETUP_STAGES.indexOf(stage)
}

export function saveSetup(snapshot: SetupSnapshot) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(snapshot))
  } catch {
    // Storage can be unavailable; the API remains authoritative and the user
    // is told the draft exists.
  }
}

export function loadSetup(): SetupSnapshot | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<SetupSnapshot>
    if (
      typeof parsed.projectId !== 'string' ||
      !parsed.projectId ||
      !SETUP_STAGES.includes(parsed.stage as SetupStage)
    ) {
      sessionStorage.removeItem(KEY)
      return null
    }
    const uploadId = typeof parsed.uploadId === 'string' && parsed.uploadId
      ? parsed.uploadId : undefined
    const keys = isKeys(parsed.keys) ? parsed.keys : undefined
    return {
      projectId: parsed.projectId,
      stage: parsed.stage as SetupStage,
      ...(uploadId ? { uploadId } : {}),
      ...(keys ? { keys } : {}),
    }
  } catch {
    clearSetup()
    return null
  }
}

export function setupKey(snapshot: SetupSnapshot | null, operation: 'project' | 'upload' | 'complete' | 'activate') {
  const existing = snapshot?.keys?.[operation]
  if (existing) return existing
  const key = crypto.randomUUID()
  if (snapshot) saveSetup({ ...snapshot, keys: { ...snapshot.keys, [operation]: key } })
  return key
}

function isKeys(value: unknown): value is SetupSnapshot['keys'] {
  if (!value || typeof value !== 'object') return false
  return Object.values(value).every((key) => typeof key === 'string' && key.length > 0)
}

export function clearSetup() {
  try {
    sessionStorage.removeItem(KEY)
    sessionStorage.removeItem(CREATE_KEY)
  } catch {
    // Nothing to do; a stale snapshot only affects this browser tab.
  }
}

/** Kept separately because a timed-out project creation has no server ID yet. */
export function pendingProjectCreateKey() {
  try {
    const key = sessionStorage.getItem(CREATE_KEY)
    if (key) return key
    const created = crypto.randomUUID()
    sessionStorage.setItem(CREATE_KEY, created)
    return created
  } catch {
    return crypto.randomUUID()
  }
}

export function confirmProjectCreated() {
  try { sessionStorage.removeItem(CREATE_KEY) } catch { /* storage is optional */ }
}
