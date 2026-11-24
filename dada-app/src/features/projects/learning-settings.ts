import type {
  Capabilities,
  EvaluationMetric,
  SolutionCapability,
  TaskTypeName,
} from '../../api/capabilities'
import { formatSetting, valueProblem, type ConfigField } from './resolver-config'
import type { LearningDraft, Project, ResolverSettings } from './types'

export const METRIC_LABELS: Record<EvaluationMetric, string> = {
  accuracy: 'Accuracy',
  f1: 'Macro F1',
  map50: 'mAP@50',
  mean_iou: 'Mean IoU',
}

export const MAX_EVALUATION_INTERVAL = 1000
export const MAX_ACQUISITION_ITERATIONS = 10_000

/** The solutions listed for a task, available or not; nothing is ever substituted. */
export function solutionsFor(capabilities: Capabilities, taskType: TaskTypeName) {
  return capabilities.active_learning_solutions.filter((solution) => solution.supported_tasks.includes(taskType))
}

/** A solution's settings as form fields, located by name inside the configuration. */
export function solutionFields(solution: SolutionCapability): ConfigField[] {
  return solution.parameters.map((descriptor) => ({
    key: descriptor.name,
    path: [descriptor.name],
    scope: 'pipeline',
    descriptor,
  }))
}

export function solutionDefaults(solution: SolutionCapability): ResolverSettings {
  return Object.fromEntries(solution.parameters.map((descriptor) => [descriptor.name, structuredClone(descriptor.default)]))
}

/**
 * The settings a new active-learning project starts from: the first solution
 * that can run here, its defaults, the task's first metric, an evaluation after
 * every iteration, and no metric target. With no runnable solution the choice
 * stays empty and the form explains why.
 */
export function defaultLearning(capabilities: Capabilities, taskType: TaskTypeName): LearningDraft {
  const solution = solutionsFor(capabilities, taskType).find((item) => !item.unavailable_reason)
  return {
    solution: solution?.id ?? '',
    configuration: solution ? solutionDefaults(solution) : {},
    metric: capabilities.evaluation_metrics[taskType][0]!,
    interval: 1,
    target: null,
  }
}

/** The saved settings of an active-learning project. */
export function projectLearning(project: Project, capabilities: Capabilities): LearningDraft {
  return {
    solution: project.learning_solution ?? '',
    configuration: project.learning_configuration,
    metric: project.evaluation_metric ?? capabilities.evaluation_metrics[project.task_type][0]!,
    interval: project.evaluation_interval ?? 1,
    target: project.metric_target,
  }
}

export function selectSolution(capabilities: Capabilities, draft: LearningDraft, id: string): LearningDraft {
  const solution = capabilities.active_learning_solutions.find((item) => item.id === id)
  return { ...draft, solution: id, configuration: solution ? solutionDefaults(solution) : {} }
}

/** What still blocks saving these settings, or null; the API stays authoritative. */
export function learningProblem(draft: LearningDraft | null, capabilities: Capabilities | undefined, taskType: TaskTypeName) {
  if (!draft || !capabilities) return 'The active-learning catalog has not loaded from the API yet.'
  const solution = solutionsFor(capabilities, taskType).find((item) => item.id === draft.solution)
  if (!solution) return 'No active-learning solution can run on this server for this task.'
  if (solution.unavailable_reason) return 'The selected solution cannot run on this server.'
  if (solutionFields(solution).some((field) => valueProblem(field.descriptor, draft.configuration[field.key]))) {
    return 'Fix the solution settings marked above.'
  }
  if (!Number.isInteger(draft.interval) || draft.interval < 1 || draft.interval > MAX_EVALUATION_INTERVAL) {
    return `Evaluate after a whole number of iterations, from 1 to ${MAX_EVALUATION_INTERVAL}.`
  }
  if (draft.target !== null && !(draft.target > 0 && draft.target <= 1)) return 'The metric target must be greater than 0 and at most 1.'
  return null
}

export function iterationLimitProblem(value: number) {
  return Number.isInteger(value) && value >= 1 && value <= MAX_ACQUISITION_ITERATIONS
    ? null
    : `The iteration limit must be a whole number from 1 to ${MAX_ACQUISITION_ITERATIONS.toLocaleString('en')}.`
}

/** The project fields that carry these settings. */
export function learningBody(draft: LearningDraft) {
  return {
    learning_solution: draft.solution,
    learning_configuration: draft.configuration,
    evaluation_metric: draft.metric,
    evaluation_interval: draft.interval,
    metric_target: draft.target,
  }
}

/** One line such as `DADA · mAP@50 every 2 iterations · stops at 0.8`. */
export function learningSummary(draft: LearningDraft, capabilities: Capabilities | undefined) {
  const solution = capabilities?.active_learning_solutions.find((item) => item.id === draft.solution)
  const every = draft.interval === 1 ? 'every iteration' : `every ${draft.interval} iterations`
  return [
    solution?.display_name ?? draft.solution,
    `${METRIC_LABELS[draft.metric]} ${every}`,
    draft.target === null ? 'no metric target' : `stops at ${formatSetting(draft.target)}`,
  ].join(' · ')
}
