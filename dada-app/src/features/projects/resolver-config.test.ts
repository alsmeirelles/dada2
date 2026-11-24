import { describe, expect, it } from 'vitest'

import type { PipelineCapability } from '../../api/capabilities'
import { consensusPipelines } from './resolver-catalog.fixture'
import {
  boundsText,
  configFields,
  configurationWarnings,
  defaultConfiguration,
  projectConfiguration,
  selectStrategy,
  setFieldValue,
  strategyBlock,
  summarizeSettings,
  validateConfiguration,
  type EligibilityState,
} from './resolver-config'

const { classification, detection, segmentation } = consensusPipelines

describe('matching metric defaults', () => {
  const metric = ['parameters', 'matching_metric']
  const threshold = ['parameters', 'matching_threshold']
  const overlap = ['review_thresholds', 'minimum_median_overlap']

  it('moves untouched thresholds to the Dice equivalent and back', () => {
    const dice = setFieldValue(defaultConfiguration('segmentation', segmentation), metric, 'dice')
    const iou = setFieldValue(dice, metric, 'iou')

    expect([dice.parameters.matching_threshold, dice.review_thresholds.minimum_median_overlap]).toEqual([2 / 3, 2 / 3])
    expect([iou.parameters.matching_threshold, iou.review_thresholds.minimum_median_overlap]).toEqual([0.5, 0.5])
  })

  it('keeps a threshold the user chose', () => {
    const custom = setFieldValue(setFieldValue(defaultConfiguration('segmentation', segmentation), threshold, 0.7), overlap, 0.6)
    const dice = setFieldValue(custom, metric, 'dice')

    expect([dice.parameters.matching_threshold, dice.review_thresholds.minimum_median_overlap]).toEqual([0.7, 0.6])
  })
})
const noProject: EligibilityState = { status: 'no_project' }

describe('resolver configuration defaults', () => {
  it('reproduces the defaults the API fills in for every task', () => {
    expect(defaultConfiguration('classification', classification)).toEqual({
      parameters: { class_strategy: { strategy: 'multilabel_binary_vote' } },
      review_thresholds: { minimum_support: { numerator: 2, denominator: 3 } },
    })
    expect(defaultConfiguration('detection', detection)).toEqual({
      parameters: {
        class_strategy: { strategy: 'categorical_vote', decision_rule: 'supermajority' },
        matching_iou: 0.5,
        box_refinement: { strategy: 'coordinate_median' },
      },
      review_thresholds: { minimum_support: { numerator: 2, denominator: 3 }, minimum_median_iou: 0.5 },
    })
    expect(defaultConfiguration('segmentation', segmentation)).toEqual({
      parameters: {
        class_strategy: { strategy: 'categorical_vote', decision_rule: 'supermajority' },
        matching_metric: 'iou',
        matching_threshold: 0.5,
        mask_refinement: { strategy: 'segmentation_majority_vote' },
        post_processing: { remove_components_below: null, fill_holes_below: null, simplify_tolerance: null },
      },
      review_thresholds: { minimum_support: { numerator: 2, denominator: 3 }, minimum_median_overlap: 0.5 },
    })
  })

  it('reads a stored configuration, dropping the retired agreement threshold and unknown keys', () => {
    const stored = {
      parameters: { class_strategy: { strategy: 'dirichlet_vote', alpha: 2, minimum_posterior: 0.95, extra: 1 }, matching_iou: 0.6, legacy: true },
      review_thresholds: { agreement: 0.75, minimum_support: { numerator: 3, denominator: 4 } },
    }

    expect(projectConfiguration('detection', detection, stored)).toEqual({
      parameters: {
        class_strategy: { strategy: 'dirichlet_vote', alpha: 2, minimum_posterior: 0.95 },
        matching_iou: 0.6,
        box_refinement: { strategy: 'coordinate_median' },
      },
      review_thresholds: { minimum_support: { numerator: 3, denominator: 4 }, minimum_median_iou: 0.5 },
    })
  })
})

