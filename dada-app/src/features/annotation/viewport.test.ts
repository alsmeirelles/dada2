import { describe, expect, it } from 'vitest'

import { clampZoom, fitView, zoomAroundPoint } from './viewport'

describe('annotation viewport math', () => {
  it('clamps zoom to safe limits', () => {
    expect(clampZoom(0.01)).toBe(0.1)
    expect(clampZoom(20)).toBe(12)
  })

  it('I7-04: opens an image centred across the full canvas width', () => {
    expect(fitView(1000, 600, 2000, 1000, false)).toEqual({ zoom: 0.5, offset: { x: 0, y: 50 } })
    expect(fitView(1000, 600, 500, 1000, false)).toEqual({ zoom: 2, offset: { x: 0, y: -700 } })
  })

  it('fits the whole image, centred, on request', () => {
    expect(fitView(1000, 600, 500, 1000, true)).toEqual({ zoom: 0.6, offset: { x: 350, y: 0 } })
  })

  it('keeps the cursor point stationary while zooming', () => {
    const result = zoomAroundPoint(1, 2, { x: 0, y: 0 }, { x: 100, y: 80 })
    expect(result).toEqual({ zoom: 2, offset: { x: -100, y: -80 } })
  })
})
