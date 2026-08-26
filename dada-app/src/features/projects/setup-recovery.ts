const KEY = 'dada.project-setup'

export const SETUP_STAGES = [
  'created',
  'classes',
  'members',
  'policy',
  'uploaded',
  'activated',
] as const

export type SetupStage = (typeof SETUP_STAGES)[number]

export type SetupSnapshot = { projectId: string; stage: SetupStage }

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
    return { projectId: parsed.projectId, stage: parsed.stage as SetupStage }
  } catch {
    clearSetup()
    return null
  }
}

export function clearSetup() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // Nothing to do; a stale snapshot only affects this browser tab.
  }
}
