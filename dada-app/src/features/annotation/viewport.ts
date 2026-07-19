export const MIN_ZOOM = 0.1
export const MAX_ZOOM = 12

export function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value))
}

export function zoomAroundPoint(
  currentZoom: number,
  nextZoom: number,
  offset: { x: number; y: number },
  point: { x: number; y: number },
) {
  const ratio = clampZoom(nextZoom) / currentZoom
  return {
    zoom: clampZoom(nextZoom),
    offset: {
      x: point.x - (point.x - offset.x) * ratio,
      y: point.y - (point.y - offset.y) * ratio,
    },
  }
}
