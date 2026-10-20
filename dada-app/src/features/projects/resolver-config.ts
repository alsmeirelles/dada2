import type {
  Area,
  ParameterDescriptor,
  PipelineCapability,
  Ratio,
  StrategyCapability,
  TaskTypeName,
  UnavailableReason,
} from '../../api/capabilities'
import type { ResolverEligibility } from '../consensus/consensus-types'
import { resolverLabel } from './resolver-label'
import type { ResolverSettings } from './types'

/** The closed configuration a policy or batch sends as `parameters` and `review_thresholds`. */
export type ResolverConfiguration = { parameters: ResolverSettings; review_thresholds: ResolverSettings }

/**
 * The parameter groups that hold a selected strategy and its own fields. The
 * descriptors list each pipeline's strategies but not these group names.
 */
export const CLASS_STRATEGY_GROUP = 'class_strategy'
export const GEOMETRY_STRATEGY_GROUP: Record<TaskTypeName, string | null> = {
  classification: null,
  detection: 'box_refinement',
  segmentation: 'mask_refinement',
}
/** Every step in this group can change the topology of an accepted mask. */
export const TOPOLOGY_GROUP = 'post_processing'

export type FieldScope = 'class' | 'geometry' | 'pipeline' | 'threshold'

/** One settable value, located by its path inside the configuration. */
export type ConfigField = { key: string; path: string[]; scope: FieldScope; descriptor: ParameterDescriptor }

/** What the API reported about the conditional strategies, if it could be asked. */
export type EligibilityState =
  | { status: 'no_project' }
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; report: ResolverEligibility }

const UNAVAILABLE_LABELS: Record<UnavailableReason, string> = {
  dependency_missing: 'a required library is not installed',
  dependency_incompatible: 'an installed library has an incompatible version',
  quarantined: 'an operator quarantined this version',
  resource_profile_unvalidated: 'its resource profile has not been validated',
}

export function unavailableText(reason: UnavailableReason, dependencies: Record<string, string | null> = {}) {
  const missing = Object.entries(dependencies).filter(([, version]) => version === null).map(([name]) => name)
  return `Unavailable: ${UNAVAILABLE_LABELS[reason]}${reason === 'dependency_missing' && missing.length ? ` (${missing.join(', ')})` : ''}.`
}

export function selectedStrategy(strategies: StrategyCapability[], group: unknown) {
  const id = isRecord(group) ? group.strategy : undefined
  return strategies.find((strategy) => strategy.id === id) ?? strategies[0]
}

export function configFields(taskType: TaskTypeName, pipeline: PipelineCapability, configuration: ResolverConfiguration): ConfigField[] {
  const geometryGroup = GEOMETRY_STRATEGY_GROUP[taskType]
  const classStrategy = selectedStrategy(pipeline.class_strategies, configuration.parameters[CLASS_STRATEGY_GROUP])
  const geometryStrategy = geometryGroup ? selectedStrategy(pipeline.geometry_strategies, configuration.parameters[geometryGroup]) : undefined
  const field = (scope: FieldScope, prefix: string[]) => (descriptor: ParameterDescriptor): ConfigField => {
    const path = [...prefix, ...descriptor.name.split('.')]
    return { key: path.join('.'), path, scope, descriptor }
  }
  return [
    ...(classStrategy?.parameters ?? []).map(field('class', ['parameters', CLASS_STRATEGY_GROUP])),
    ...(geometryGroup && geometryStrategy ? geometryStrategy.parameters.map(field('geometry', ['parameters', geometryGroup])) : []),
    ...pipeline.parameters.map(field('pipeline', ['parameters'])),
    ...pipeline.review_thresholds.map(field('threshold', ['review_thresholds'])),
  ]
}

/**
 * Reads a stored or recovered configuration through the descriptors: the
 * strategies it names are kept even when unavailable, unknown keys such as
 * the retired `agreement` are dropped, and missing values take their defaults.
 * The first listed strategy is the default, as in the API catalog.
 */
