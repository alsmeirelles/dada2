import { describe, expect, it } from 'vitest'

import { coordinatePairs, flattenPoints, normalizedBox } from './geometry'

describe('annotation geometry', () => {
  it('normalizes boxes dragged in any direction', () => {
    expect(normalizedBox({ x: 80, y: 60 }, { x: 20, y: 10 })).toEqual({
      x: 20, y: 10, width: 60, height: 50,
    })
  })

  it('serializes polygon points without changing original-pixel coordinates', () => {
    const points = [{ x: 1.5, y: 2 }, { x: 8, y: 3 }, { x: 4, y: 9 }]
    expect(flattenPoints(points)).toEqual([1.5, 2, 8, 3, 4, 9])
    expect(coordinatePairs(flattenPoints(points))).toBe('1.5,2 8,3 4,9')
  })
})
