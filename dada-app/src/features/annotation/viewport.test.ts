import { describe, expect, it } from 'vitest'

import { clampZoom, zoomAroundPoint } from './viewport'

describe('annotation viewport math', () => {
  it('clamps zoom to safe limits', () => {
    expect(clampZoom(0.01)).toBe(0.1)
    expect(clampZoom(20)).toBe(12)
  })

  it('keeps the cursor point stationary while zooming', () => {
    const result = zoomAroundPoint(1, 2, { x: 0, y: 0 }, { x: 100, y: 80 })
    expect(result).toEqual({ zoom: 2, offset: { x: -100, y: -80 } })
  })
})