export function projectConfiguration(taskType: TaskTypeName, pipeline: PipelineCapability, source?: Partial<ResolverConfiguration> | null): ResolverConfiguration {
  const configuration: ResolverConfiguration = { parameters: {}, review_thresholds: {} }
  const sourceParameters = isRecord(source?.parameters) ? source.parameters : {}
  const classStrategy = selectedStrategy(pipeline.class_strategies, sourceParameters[CLASS_STRATEGY_GROUP])
  if (classStrategy) configuration.parameters[CLASS_STRATEGY_GROUP] = { strategy: classStrategy.id }
  const geometryGroup = GEOMETRY_STRATEGY_GROUP[taskType]
  const geometryStrategy = geometryGroup ? selectedStrategy(pipeline.geometry_strategies, sourceParameters[geometryGroup]) : undefined
  if (geometryGroup && geometryStrategy) configuration.parameters[geometryGroup] = { strategy: geometryStrategy.id }
  for (const field of configFields(taskType, pipeline, configuration)) {
    const value = valueAt(source, field.path)
    assign(configuration, field.path, value === undefined ? structuredClone(field.descriptor.default) : value)
  }
  return configuration
}

export function defaultConfiguration(taskType: TaskTypeName, pipeline: PipelineCapability) {
  return projectConfiguration(taskType, pipeline, null)
}

/** Switches a strategy; the previous strategy's fields are dropped and the new one starts from its defaults. */
export function selectStrategy(taskType: TaskTypeName, pipeline: PipelineCapability, configuration: ResolverConfiguration, scope: 'class' | 'geometry', id: string): ResolverConfiguration {
  const group = scope === 'class' ? CLASS_STRATEGY_GROUP : GEOMETRY_STRATEGY_GROUP[taskType]
  const strategy = (scope === 'class' ? pipeline.class_strategies : pipeline.geometry_strategies).find((item) => item.id === id)
  if (!group || !strategy) return configuration
  const settings: ResolverSettings = { strategy: strategy.id }
  for (const descriptor of strategy.parameters) assign(settings, descriptor.name.split('.'), structuredClone(descriptor.default))
  return { ...configuration, parameters: { ...configuration.parameters, [group]: settings } }
}

/**
 * Defaults that follow the segmentation matching metric: Dice 2/3 is the
 * equivalent of IoU 0.5. The API applies them only to omitted fields and the
 * descriptors cannot express them, so the form mirrors the rule.
 */
export const METRIC_DEFAULTS: Record<string, Record<string, number>> = {
  'parameters.matching_threshold': { iou: 0.5, dice: 2 / 3 },
  'review_thresholds.minimum_median_overlap': { iou: 0.5, dice: 2 / 3 },
}
const METRIC_KEY = 'parameters.matching_metric'

/** Sets one value; switching the metric moves a dependent field still at the old metric's default to the new one's. */
export function setFieldValue(configuration: ResolverConfiguration, path: string[], value: unknown): ResolverConfiguration {
  const next = structuredClone(configuration)
  assign(next, path, value)
  if (path.join('.') !== METRIC_KEY) return next
  const previous = String(valueAt(configuration, METRIC_KEY.split('.')))
  for (const [key, defaults] of Object.entries(METRIC_DEFAULTS)) {
    const fieldPath = key.split('.')
    const target = defaults[String(value)]
    if (target !== undefined && valueAt(configuration, fieldPath) === defaults[previous]) assign(next, fieldPath, target)
  }
  return next
}

export function valueAt(source: unknown, path: string[]): unknown {
  let current = source
  for (const segment of path) {
    if (!isRecord(current)) return undefined
    current = current[segment]
  }
  return current
}

/** True when the client finds nothing to fix; the API still validates the configuration. */
export function configurationIsValid(taskType: TaskTypeName, pipeline: PipelineCapability, configuration: ResolverConfiguration) {
  return Object.keys(validateConfiguration(configFields(taskType, pipeline, configuration), configuration)).length === 0
}

/** Client checks taken from the descriptors; the API stays authoritative. Keyed by field. */
export function validateConfiguration(fields: ConfigField[], configuration: ResolverConfiguration) {
  const problems: Record<string, string> = {}
  for (const field of fields) {
    const problem = valueProblem(field.descriptor, valueAt(configuration, field.path))
    if (problem) problems[field.key] = problem
  }
  return problems
}

export function valueProblem(descriptor: ParameterDescriptor, value: unknown): string | null {
  if (value === null && descriptor.nullable) return null
  switch (descriptor.kind) {
    case 'boolean':
      return typeof value === 'boolean' ? null : 'Choose on or off.'
    case 'enum':
      return typeof value === 'string' && (descriptor.options ?? []).includes(value) ? null : 'Choose one of the listed options.'
    case 'integer':
    case 'number':
      if (typeof value !== 'number' || !Number.isFinite(value)) return 'Enter a number.'
      if (descriptor.kind === 'integer' && !Number.isInteger(value)) return 'Enter a whole number.'
      return boundsProblem(descriptor, (bound) => typeof bound === 'number' ? value - bound : null)
    case 'ratio': {
      if (!isRatio(value)) return 'Enter whole numbers for both parts, with at least 1 below the line.'
      if (value.numerator > value.denominator) return 'A share cannot be more than 1.'
      return boundsProblem(descriptor, (bound) => isRatio(bound) ? value.numerator * bound.denominator - bound.numerator * value.denominator : null)
    }
    case 'area': {
      if (!isRecord(value)) return 'Enter both a pixel count and an image share.'
      const { pixels, image_ratio: ratio } = value
      if (typeof pixels !== 'number' || !Number.isInteger(pixels) || pixels < 1) return 'Pixels must be a whole number of at least 1.'
      if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio <= 0 || ratio >= 1) return 'The image share must be greater than 0 and less than 1.'
      return null
    }
  }
}

