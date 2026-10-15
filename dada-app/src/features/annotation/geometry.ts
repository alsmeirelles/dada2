export type Point = { x: number; y: number }

export function normalizedBox(start: Point, end: Point) {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  }
}

export function flattenPoints(points: Point[]) {
  return points.flatMap((point) => [point.x, point.y])
}

/** An SVG path of every ring; with `fill-rule: evenodd`, inner rings render as holes. */
export function ringsPath(rings: number[][]) {
  return rings
    .filter((ring) => ring.length >= 6)
    .map((ring) => `M${coordinatePairs(ring).split(' ').join('L')}Z`)
    .join('')
}

export function coordinatePairs(coordinates: number[]) {
  const result: string[] = []
  for (let index = 0; index < coordinates.length; index += 2) {
    result.push(`${coordinates[index]},${coordinates[index + 1]}`)
  }
  return result.join(' ')
}
