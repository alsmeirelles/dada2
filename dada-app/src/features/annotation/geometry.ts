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

export function coordinatePairs(coordinates: number[]) {
  const result: string[] = []
  for (let index = 0; index < coordinates.length; index += 2) {
    result.push(`${coordinates[index]},${coordinates[index + 1]}`)
  }
  return result.join(' ')
}