function boundsProblem(descriptor: ParameterDescriptor, compare: (bound: unknown) => number | null) {
  const low = compare(descriptor.minimum)
  if (low !== null && (low < 0 || (low === 0 && descriptor.minimum_inclusive === false))) {
    return `Must be ${descriptor.minimum_inclusive === false ? 'greater than' : 'at least'} ${formatSetting(descriptor.minimum)}.`
  }
  const high = compare(descriptor.maximum)
  if (high !== null && (high > 0 || (high === 0 && descriptor.maximum_inclusive === false))) {
    return `Must be ${descriptor.maximum_inclusive === false ? 'less than' : 'at most'} ${formatSetting(descriptor.maximum)}.`
  }
  return null
}

/** The descriptor's bounds in words, such as `Greater than 1/2 and at most 1/1.` */
export function boundsText(descriptor: ParameterDescriptor) {
  const parts: string[] = []
  if (descriptor.minimum !== null) parts.push(`${descriptor.minimum_inclusive === false ? 'greater than' : 'at least'} ${formatSetting(descriptor.minimum)}`)
  if (descriptor.maximum !== null) parts.push(`${descriptor.maximum_inclusive === false ? 'less than' : 'at most'} ${formatSetting(descriptor.maximum)}`)
  const text = parts.join(' and ')
  return text ? `${text[0]!.toLocaleUpperCase()}${text.slice(1)}.` : ''
}

export function fieldLabel(name: string) {
  return resolverLabel(name.split('.').at(-1)!)
}

/** Why a strategy cannot be chosen now, or null when it can. */
export function strategyBlock(strategy: StrategyCapability, eligibility: EligibilityState): string | null {
  if (strategy.unavailable_reason) return unavailableText(strategy.unavailable_reason, strategy.dependencies)
  if (!strategy.conditional) return null
  if (eligibility.status === 'no_project') return 'Needs evidence from this project\'s own resolved images, so it can be chosen in the project settings once that evidence exists.'
  if (eligibility.status === 'loading') return 'Checking this project\'s evidence…'
  if (eligibility.status === 'error') return 'This project\'s evidence could not be checked.'
  const verdict = eligibility.report.strategies.find((item) => item.strategy === strategy.id)
  if (!verdict) return 'The API reported no eligibility for this strategy.'
  if (verdict.eligible) return null
  const guidance = evidenceGuidance(strategy.id, verdict.missing)
  return `Available after this project has ${guidance}.`
}

function evidenceGuidance(strategy: string, missing: { requirement: string; [detail: string]: unknown }[]) {
  const requirements = new Map(missing.map((gap) => [gap.requirement, gap.required]))
  const count = (requirement: string) => typeof requirements.get(requirement) === 'number'
    ? String(requirements.get(requirement))
    : 'enough'
  const phrases = strategy === 'reliability_weighted_vote'
    ? [
        requirements.has('decisions_per_rater') ? `${count('decisions_per_rater')} reference decisions for each selected annotator` : null,
        requirements.has('observations_per_outcome') ? `${count('observations_per_outcome')} reference decisions for every class from each selected annotator` : null,
      ]
    : [
        requirements.has('calibration_items') ? `${count('calibration_items')} resolved images annotated by at least three selected annotators` : null,
        requirements.has('observations_per_rater') ? `${count('observations_per_rater')} observations from each selected annotator` : null,
        requirements.has('observations_per_outcome') ? `${count('observations_per_outcome')} observations for every class` : null,
        requirements.has('convergence') ? 'evidence that produces a stable estimate' : null,
      ]
  const visible = phrases.filter((phrase): phrase is string => phrase !== null)
  if (!visible.length) return 'enough resolved images from every selected annotator and class'
  if (visible.length === 1) return visible[0]
  return `${visible.slice(0, -1).join(', ')}, and ${visible.at(-1)}`
}

