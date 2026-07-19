import { LoaderCircle, Maximize, Minus, Plus } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent,
} from 'react'

import { Button } from '../../components/ui/Button'
import type { ProjectClassInput } from '../projects/types'
import { coordinatePairs, flattenPoints, normalizedBox, type Point } from './geometry'
import type {
  AnnotationDocument,
  AnnotationObject,
  AnnotationTool,
  Lease,
} from './types'
import { clampZoom, zoomAroundPoint } from './viewport'

type DraftBox = { start: Point; end: Point; pointerId: number }

type ImageStageProps = {
  media: Lease['media']
  document: AnnotationDocument
  classes: ProjectClassInput[]
  tool: AnnotationTool
  selectedClassId: string | null
  selectedObjectId: string | null
  locked: boolean
  samPending: boolean
  onChange: (document: AnnotationDocument) => void
  onSelectObject: (id: string | null) => void
  onSamPoint: (point: Point) => void
  onNotice: (message: string) => void
}

export function ImageStage({
  media,
  document,
  classes,
  tool,
  selectedClassId,
  selectedObjectId,
  locked,
  samPending,
  onChange,
  onSelectObject,
  onSamPoint,
  onNotice,
}: ImageStageProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [drag, setDrag] = useState<{ pointerId: number; x: number; y: number } | null>(null)
  const [spaceHeld, setSpaceHeld] = useState(false)
  const [draftBox, setDraftBox] = useState<DraftBox | null>(null)
  const [polygonPoints, setPolygonPoints] = useState<Point[]>([])
  const [hoverPoint, setHoverPoint] = useState<Point | null>(null)

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

  const finishPolygon = useCallback(() => {
    if (polygonPoints.length < 3) {
      if (polygonPoints.length) onNotice('A polygon needs at least three points.')
      return
    }
    if (!selectedClassId) {
      onNotice('Select a class before creating an annotation.')
      return
    }
    onChange(addObject(document, {
      id: crypto.randomUUID(),
      class_id: selectedClassId,
      geometry: { type: 'polygon', coordinates: [flattenPoints(polygonPoints)] },
      attributes: {},
    }))
    setPolygonPoints([])
    setHoverPoint(null)
  }, [document, onChange, onNotice, polygonPoints, selectedClassId])

  useEffect(() => {
    fit()
    setDraftBox(null)
    setPolygonPoints([])
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
      if (event.key === 'Escape') {
        setDraftBox(null)
        setPolygonPoints([])
        setHoverPoint(null)
      }
      if ((event.key === 'Enter' || event.key.toLowerCase() === 'n') && tool === 'polygon') {
        event.preventDefault()
        finishPolygon()
      }
    }
    window.addEventListener('keydown', key)
    window.addEventListener('keyup', key)
    return () => {
      window.removeEventListener('keydown', key)
      window.removeEventListener('keyup', key)
    }
  }, [finishPolygon, fit, tool])

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    event.preventDefault()
    const bounds = event.currentTarget.getBoundingClientRect()
    const point = { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
    const next = zoomAroundPoint(zoom, zoom * (event.deltaY > 0 ? 0.88 : 1.12), offset, point)
    setZoom(next.zoom)
    setOffset(next.offset)
  }

  function stagePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!(tool === 'pan' || spaceHeld || event.button === 1)) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({ pointerId: event.pointerId, x: event.clientX, y: event.clientY })
  }

  function stagePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drag || drag.pointerId !== event.pointerId) return
    setOffset((current) => ({
      x: current.x + event.clientX - drag.x,
      y: current.y + event.clientY - drag.y,
    }))
    setDrag({ ...drag, x: event.clientX, y: event.clientY })
  }

  function overlayPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (locked || spaceHeld || event.button !== 0) return
    const point = imagePoint(event.clientX, event.clientY, event.currentTarget)
    if (tool === 'box') {
      if (!selectedClassId) return onNotice('Select a class before drawing a box.')
      event.currentTarget.setPointerCapture(event.pointerId)
      setDraftBox({ start: point, end: point, pointerId: event.pointerId })
      onSelectObject(null)
    } else if (tool === 'polygon') {
      if (!selectedClassId) return onNotice('Select a class before drawing a polygon.')
      setPolygonPoints((current) => [...current, point])
    } else if (tool === 'sam-point' && !samPending) {
      if (!selectedClassId) return onNotice('Select a class before using assisted segmentation.')
      onSamPoint(point)
    } else if (tool === 'select') {
      onSelectObject(null)
    }
  }

  function overlayPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const point = imagePoint(event.clientX, event.clientY, event.currentTarget)
    if (draftBox?.pointerId === event.pointerId) setDraftBox({ ...draftBox, end: point })
    if (tool === 'polygon' && polygonPoints.length) setHoverPoint(point)
  }

  function overlayPointerUp(event: ReactPointerEvent<SVGSVGElement>) {
    if (!draftBox || draftBox.pointerId !== event.pointerId || !selectedClassId) return
    const box = normalizedBox(draftBox.start, draftBox.end)
    setDraftBox(null)
    if (box.width < 2 || box.height < 2) return
    const object: AnnotationObject = {
      id: crypto.randomUUID(),
      class_id: selectedClassId,
      geometry: { type: 'rectangle', coordinates: [box.x, box.y, box.width, box.height] },
      attributes: {},
    }
    onChange(addObject(document, object))
    onSelectObject(object.id)
  }

  const draftRectangle = draftBox ? normalizedBox(draftBox.start, draftBox.end) : null
  const draftPolygon = [...polygonPoints, ...(hoverPoint ? [hoverPoint] : [])]
  const interactive = !locked && !spaceHeld && tool !== 'pan'

  return (
    <div
      ref={containerRef}
      className={`image-stage ${tool === 'pan' || spaceHeld ? 'image-stage--pan' : ''} ${drag ? 'image-stage--dragging' : ''}`}
      onWheel={handleWheel}
      onPointerDown={stagePointerDown}
      onPointerMove={stagePointerMove}
      onPointerUp={() => setDrag(null)}
      onPointerCancel={() => setDrag(null)}
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
        <svg
          className={`annotation-overlay annotation-overlay--${tool}`}
          viewBox={`0 0 ${media.width} ${media.height}`}
          onPointerDown={interactive ? overlayPointerDown : undefined}
          onPointerMove={interactive ? overlayPointerMove : undefined}
          onPointerUp={interactive ? overlayPointerUp : undefined}
          onDoubleClick={tool === 'polygon' ? finishPolygon : undefined}
        >
          {document.objects.map((object, index) => (
            <AnnotationShape
              key={object.id}
              object={object}
              color={classColor(classes, object.class_id)}
              selected={object.id === selectedObjectId}
              index={index + 1}
              onSelect={() => tool === 'select' && onSelectObject(object.id)}
            />
          ))}
          {draftRectangle && <rect className="shape-draft" x={draftRectangle.x} y={draftRectangle.y} width={draftRectangle.width} height={draftRectangle.height} style={{ color: classColor(classes, selectedClassId) }} />}
          {draftPolygon.length > 0 && <polyline className="shape-draft" points={draftPolygon.map((point) => `${point.x},${point.y}`).join(' ')} style={{ color: classColor(classes, selectedClassId) }} />}
          {polygonPoints.map((point, index) => <circle key={`${point.x}-${point.y}-${index}`} className="polygon-point" cx={point.x} cy={point.y} r={4 / zoom} style={{ color: classColor(classes, selectedClassId) }} />)}
        </svg>
      </div>
      {samPending && <div className="sam-progress"><LoaderCircle size={16} /> Predicting mask…</div>}
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

function AnnotationShape({ object, color, selected, index, onSelect }: { object: AnnotationObject; color: string; selected: boolean; index: number; onSelect: () => void }) {
  if (!object.geometry) return null
  const common = { className: `annotation-shape ${selected ? 'selected' : ''}`, style: { color }, onPointerDown: (event: ReactPointerEvent) => { event.stopPropagation(); onSelect() } }
  if (object.geometry.type === 'rectangle') {
    const [x, y, width, height] = object.geometry.coordinates
    return <g><rect {...common} x={x} y={y} width={width} height={height} /><text className="shape-label" x={x + 4} y={Math.max(14, y + 14)}>{index}</text></g>
  }
  const ring = object.geometry.coordinates[0] ?? []
  return <g><polygon {...common} points={coordinatePairs(ring)} /><text className="shape-label" x={ring[0] ?? 0} y={(ring[1] ?? 0) + 14}>{index}</text></g>
}

function addObject(document: AnnotationDocument, object: AnnotationObject): AnnotationDocument {
  return { ...document, objects: [...document.objects, object] }
}

function imagePoint(clientX: number, clientY: number, svg: SVGSVGElement): Point {
  const bounds = svg.getBoundingClientRect()
  const viewBox = svg.viewBox.baseVal
  return {
    x: Math.min(viewBox.width, Math.max(0, (clientX - bounds.left) * viewBox.width / bounds.width)),
    y: Math.min(viewBox.height, Math.max(0, (clientY - bounds.top) * viewBox.height / bounds.height)),
  }
}

function classColor(classes: ProjectClassInput[], classId: string | null) {
  return classes.find((item) => item.id === classId)?.color ?? '#8B7CF6'
}

function isEditingText(target: EventTarget | null) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement ||
    (target instanceof HTMLElement && target.isContentEditable)
}
