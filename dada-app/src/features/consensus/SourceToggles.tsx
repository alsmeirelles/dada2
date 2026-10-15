import { EyeOff } from 'lucide-react'
import { useId } from 'react'

import { Button } from '../../components/ui/Button'
import type { EvidenceLayout, EvidenceSource } from './consensus-view-model'

type SourceTogglesProps = {
  sources: EvidenceSource[]
  visible: ReadonlySet<string>
  onToggle: (id: string) => void
  onHideAll: () => void
  regions?: { checked: boolean; onChange: (checked: boolean) => void }
  alpha?: { value: number; onChange: (value: number) => void }
  layout?: { value: EvidenceLayout; onChange: (value: EvidenceLayout) => void }
}

/** Keyboard-reachable visibility, transparency, and layout controls for evidence overlays. */
export function SourceToggles({ sources, visible, onToggle, onHideAll, regions, alpha, layout }: SourceTogglesProps) {
  const alphaId = useId()
  return <div className="source-toggles">
    <fieldset>
      <legend>Evidence sources</legend>
      {sources.map((source) => <label key={source.id} className="source-toggle">
        <input type="checkbox" checked={visible.has(source.id)} onChange={() => onToggle(source.id)} />
        <svg className="source-swatch" viewBox="0 0 36 10" aria-hidden="true"><line x1="1" y1="5" x2="35" y2="5" stroke={source.color} strokeWidth="3" strokeDasharray={source.dash || undefined} /></svg>
        <span>{source.label} <small>{source.detail} · {source.pattern}</small></span>
      </label>)}
      {regions && <label className="source-toggle">
        <input type="checkbox" checked={regions.checked} onChange={(event) => regions.onChange(event.target.checked)} />
        <svg className="source-swatch" viewBox="0 0 36 10" aria-hidden="true"><rect x="1" y="1" width="34" height="8" className="evidence-region evidence-region--review" /></svg>
        <span>Candidate regions <small>Labelled passed or needs review</small></span>
      </label>}
      <Button type="button" variant="secondary" onClick={onHideAll}><EyeOff size={16} /> Hide all sources</Button>
    </fieldset>
    {alpha && <div className="source-alpha">
      <label htmlFor={alphaId}>Mask opacity</label>
      <output htmlFor={alphaId}>{Math.round(alpha.value * 100)}%</output>
      <input id={alphaId} type="range" min={0} max={1} step={0.05} value={alpha.value} onChange={(event) => alpha.onChange(Number(event.target.value))} />
    </div>}
    {layout && <fieldset className="source-layout">
      <legend>Layout</legend>
      <label><input type="radio" name="evidence-layout" checked={layout.value === 'overlay'} onChange={() => layout.onChange('overlay')} /> Overlay</label>
      <label><input type="radio" name="evidence-layout" checked={layout.value === 'side-by-side'} onChange={() => layout.onChange('side-by-side')} /> Side by side</label>
    </fieldset>}
  </div>
}
