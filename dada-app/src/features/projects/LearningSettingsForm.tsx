import { useId } from 'react'

import type { Capabilities, TaskTypeName } from '../../api/capabilities'
import {
  MAX_EVALUATION_INTERVAL,
  METRIC_LABELS,
  selectSolution,
  solutionFields,
  solutionsFor,
} from './learning-settings'
import { SettingField } from './ResolverConfigForm'
import { unavailableText, valueProblem, type ConfigField } from './resolver-config'
import type { LearningDraft } from './types'

type LearningSettingsFormProps = {
  taskType: TaskTypeName
  capabilities: Capabilities
  value: LearningDraft
  onChange: (value: LearningDraft) => void
  disabled?: boolean
}

/** The active-learning solution, its settings, and the evaluation plan, drawn from the API catalog. */
export function LearningSettingsForm({ taskType, capabilities, value, onChange, disabled = false }: LearningSettingsFormProps) {
  const id = useId()
  const solutions = solutionsFor(capabilities, taskType)
  const solution = solutions.find((item) => item.id === value.solution)
  const fields = solution ? solutionFields(solution) : []
  const problem = (field: ConfigField) => valueProblem(field.descriptor, value.configuration[field.key]) ?? undefined
  const setting = (field: ConfigField) => <SettingField
    key={field.key}
    id={`${id}-${field.key}`}
    field={field}
    value={value.configuration[field.key]}
    problem={problem(field)}
    disabled={disabled}
    emptyHelp="Leave it empty to use the default."
    onChange={(next) => onChange({ ...value, configuration: { ...value.configuration, [field.key]: next } })}
  />
  const main = fields.filter((field) => !field.descriptor.advanced)
  const advanced = fields.filter((field) => field.descriptor.advanced)

  return <div className="resolver-form learning-form">
    <fieldset className="resolver-strategies"><legend>Active-learning solution</legend>
      {solutions.map((item) => {
        const inputId = `${id}-solution-${item.id}`
        return <div key={item.id} className={item.id === value.solution ? 'resolver-strategy selected' : 'resolver-strategy'}>
          <input type="radio" id={inputId} name={`${id}-solution`} checked={item.id === value.solution} disabled={disabled || Boolean(item.unavailable_reason)} onChange={() => onChange(selectSolution(capabilities, value, item.id))} aria-describedby={item.unavailable_reason ? `${inputId}-reason` : undefined} />
          <label htmlFor={inputId}>
            <strong>{item.display_name}</strong>
            <small>{item.description} Version {item.version}{item.development_only ? ' · development and testing only' : ''}</small>
            {item.unavailable_reason && <small id={`${inputId}-reason`} className="resolver-unavailable">{unavailableText(item.unavailable_reason)}</small>}
          </label>
        </div>
      })}
    </fieldset>
    {!solutions.some((item) => !item.unavailable_reason) && <p className="notice" role="status">No active-learning solution can run on this server for this task. Choose random acquisition, or ask an administrator to install a solution.</p>}
    {main.map(setting)}
    {advanced.length > 0 && <details className="resolver-advanced"><summary>Advanced solution settings</summary>{advanced.map(setting)}</details>}
    <div className="field-grid">
      <label className="field" htmlFor={`${id}-metric`}>Evaluation metric
        <select id={`${id}-metric`} value={value.metric} disabled={disabled} onChange={(event) => onChange({ ...value, metric: event.target.value as LearningDraft['metric'] })}>
          {capabilities.evaluation_metrics[taskType].map((metric) => <option key={metric} value={metric}>{METRIC_LABELS[metric]}</option>)}
        </select>
        <small>The target model is measured on the validation set with this metric, and on the test set when the loop ends.</small>
      </label>
      <label className="field" htmlFor={`${id}-interval`}>Evaluate every
        <input id={`${id}-interval`} type="number" min={1} max={MAX_EVALUATION_INTERVAL} step={1} value={value.interval} disabled={disabled} onChange={(event) => onChange({ ...value, interval: Number(event.target.value) })} />
        <small>Acquisition iterations between two evaluations of the target model.</small>
      </label>
      <label className="field" htmlFor={`${id}-target`}>Metric target <span className="optional">Optional</span>
        <input id={`${id}-target`} type="number" min={0} max={1} step={0.01} value={value.target ?? ''} disabled={disabled} onChange={(event) => onChange({ ...value, target: event.target.value === '' ? null : Number(event.target.value) })} />
        <small>The loop stops once the validation metric reaches this value, from above 0 to 1. Leave it empty to stop only at the iteration limit.</small>
      </label>
    </div>
  </div>
}
