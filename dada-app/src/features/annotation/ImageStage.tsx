import { LoaderCircle, Maximize, Minus, Plus } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'

import { Button } from '../../components/ui/Button'
import type { ProjectClassInput } from '../projects/types'
import { flattenPoints, normalizedBox, ringsPath, type Point } from './geometry'
import type {
  AnnotationDocument,
  AnnotationObject,
  AnnotationTool,
  AssignmentMedia,
  AssistPrompt,
} from './types'
import { fitView, zoomAroundPoint, type View } from './viewport'

type DraftBox = { start: Point; end: Point; pointerId: number }

const ZOOM_STEP = 1.2
/** A drag shorter than this, in image pixels, is a point prompt rather than a box. */
const MIN_PROMPT_BOX = 4

type ImageStageProps = {
  media: AssignmentMedia
  document: AnnotationDocument
  classes: ProjectClassInput[]
  tool: AnnotationTool
  selectedClassId: string | null
  selectedObjectId: string | null
  locked: boolean
  /** A model suggestion is on its way; the assist tool waits for it. */
  assistPending?: boolean
  /** The most objects the document may hold, as for an object target. */
  maxObjects?: number
  onChange: (document: AnnotationDocument) => void
  onSelectObject: (id: string | null) => void
  /** Called with a point or box drawn with the assist tool. */
  onAssist?: (prompt: AssistPrompt) => void
  onNotice: (message: string) => void
  /** Read-only SVG drawn beneath the objects in original-image pixels; it never takes pointer input. */
  overlay?: ReactNode
}

