import { useId } from 'react'

import type { PipelineCapability, StrategyCapability, TaskTypeName } from '../../api/capabilities'
import {
  CLASS_STRATEGY_GROUP,
  GEOMETRY_STRATEGY_GROUP,
  boundsText,
  configFields,
  configurationWarnings,
  fieldLabel,
  selectStrategy,
  selectedStrategy,
  setFieldValue,
  strategyBlock,
  unavailableText,
  validateConfiguration,
  valueAt,
  type ConfigField,
  type EligibilityState,
  type FieldScope,
  type ResolverConfiguration,
} from './resolver-config'
import { resolverLabel } from './resolver-label'

type ResolverConfigFormProps = {
  taskType: TaskTypeName
  pipeline: PipelineCapability
  value: ResolverConfiguration
  onChange: (value: ResolverConfiguration) => void
  eligibility: EligibilityState
  /** Omitted where the setting does not apply, such as a retry configuration. */
  requireIndependentAdjudicator?: boolean
  onRequireIndependentAdjudicatorChange?: (value: boolean) => void
  disabled?: boolean
}

/** The consensus resolution settings, drawn entirely from the capability descriptors. */
export function ResolverConfigForm({
  taskType,
  pipeline,
  value,
  onChange,
  eligibility,
  requireIndependentAdjudicator,
  onRequireIndependentAdjudicatorChange,
  disabled = false,
}: ResolverConfigFormProps) {
  const id = useId()
  const fields = configFields(taskType, pipeline, value)
  const problems = validateConfiguration(fields, value)
  const warnings = configurationWarnings(taskType, pipeline, value, eligibility)
  const geometryGroup = GEOMETRY_STRATEGY_GROUP[taskType]
  const main = (scope: FieldScope) => fields.filter((field) => field.scope === scope && !field.descriptor.advanced)
  const advanced = fields.filter((field) => field.descriptor.advanced)
  const setting = (field: ConfigField) => <SettingField
    key={field.key}
    id={`${id}-${field.key}`}
    field={field}
    value={valueAt(value, field.path)}
    problem={problems[field.key]}
    disabled={disabled}
    onChange={(next) => onChange(setFieldValue(value, field.path, next))}
  />

  return <div className="resolver-form">
    <div className="resolver-pipeline">
      <span>Resolution pipeline</span>
      <strong>{resolverLabel(pipeline.id)}</strong>
      <small>Version {pipeline.version}. It estimates a best annotation from the independent submissions; images it cannot resolve confidently go to review.</small>
      {pipeline.unavailable_reason && <small className="resolver-unavailable">{unavailableText(pipeline.unavailable_reason)}</small>}
    </div>
    <StrategyPicker
      legend="Class strategy"
      name={`${id}-class`}
      strategies={pipeline.class_strategies}
      selected={selectedStrategy(pipeline.class_strategies, value.parameters[CLASS_STRATEGY_GROUP])?.id}
      eligibility={eligibility}
      disabled={disabled}
      onSelect={(strategy) => onChange(selectStrategy(taskType, pipeline, value, 'class', strategy))}
    />
    {main('class').map(setting)}
    {geometryGroup && <StrategyPicker
      legend={resolverLabel(geometryGroup)}
      name={`${id}-geometry`}
      strategies={pipeline.geometry_strategies}
      selected={selectedStrategy(pipeline.geometry_strategies, value.parameters[geometryGroup])?.id}
      eligibility={eligibility}
      disabled={disabled}
      onSelect={(strategy) => onChange(selectStrategy(taskType, pipeline, value, 'geometry', strategy))}
    />}
    {main('geometry').map(setting)}
    {main('pipeline').map(setting)}
    {main('threshold').map(setting)}
    {advanced.length > 0 && <details className="resolver-advanced"><summary>Advanced settings</summary>{advanced.map(setting)}</details>}
    {onRequireIndependentAdjudicatorChange && <div className="resolver-check">
      <input id={`${id}-independent`} type="checkbox" checked={Boolean(requireIndependentAdjudicator)} disabled={disabled} onChange={(event) => onRequireIndependentAdjudicatorChange(event.target.checked)} />
      <label htmlFor={`${id}-independent`}><strong>Require an independent adjudicator</strong><small>When on, owners and managers who contributed evidence for an image, as an annotator or a reviewer, cannot adjudicate it. When off, they may, with a rationale, and the conflict is recorded.</small></label>
    </div>}
    {warnings.length > 0 && <ul className="resolver-warnings" aria-label="Resolver warnings" aria-live="polite">{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
  </div>
}

function StrategyPicker({ legend, name, strategies, selected, eligibility, disabled, onSelect }: {
  legend: string
  name: string
  strategies: StrategyCapability[]
  selected: string | undefined
  eligibility: EligibilityState
  disabled: boolean
  onSelect: (strategy: string) => void
}) {
  return <fieldset className="resolver-strategies"><legend>{legend}</legend>
    {strategies.map((strategy) => {
      const block = strategyBlock(strategy, eligibility)
      const inputId = `${name}-${strategy.id}`
      return <div key={strategy.id} className={strategy.id === selected ? 'resolver-strategy selected' : 'resolver-strategy'}>
        <input type="radio" id={inputId} name={name} checked={strategy.id === selected} disabled={disabled || Boolean(block)} onChange={() => onSelect(strategy.id)} aria-describedby={block ? `${inputId}-reason` : undefined} />
        <label htmlFor={inputId}>
          <strong>{resolverLabel(strategy.id)}</strong>
          <small>Version {strategy.version}{strategy.conditional ? ' · depends on this project\'s evidence' : ''}</small>
          {block && <small id={`${inputId}-reason`} className="resolver-unavailable">{block}</small>}
        </label>
      </div>
    })}
  </fieldset>
}

function SettingField({ id, field, value, problem, disabled, onChange }: {
  id: string
  field: ConfigField
  value: unknown
  problem: string | undefined
  disabled: boolean
  onChange: (value: unknown) => void
}) {
  const { descriptor } = field
  const label = fieldLabel(descriptor.name)
  const helpId = `${id}-help`
  const errorId = `${id}-error`
  const describedBy = problem ? `${helpId} ${errorId}` : helpId
  const help = [
    descriptor.help,
    descriptor.unit ? `Unit: ${descriptor.unit}.` : null,
    boundsText(descriptor),
    descriptor.nullable ? 'Leave it empty to turn it off.' : null,
  ].filter(Boolean).join(' ')
  const common = { disabled, 'aria-invalid': Boolean(problem), 'aria-describedby': describedBy }
  const number = (raw: string) => raw === '' ? null : Number(raw)
  const footer = <><small id={helpId}>{help}</small>{problem && <small id={errorId} className="resolver-field-error">{problem}</small>}</>

  if (descriptor.kind === 'ratio') {
    const ratio = (value ?? {}) as { numerator?: number | null; denominator?: number | null }
    return <fieldset className="resolver-field"><legend>{label}</legend>
      <span className="resolver-pair">
        <input {...common} type="number" min={0} step={1} aria-label={`${label}, votes`} value={ratio.numerator ?? ''} onChange={(event) => onChange({ ...ratio, numerator: number(event.target.value) })} />
        <span aria-hidden="true">out of</span>
        <input {...common} type="number" min={1} step={1} aria-label={`${label}, out of`} value={ratio.denominator ?? ''} onChange={(event) => onChange({ ...ratio, denominator: number(event.target.value) })} />
      </span>
      {footer}
    </fieldset>
  }
  if (descriptor.kind === 'area') {
    const area = (value ?? {}) as { pixels?: number | null; image_ratio?: number | null }
    const change = (next: typeof area) => onChange(next.pixels == null && next.image_ratio == null && descriptor.nullable ? null : next)
    return <fieldset className="resolver-field"><legend>{label}</legend>
      <span className="resolver-pair">
        <input {...common} type="number" min={1} step={1} aria-label={`${label}, pixels`} placeholder="pixels" value={area.pixels ?? ''} onChange={(event) => change({ ...area, pixels: number(event.target.value) })} />
        <span aria-hidden="true">or</span>
        <input {...common} type="number" min={0} max={1} step="any" aria-label={`${label}, share of the image`} placeholder="share of image" value={area.image_ratio ?? ''} onChange={(event) => change({ ...area, image_ratio: number(event.target.value) })} />
      </span>
      {footer}
    </fieldset>
  }
  if (descriptor.kind === 'boolean') {
    return <div className="resolver-field resolver-field--check">
      <label htmlFor={id}><input {...common} id={id} type="checkbox" checked={value === true} onChange={(event) => onChange(event.target.checked)} /> {label}</label>
      {footer}
    </div>
  }
  return <div className="resolver-field">
    <label htmlFor={id}>{label}</label>
    {descriptor.kind === 'enum'
      ? <select {...common} id={id} value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)}>
        {(descriptor.options ?? []).map((option) => <option key={option} value={option}>{resolverLabel(option)}</option>)}
      </select>
      : <input {...common} id={id} type="number" step={descriptor.kind === 'integer' ? 1 : 'any'} value={typeof value === 'number' ? value : ''} onChange={(event) => onChange(number(event.target.value))} />}
    {footer}
  </div>
}
