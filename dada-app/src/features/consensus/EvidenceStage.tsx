import { Maximize, Minus, Plus } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent } from 'react'

import { Button } from '../../components/ui/Button'
import type { AssignmentMedia } from '../annotation/types'
import { clampZoom, zoomAroundPoint } from '../annotation/viewport'
import type { ProjectClassInput } from '../projects/types'
import type { CandidateRegion, EvidenceSource } from './consensus-view-model'
import { EvidenceShapes } from './EvidenceShapes'
import '../annotation/annotation.css'

type EvidenceStageProps = {
  label: string
  media: AssignmentMedia
  sources: EvidenceSource[]
  regions: CandidateRegion[]
  classes: ProjectClassInput[]
  alpha: number
}

/** A read-only, zoomable view of one image with evidence drawn over it; it holds no editing state. */
export function EvidenceStage({ label, media, sources, regions, classes, alpha }: EvidenceStageProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [drag, setDrag] = useState<{ pointerId: number; x: number; y: number } | null>(null)

  const fit = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const padding = 32
    const nextZoom = clampZoom(Math.min(
      (container.clientWidth - padding) / media.width,
      (container.clientHeight - padding) / media.height,
    ))
    setZoom(nextZoom)
    setOffset({
      x: (container.clientWidth - media.width * nextZoom) / 2,
      y: (container.clientHeight - media.height * nextZoom) / 2,
    })
  }, [media.height, media.width])

  useEffect(() => {
    fit()
    const container = containerRef.current
    if (!container) return
    const observer = new ResizeObserver(fit)
    observer.observe(container)
    return () => observer.disconnect()
  }, [fit, media.id])

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    event.preventDefault()
    const bounds = event.currentTarget.getBoundingClientRect()
    const next = zoomAroundPoint(zoom, zoom * (event.deltaY > 0 ? 0.88 : 1.12), offset, {
      x: event.clientX - bounds.left, y: event.clientY - bounds.top,
    })
    setZoom(next.zoom)
    setOffset(next.offset)
  }

  function pointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest('.zoom-controls')) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({ pointerId: event.pointerId, x: event.clientX, y: event.clientY })
  }

  function pointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drag || drag.pointerId !== event.pointerId) return
    setOffset((current) => ({ x: current.x + event.clientX - drag.x, y: current.y + event.clientY - drag.y }))
    setDrag({ ...drag, x: event.clientX, y: event.clientY })
  }

  return <figure className="evidence-stage">
    <figcaption>{label}</figcaption>
    <div
      ref={containerRef}
      className={`image-stage image-stage--pan ${drag ? 'image-stage--dragging' : ''}`}
      onWheel={handleWheel}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={() => setDrag(null)}
      onPointerCancel={() => setDrag(null)}
      role="group"
      aria-label={`Evidence view: ${label}`}
    >
      <div className="image-layer" style={{ width: media.width, height: media.height, transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})` }}>
        <img src={media.image_url} alt="" draggable={false} />
        <svg className="annotation-overlay" viewBox={`0 0 ${media.width} ${media.height}`} pointerEvents="none">
          <EvidenceShapes sources={sources} regions={regions} classes={classes} alpha={alpha} />
        </svg>
      </div>
      <div className="zoom-controls" aria-label="Zoom controls">
        <Button variant="ghost" aria-label="Zoom out" onClick={() => setZoom((value) => clampZoom(value / 1.2))}><Minus size={17} /></Button>
        <output className="zoom-value" aria-label="Preview scale">{Math.round(zoom * 100)}%</output>
        <Button variant="ghost" aria-label="Zoom in" onClick={() => setZoom((value) => clampZoom(value * 1.2))}><Plus size={17} /></Button>
        <Button variant="ghost" aria-label="Fit image" onClick={fit}><Maximize size={17} /></Button>
      </div>
    </div>
  </figure>
}