export function ImageStage({
  media,
  document,
  classes,
  tool,
  selectedClassId,
  selectedObjectId,
  locked,
  assistPending = false,
  maxObjects,
  onChange,
  onSelectObject,
  onAssist,
  onNotice,
  overlay,
}: ImageStageProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const pointer = useRef<Point | null>(null)
  const [view, setView] = useState<View>({ zoom: 1, offset: { x: 0, y: 0 } })
  const { zoom, offset } = view
  const [drag, setDrag] = useState<{ pointerId: number; x: number; y: number } | null>(null)
  const [spaceHeld, setSpaceHeld] = useState(false)
  const [draftBox, setDraftBox] = useState<DraftBox | null>(null)
  const [polygonPoints, setPolygonPoints] = useState<Point[]>([])
  const [hoverPoint, setHoverPoint] = useState<Point | null>(null)

  const fit = useCallback((whole: boolean) => {
    const container = containerRef.current
    if (!container) return
    setView(fitView(container.clientWidth, container.clientHeight, media.width, media.height, whole))
  }, [media.height, media.width])

  /** Zooms around a stage point, the canvas centre when none is given, so the image stays put (I7-04). */
  const zoomBy = useCallback((factor: number, point?: Point | null) => {
    const container = containerRef.current
    if (!container) return
    const anchor = point ?? { x: container.clientWidth / 2, y: container.clientHeight / 2 }
    setView((current) => zoomAroundPoint(current.zoom, current.zoom * factor, current.offset, anchor))
  }, [])

  const full = useCallback(() => {
    if (maxObjects === undefined || document.objects.length < maxObjects) return false
    onNotice('This assignment answers only the highlighted object. Delete the current one to draw it again.')
    return true
  }, [document.objects.length, maxObjects, onNotice])

  const finishPolygon = useCallback(() => {
    if (polygonPoints.length < 3) {
      if (polygonPoints.length) onNotice('A polygon needs at least three points.')
      return
    }
    if (!selectedClassId) {
      onNotice('Select a class before creating an annotation.')
      return
    }
    if (full()) return
    onChange(addObject(document, {
      id: crypto.randomUUID(),
      class_id: selectedClassId,
      geometry: { type: 'polygon', coordinates: [flattenPoints(polygonPoints)] },
      attributes: {},
    }))
    setPolygonPoints([])
    setHoverPoint(null)
  }, [document, full, onChange, onNotice, polygonPoints, selectedClassId])

  useLayoutEffect(() => {
    fit(false)
    setDraftBox(null)
    setPolygonPoints([])
    const container = containerRef.current
    if (!container) return
    const observer = new ResizeObserver(() => fit(false))
    observer.observe(container)
    return () => observer.disconnect()
  }, [fit, media.id])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    function wheel(event: WheelEvent) {
      event.preventDefault()
      const bounds = container!.getBoundingClientRect()
      zoomBy(event.deltaY > 0 ? 0.88 : 1.12, { x: event.clientX - bounds.left, y: event.clientY - bounds.top })
    }
    container.addEventListener('wheel', wheel, { passive: false })
    return () => container.removeEventListener('wheel', wheel)
  }, [zoomBy])

  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (isEditingText(event.target)) return
      if (event.code === 'Space') {
        setSpaceHeld(event.type === 'keydown')
        event.preventDefault()
      }
      if (event.type !== 'keydown') return
      if (event.key === '+' || event.key === '=') zoomBy(ZOOM_STEP, pointer.current)
      if (event.key === '-') zoomBy(1 / ZOOM_STEP, pointer.current)
      if (event.key === '0') fit(true)
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
  }, [finishPolygon, fit, tool, zoomBy])


  function stagePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!(tool === 'pan' || spaceHeld || event.button === 1)) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({ pointerId: event.pointerId, x: event.clientX, y: event.clientY })
  }

  function stagePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    pointer.current = { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
    if (!drag || drag.pointerId !== event.pointerId) return
    setView((current) => ({
      ...current,
      offset: { x: current.offset.x + event.clientX - drag.x, y: current.offset.y + event.clientY - drag.y },
    }))
    setDrag({ ...drag, x: event.clientX, y: event.clientY })
  }

  function overlayPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (locked || spaceHeld || event.button !== 0) return
    const point = imagePoint(event.clientX, event.clientY, event.currentTarget)
    if (tool === 'box') {
      if (!selectedClassId) return onNotice('Select a class before drawing a box.')
      if (full()) return
      event.currentTarget.setPointerCapture(event.pointerId)
      setDraftBox({ start: point, end: point, pointerId: event.pointerId })
      onSelectObject(null)
    } else if (tool === 'polygon') {
      if (!selectedClassId) return onNotice('Select a class before drawing a polygon.')
      if (!polygonPoints.length && full()) return
      setPolygonPoints((current) => [...current, point])
    } else if (tool === 'assist' && !assistPending) {
      event.currentTarget.setPointerCapture(event.pointerId)
      setDraftBox({ start: point, end: point, pointerId: event.pointerId })
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
    if (!draftBox || draftBox.pointerId !== event.pointerId) return
    const box = normalizedBox(draftBox.start, draftBox.end)
    setDraftBox(null)
    if (tool === 'assist') {
      onAssist?.(box.width < MIN_PROMPT_BOX || box.height < MIN_PROMPT_BOX
        ? { type: 'point', coordinates: [draftBox.end.x, draftBox.end.y] }
        : { type: 'box', coordinates: [box.x, box.y, box.width, box.height] })
      return
    }
    if (!selectedClassId || box.width < 2 || box.height < 2) return
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
      onPointerDown={stagePointerDown}
      onPointerMove={stagePointerMove}
      onPointerLeave={() => { pointer.current = null }}
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
          {overlay && <g className="stage-overlay" pointerEvents="none">{overlay}</g>}
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
          {draftRectangle && <rect className={tool === 'assist' ? 'shape-draft assist-draft' : 'shape-draft'} x={draftRectangle.x} y={draftRectangle.y} width={draftRectangle.width} height={draftRectangle.height} style={{ color: classColor(classes, selectedClassId) }} />}
          {draftPolygon.length > 0 && <polyline className="shape-draft" points={draftPolygon.map((point) => `${point.x},${point.y}`).join(' ')} style={{ color: classColor(classes, selectedClassId) }} />}
          {polygonPoints.map((point, index) => <circle key={`${point.x}-${point.y}-${index}`} className="polygon-point" cx={point.x} cy={point.y} r={4 / zoom} style={{ color: classColor(classes, selectedClassId) }} />)}
        </svg>
      </div>
      {assistPending && <div className="sam-progress" role="status"><LoaderCircle size={16} /> Asking the model…</div>}
      {locked && <div className="canvas-lock" role="status">Read-only — editing disabled</div>}
      <div className="zoom-controls" aria-label="Zoom controls">
        <Button variant="ghost" aria-label="Zoom out" onClick={() => zoomBy(1 / ZOOM_STEP)}><Minus size={17} /></Button>
        <button className="zoom-value" onClick={() => fit(true)} title="Fit image">{Math.round(zoom * 100)}%</button>
        <Button variant="ghost" aria-label="Zoom in" onClick={() => zoomBy(ZOOM_STEP)}><Plus size={17} /></Button>
        <Button variant="ghost" aria-label="Fit image" onClick={() => fit(true)}><Maximize size={17} /></Button>
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
  return <g><path {...common} d={ringsPath(object.geometry.coordinates)} fillRule="evenodd" /><text className="shape-label" x={ring[0] ?? 0} y={(ring[1] ?? 0) + 14}>{index}</text></g>
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
