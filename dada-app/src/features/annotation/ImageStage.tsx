import { Maximize, Minus, Plus } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent,
} from 'react'

import { Button } from '../../components/ui/Button'
import type { Lease } from './types'
import { clampZoom, zoomAroundPoint } from './viewport'

type ImageStageProps = {
  media: Lease['media']
  panMode: boolean
  locked: boolean
}

export function ImageStage({ media, panMode, locked }: ImageStageProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [drag, setDrag] = useState<{ pointerId: number; x: number; y: number } | null>(null)
  const [spaceHeld, setSpaceHeld] = useState(false)

  const fit = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const padding = 56
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

  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (isEditingText(event.target)) return
      if (event.code === 'Space') {
        setSpaceHeld(event.type === 'keydown')
        event.preventDefault()
      }
      if (event.type !== 'keydown') return
      if (event.key === '+' || event.key === '=') setZoom((value) => clampZoom(value * 1.2))
      if (event.key === '-') setZoom((value) => clampZoom(value / 1.2))
      if (event.key === '0') fit()
    }
    window.addEventListener('keydown', key)
    window.addEventListener('keyup', key)
    return () => {
      window.removeEventListener('keydown', key)
      window.removeEventListener('keyup', key)
    }
  }, [fit])

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    event.preventDefault()
    const bounds = event.currentTarget.getBoundingClientRect()
    const point = { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
    const next = zoomAroundPoint(zoom, zoom * (event.deltaY > 0 ? 0.88 : 1.12), offset, point)
    setZoom(next.zoom)
    setOffset(next.offset)
  }

  function pointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!(panMode || spaceHeld || event.button === 1)) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({ pointerId: event.pointerId, x: event.clientX, y: event.clientY })
  }

  function pointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drag || drag.pointerId !== event.pointerId) return
    setOffset((current) => ({
      x: current.x + event.clientX - drag.x,
      y: current.y + event.clientY - drag.y,
    }))
    setDrag({ ...drag, x: event.clientX, y: event.clientY })
  }

  function pointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (drag?.pointerId === event.pointerId) setDrag(null)
  }

  return (
    <div
      ref={containerRef}
      className={`image-stage ${panMode || spaceHeld ? 'image-stage--pan' : ''} ${drag ? 'image-stage--dragging' : ''}`}
      onWheel={handleWheel}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={pointerUp}
      aria-label="Annotation image canvas"
    >
      <div
        className="image-layer"
        style={{
          width: media.width,
          height: media.height,
          transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
        }}
      >
        <img src={media.image_url} alt={media.relative_path} draggable={false} />
        <div className="annotation-overlay" aria-hidden="true" />
      </div>
      {locked && <div className="canvas-lock" role="alert">Lease lost — editing disabled</div>}
      <div className="zoom-controls" aria-label="Zoom controls">
        <Button variant="ghost" aria-label="Zoom out" onClick={() => setZoom((value) => clampZoom(value / 1.2))}><Minus size={17} /></Button>
        <button className="zoom-value" onClick={fit} title="Fit image">{Math.round(zoom * 100)}%</button>
        <Button variant="ghost" aria-label="Zoom in" onClick={() => setZoom((value) => clampZoom(value * 1.2))}><Plus size={17} /></Button>
        <Button variant="ghost" aria-label="Fit image" onClick={fit}><Maximize size={17} /></Button>
      </div>
    </div>
  )
}

function isEditingText(target: EventTarget | null) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement ||
    (target instanceof HTMLElement && target.isContentEditable)
}
