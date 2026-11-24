import { describe, expect, it } from 'vitest'

import type { Capabilities } from '../../api/capabilities'
import { learningCatalog } from './learning-catalog.fixture'
import {
  defaultLearning,
  iterationLimitProblem,
  learningBody,
  learningProblem,
  learningSummary,
  selectSolution,
} from './learning-settings'

const capabilities = learningCatalog as Capabilities

describe('active-learning settings', () => {
  it('starts from the first solution that can run, its defaults, and the task metric', () => {
    expect(defaultLearning(capabilities, 'classification')).toEqual({
      solution: 'deterministic',
      configuration: { retain_helper_models: false, model_name: null },
      metric: 'accuracy',
      interval: 1,
      target: null,
    })
  })

  it('leaves the solution empty and blocks saving when nothing can run', () => {
    const none = { ...capabilities, active_learning_solutions: [capabilities.active_learning_solutions[0]!] }
    const draft = defaultLearning(none, 'detection')

    expect(draft.solution).toBe('')
    expect(learningProblem(draft, none, 'detection')).toBe('No active-learning solution can run on this server for this task.')
  })

  it('checks the solution settings, the evaluation interval, and the metric target', () => {
    const draft = defaultLearning(capabilities, 'detection')

    expect(learningProblem(draft, capabilities, 'detection')).toBeNull()
    expect(learningProblem({ ...draft, configuration: { ...draft.configuration, model_name: ' ' } }, capabilities, 'detection')).toBe('Fix the solution settings marked above.')
    expect(learningProblem({ ...draft, interval: 0 }, capabilities, 'detection')).toBe('Evaluate after a whole number of iterations, from 1 to 1000.')
    expect(learningProblem({ ...draft, target: 1.2 }, capabilities, 'detection')).toBe('The metric target must be greater than 0 and at most 1.')
    expect(learningProblem({ ...selectSolution(capabilities, draft, 'dada') }, capabilities, 'detection')).toBe('The selected solution cannot run on this server.')
    expect(iterationLimitProblem(0)).toBe('The iteration limit must be a whole number from 1 to 10,000.')
  })

  it('sends the API fields and summarizes them in one line', () => {
    const draft = { ...defaultLearning(capabilities, 'detection'), interval: 2, target: 0.8 }

    expect(learningBody(draft)).toEqual({
      learning_solution: 'deterministic',
      learning_configuration: { retain_helper_models: false, model_name: null },
      evaluation_metric: 'map50',
      evaluation_interval: 2,
      metric_target: 0.8,
    })
    expect(learningSummary(draft, capabilities)).toBe('Deterministic (development) · mAP@50 every 2 iterations · stops at 0.8')
  })
})