describe('strategy switching', () => {
  it('drops the previous strategy\'s fields and starts from the new one\'s defaults', () => {
    const dirichlet = selectStrategy('detection', detection, defaultConfiguration('detection', detection), 'class', 'dirichlet_vote')
    expect(dirichlet.parameters.class_strategy).toEqual({ strategy: 'dirichlet_vote', alpha: 0.5, minimum_posterior: 0.9 })

    const back = selectStrategy('detection', detection, dirichlet, 'class', 'categorical_vote')
    expect(back.parameters.class_strategy).toEqual({ strategy: 'categorical_vote', decision_rule: 'supermajority' })
  })

  it('puts the geometry strategy in the task\'s own group', () => {
    const trimmed = selectStrategy('detection', detection, defaultConfiguration('detection', detection), 'geometry', 'trimmed_mean_box')
    expect(trimmed.parameters.box_refinement).toEqual({ strategy: 'trimmed_mean_box', trim_fraction: 0.2 })

    const staple = selectStrategy('segmentation', segmentation, defaultConfiguration('segmentation', segmentation), 'geometry', 'staple')
    expect(staple.parameters.mask_refinement).toEqual({ strategy: 'staple', pixel_threshold: 0.5 })
  })

  it('nests dotted names inside their group', () => {
    const configuration = defaultConfiguration('segmentation', segmentation)
    const field = configFields('segmentation', segmentation, configuration).find((item) => item.descriptor.name === 'post_processing.simplify_tolerance')!

    expect(field.path).toEqual(['parameters', 'post_processing', 'simplify_tolerance'])
    expect(setFieldValue(configuration, field.path, 1.5).parameters.post_processing).toEqual({
      remove_components_below: null, fill_holes_below: null, simplify_tolerance: 1.5,
    })
  })
})

describe('client validation', () => {
  function problems(configuration = defaultConfiguration('detection', detection)) {
    return validateConfiguration(configFields('detection', detection, configuration), configuration)
  }

  it('accepts the defaults', () => {
    expect(problems()).toEqual({})
  })

  it('refuses a vote threshold at or below the majority floor', () => {
    const base = defaultConfiguration('detection', detection)
    const path = ['review_thresholds', 'minimum_support']

    expect(problems(setFieldValue(base, path, { numerator: 1, denominator: 2 }))['review_thresholds.minimum_support']).toBe('Must be greater than 1/2.')
    expect(problems(setFieldValue(base, path, { numerator: 2, denominator: 5 }))['review_thresholds.minimum_support']).toBe('Must be greater than 1/2.')
    expect(problems(setFieldValue(base, path, { numerator: 3, denominator: 2 }))['review_thresholds.minimum_support']).toBe('A share cannot be more than 1.')
    expect(problems(setFieldValue(base, path, { numerator: 1, denominator: 1 }))).toEqual({})
  })

  it('applies bound inclusivity from the descriptors', () => {
    const base = defaultConfiguration('detection', detection)

    expect(problems(setFieldValue(base, ['parameters', 'matching_iou'], 0))['parameters.matching_iou']).toBe('Must be greater than 0.')
    expect(problems(setFieldValue(base, ['parameters', 'matching_iou'], 1))).toEqual({})
    expect(problems(setFieldValue(base, ['parameters', 'matching_iou'], null))['parameters.matching_iou']).toBe('Enter a number.')
    const trimmed = selectStrategy('detection', detection, base, 'geometry', 'trimmed_mean_box')
    expect(problems(setFieldValue(trimmed, ['parameters', 'box_refinement', 'trim_fraction'], 0))).toEqual({})
    expect(problems(setFieldValue(trimmed, ['parameters', 'box_refinement', 'trim_fraction'], 0.41))['parameters.box_refinement.trim_fraction']).toBe('Must be at most 0.4.')
  })

  it('allows an unset nullable area and checks a set one', () => {
    const base = defaultConfiguration('segmentation', segmentation)
    const path = ['parameters', 'post_processing', 'fill_holes_below']
    const check = (value: unknown) => validateConfiguration(configFields('segmentation', segmentation, base), setFieldValue(base, path, value))

    expect(check(null)).toEqual({})
    expect(check({ pixels: 20, image_ratio: 0.01 })).toEqual({})
    expect(check({ pixels: 0, image_ratio: 0.01 })['parameters.post_processing.fill_holes_below']).toBe('Pixels must be a whole number of at least 1.')
    expect(check({ pixels: 20, image_ratio: 1 })['parameters.post_processing.fill_holes_below']).toBe('The image share must be greater than 0 and less than 1.')
  })

  it('describes bounds in words', () => {
    const support = detection.review_thresholds.find((item) => item.name === 'minimum_support')!
    expect(boundsText(support)).toBe('Greater than 1/2 and at most 1.')
  })
})

