export const MIN_ZOOM = 0.1
export const MAX_ZOOM = 12

export function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value))
}

/** The canvas transform: the image's scale and where its top-left corner sits in the stage. */
export type View = { zoom: number; offset: { x: number; y: number } }

/**
 * Centres the image in the stage (I7-04). An image opens across the full
 * canvas width; `whole` instead fits all of it inside the canvas.
 */
export function fitView(stageWidth: number, stageHeight: number, imageWidth: number, imageHeight: number, whole: boolean): View {
  const zoom = clampZoom(whole
    ? Math.min(stageWidth / imageWidth, stageHeight / imageHeight)
    : stageWidth / imageWidth)
  return {
    zoom,
    offset: { x: (stageWidth - imageWidth * zoom) / 2, y: (stageHeight - imageHeight * zoom) / 2 },
  }
}

export function zoomAroundPoint(
  currentZoom: number,
  nextZoom: number,
  offset: { x: number; y: number },
  point: { x: number; y: number },
): View {
  const ratio = clampZoom(nextZoom) / currentZoom
  return {
    zoom: clampZoom(nextZoom),
    offset: {
      x: point.x - (point.x - offset.x) * ratio,
      y: point.y - (point.y - offset.y) * ratio,
    },
  }
}
