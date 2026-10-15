import { apiRequest } from './client'

export type TaskTypeName = 'classification' | 'detection' | 'segmentation'

export type UnavailableReason =
  | 'dependency_missing'
  | 'dependency_incompatible'
  | 'quarantined'
  | 'resource_profile_unvalidated'

/** An exact vote share; the API compares it by cross-multiplication. */
export type Ratio = { numerator: number; denominator: number }

/** An area limit; a mask region is affected only when it is below both values. */
export type Area = { pixels: number; image_ratio: number }

/**
 * One settable resolver field. `name` is dotted inside a group, for example
 * `class_strategy.alpha`; ratio bounds and defaults are `Ratio` objects.
 */
export type ParameterDescriptor = {
  name: string
  kind: 'ratio' | 'number' | 'integer' | 'enum' | 'boolean' | 'area'
  default: unknown
  nullable: boolean
  options: string[] | null
  minimum: unknown
  maximum: unknown
  minimum_inclusive: boolean | null
  maximum_inclusive: boolean | null
  advanced: boolean
  unit: string | null
  help: string | null
}

/** A selectable class or geometry strategy; it is never substituted when unavailable. */
export type StrategyCapability = {
  id: string
  version: string
  conditional: boolean
  unavailable_reason: UnavailableReason | null
  dependencies: Record<string, string | null>
  parameters: ParameterDescriptor[]
}

/** The single resolver pipeline of one task type, sent as the policy `resolver`. */
export type PipelineCapability = {
  id: string
  version: string
  unavailable_reason: UnavailableReason | null
  class_strategies: StrategyCapability[]
  geometry_strategies: StrategyCapability[]
  parameters: ParameterDescriptor[]
  review_thresholds: ParameterDescriptor[]
}

export type Capabilities = {
  supported_image_media_types: string[]
  max_file_bytes: number
  max_project_files: number
  upload_chunk_bytes: number
  upload_session_ttl_hours: number
  max_import_file_bytes: number
  supported_task_types: TaskTypeName[]
  supported_annotation_modes: Array<'single' | 'consensus'>
  consensus_pipelines: Record<TaskTypeName, PipelineCapability>
  realtime_transport: 'websocket' | 'polling'
}

export function getCapabilities(): Promise<Capabilities> {
  return apiRequest<Capabilities>('/api/v1/capabilities')
}
