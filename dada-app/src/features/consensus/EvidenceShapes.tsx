import { ringsPath } from '../annotation/geometry'
import type { ProjectClassInput } from '../projects/types'
import type { CandidateRegion, EvidenceSource } from './consensus-view-model'
import { classLabel } from './consensus-view-model'

type EvidenceShapesProps = {
  sources: EvidenceSource[]
  regions: CandidateRegion[]
  classes: ProjectClassInput[]
  alpha: number
}

/** Read-only SVG shapes in original-image pixels; each source keeps its colour and dash pattern. */
export function EvidenceShapes({ sources, regions, classes, alpha }: EvidenceShapesProps) {
  return <>
    {regions.map((region) => {
      const [x, y, width, height] = region.region
      return <g key={region.key} data-region={region.key}>
        <rect className={`evidence-region evidence-region--${region.passed ? 'passed' : 'review'}`} x={x} y={y} width={width} height={height}><title>{region.label}</title></rect>
        <text className="shape-label" x={x + 4} y={Math.max(14, y - 4)}>{region.label}</text>
      </g>
    })}
    {sources.flatMap((source) => source.objects.map((object) => {
      const geometry = object.geometry
      if (!geometry) return null
      const key = `${source.id}:${object.id}`
      const common = {
        className: 'evidence-shape',
        'data-source': source.id,
        stroke: source.color,
        strokeDasharray: source.dash || undefined,
      }
      const title = <title>{`${source.label}: ${classLabel(classes, object.class_id)}`}</title>
      if (geometry.type === 'rectangle') {
        const [x, y, width, height] = geometry.coordinates
        return <rect key={key} {...common} x={x} y={y} width={width} height={height} fill="none">{title}</rect>
      }
      return <path key={key} {...common} d={ringsPath(geometry.coordinates)} fillRule="evenodd" fill={source.color} fillOpacity={alpha}>{title}</path>
    }))}
  </>
}