describe('strategy availability', () => {
  const conditional = detection.class_strategies.find((item) => item.id === 'dawid_skene')!

  it('disables a conditional strategy before the project exists', () => {
    expect(strategyBlock(conditional, noProject)).toMatch(/project's own resolved images/)
    expect(strategyBlock(detection.class_strategies[0]!, noProject)).toBeNull()
  })

  it('turns raw missing prerequisites into concise user guidance', () => {
    const eligibility: EligibilityState = {
      status: 'ready',
      report: { strategies: [{ strategy: 'dawid_skene', eligible: false, missing: [{ requirement: 'observations_per_outcome', rater: 'internal-user-id', outcome: 'internal-class-id', required: 5, found: 0 }], report: {} }] },
    }
    expect(strategyBlock(conditional, eligibility)).toBe('Available after this project has 5 observations for every class.')
    expect(strategyBlock(conditional, { status: 'ready', report: { strategies: [{ strategy: 'dawid_skene', eligible: true, missing: [], report: {} }] } })).toBeNull()
  })

  it('combines repeated per-rater diagnostics into one requirement', () => {
    const reliability = detection.class_strategies.find((item) => item.id === 'reliability_weighted_vote')!
    const eligibility: EligibilityState = {
      status: 'ready',
      report: { strategies: [{ strategy: 'reliability_weighted_vote', eligible: false, missing: [
        { requirement: 'decisions_per_rater', rater: 'internal-user-1', required: 30, found: 0 },
        { requirement: 'decisions_per_rater', rater: 'internal-user-2', required: 30, found: 0 },
        { requirement: 'observations_per_outcome', rater: 'internal-user-1', outcome: 'internal-class-1', required: 5, found: 0 },
      ], report: {} }] },
    }

    expect(strategyBlock(reliability, eligibility)).toBe('Available after this project has 30 reference decisions for each selected annotator, and 5 reference decisions for every class from each selected annotator.')
  })

  it('shows the exact reason a strategy is unavailable, and never substitutes it', () => {
    const missing: PipelineCapability = {
      ...segmentation,
      geometry_strategies: segmentation.geometry_strategies.map((item) => item.id === 'segmentation_rasa'
        ? { ...item, unavailable_reason: 'dependency_missing', dependencies: { ...item.dependencies, 'crowd-kit': null } }
        : item),
    }
    const rasa = missing.geometry_strategies.find((item) => item.id === 'segmentation_rasa')!
    expect(strategyBlock(rasa, noProject)).toBe('Unavailable: a required library is not installed (crowd-kit).')

    const stored = projectConfiguration('segmentation', missing, { parameters: { mask_refinement: { strategy: 'segmentation_rasa' } } })
    expect(stored.parameters.mask_refinement).toEqual({ strategy: 'segmentation_rasa' })
    expect(configurationWarnings('segmentation', missing, stored, noProject).join(' ')).toMatch(/Segmentation RASA is unavailable.*nothing is substituted/)
  })
})

describe('warnings before saving', () => {
  it('warns when a threshold is stricter than its default', () => {
    const stricter = setFieldValue(defaultConfiguration('detection', detection), ['review_thresholds', 'minimum_median_iou'], 0.7)

    expect(configurationWarnings('detection', detection, stricter, noProject)).toEqual([
      'Minimum median IoU is stricter than its default of 0.5, so more images will need review.',
    ])
    expect(configurationWarnings('detection', detection, setFieldValue(stricter, ['review_thresholds', 'minimum_median_iou'], 0.4), noProject)).toEqual([])
  })

  it('warns before enabling a topology-changing post-processing step', () => {
    const base = defaultConfiguration('segmentation', segmentation)
    const enabled = setFieldValue(base, ['parameters', 'post_processing', 'remove_components_below'], { pixels: 10, image_ratio: 0.001 })

    expect(configurationWarnings('segmentation', segmentation, base, noProject)).toEqual([])
    expect(configurationWarnings('segmentation', segmentation, enabled, noProject)).toEqual([
      'Remove components below can change the topology of accepted masks; an instance that changes materially goes to review.',
    ])
  })

  it('warns that a stored conditional strategy cannot start a batch yet', () => {
    const configuration = selectStrategy('classification', classification, defaultConfiguration('classification', classification), 'class', 'dawid_skene')

    expect(configurationWarnings('classification', classification, configuration, noProject)).toEqual([
      'A batch cannot start with Dawid skene until the API reports this project\'s evidence as sufficient.',
    ])
  })
})

describe('summaries', () => {
  it('reads a configuration as one line per setting', () => {
    const configuration = defaultConfiguration('detection', detection)

    expect([...summarizeSettings(configuration.parameters), ...summarizeSettings(configuration.review_thresholds)]).toEqual([
      { label: 'Class strategy', value: 'Categorical vote' },
      { label: 'Decision rule', value: 'Supermajority' },
      { label: 'Box refinement', value: 'Coordinate median' },
      { label: 'Matching IoU', value: '0.5' },
      { label: 'Minimum support', value: '2/3' },
      { label: 'Minimum median IoU', value: '0.5' },
    ])
  })
})
