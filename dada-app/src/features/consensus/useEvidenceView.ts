import { useMemo, useState } from 'react'

import type { EvidenceSource } from './consensus-view-model'

export const DEFAULT_MASK_ALPHA = 0.35

/** Which sources are shown, the region toggle, and the mask opacity; a source the user never touched keeps its default. */
export function useEvidenceView(sources: EvidenceSource[]) {
  const [overrides, setOverrides] = useState<Record<string, boolean>>({})
  const [showRegions, setShowRegions] = useState(true)
  const [alpha, setAlpha] = useState(DEFAULT_MASK_ALPHA)
  const visible = useMemo(
    () => new Set(sources.filter((source) => overrides[source.id] ?? source.defaultVisible).map((source) => source.id)),
    [overrides, sources],
  )
  return {
    visible,
    shown: sources.filter((source) => visible.has(source.id)),
    toggle: (id: string) => setOverrides((current) => ({ ...current, [id]: !visible.has(id) })),
    hideAll: () => {
      setOverrides(Object.fromEntries(sources.map((source) => [source.id, false])))
      setShowRegions(false)
    },
    showRegions,
    setShowRegions,
    alpha,
    setAlpha,
  }
}