/** Notices shown before saving: more review, mask topology, and strategies that cannot run as configured. */
export function configurationWarnings(taskType: TaskTypeName, pipeline: PipelineCapability, configuration: ResolverConfiguration, eligibility: EligibilityState) {
  const warnings: string[] = []
  if (pipeline.unavailable_reason) warnings.push(`The ${resolverLabel(pipeline.id)} pipeline is ${unavailableText(pipeline.unavailable_reason).toLocaleLowerCase()} Its runs fail and images go to manual review; nothing is substituted.`)
  const geometryGroup = GEOMETRY_STRATEGY_GROUP[taskType]
  const chosen = [
    selectedStrategy(pipeline.class_strategies, configuration.parameters[CLASS_STRATEGY_GROUP]),
    geometryGroup ? selectedStrategy(pipeline.geometry_strategies, configuration.parameters[geometryGroup]) : undefined,
  ]
  for (const strategy of chosen) {
    if (!strategy) continue
    if (strategy.unavailable_reason) {
      warnings.push(`${resolverLabel(strategy.id)} is ${unavailableText(strategy.unavailable_reason, strategy.dependencies).toLocaleLowerCase()} Its runs fail and images go to manual review; nothing is substituted.`)
    } else if (strategy.conditional && strategyBlock(strategy, eligibility)) {
      warnings.push(`A batch cannot start with ${resolverLabel(strategy.id)} until the API reports this project's evidence as sufficient.`)
    }
  }
  for (const field of configFields(taskType, pipeline, configuration)) {
    const value = valueAt(configuration, field.path)
    if (valueProblem(field.descriptor, value)) continue
    if (field.scope === 'threshold' && stricterThan(value, field.descriptor.default)) {
      warnings.push(`${fieldLabel(field.descriptor.name)} is stricter than its default of ${formatSetting(field.descriptor.default)}, so more images will need review.`)
    }
    if (field.path[1] === TOPOLOGY_GROUP && value !== null) {
      warnings.push(`${fieldLabel(field.descriptor.name)} can change the topology of accepted masks; an instance that changes materially goes to review.`)
    }
  }
  return warnings
}

function stricterThan(value: unknown, fallback: unknown) {
  if (typeof value === 'number' && typeof fallback === 'number') return value > fallback
  if (isRatio(value) && isRatio(fallback)) return value.numerator * fallback.denominator > fallback.numerator * value.denominator
  return false
}

/** A short readable value: ratios as `2/3`, areas with units, catalog identifiers as words, and `off` for an unset step. */
export function formatSetting(value: unknown): string {
  if (value === null || value === undefined) return 'off'
  if (isRatio(value)) return value.denominator === 1 ? String(value.numerator) : `${value.numerator}/${value.denominator}`
  if (isArea(value)) return `${String(value.pixels)} px or ${String(value.image_ratio)} of the image`
  if (typeof value === 'string') return /^[a-z][a-z0-9_]*$/.test(value) ? resolverLabel(value) : value
  if (typeof value === 'boolean') return value ? 'on' : 'off'
  if (Array.isArray(value)) return `${value.length} selected`
  if (isRecord(value)) return summarizeSettings(value).map((line) => `${line.label}: ${line.value}`).join(', ')
  return String(value)
}

/** One readable line per setting, for batch cards and the policy history. */
export function summarizeSettings(settings: ResolverSettings) {
  const lines: Array<{ label: string; value: string }> = []
  for (const [name, value] of Object.entries(settings)) {
    if (name === 'strategy') continue
    if (isRecord(value) && 'strategy' in value) lines.push({ label: resolverLabel(name), value: formatSetting(value.strategy) })
    if (isRecord(value) && !isRatio(value) && !isArea(value)) lines.push(...summarizeSettings(value))
    else lines.push({ label: resolverLabel(name), value: formatSetting(value) })
  }
  return lines
}

export function isRatio(value: unknown): value is Ratio {
  return isRecord(value) && Number.isInteger(value.numerator) && Number.isInteger(value.denominator) &&
    (value.numerator as number) >= 0 && (value.denominator as number) >= 1
}

function isArea(value: unknown): value is Area {
  return isRecord(value) && 'pixels' in value && 'image_ratio' in value
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function assign(target: Record<string, unknown>, path: string[], value: unknown) {
  let current = target
  for (const segment of path.slice(0, -1)) {
    if (!isRecord(current[segment])) current[segment] = {}
    current = current[segment] as Record<string, unknown>
  }
  current[path.at(-1)!] = value
}
