import type { Capabilities } from '../../api/capabilities'

/** The active-learning part of `/capabilities` as the API returns it in development. */
export const learningCatalog: Pick<Capabilities, 'active_learning_solutions' | 'evaluation_metrics'> = {
  active_learning_solutions: [
    {
      id: 'dada',
      version: '1.0.0',
      display_name: 'DADA',
      description: 'Diversity-aware data acquisition.',
      supported_tasks: ['classification', 'detection', 'segmentation'],
      development_only: false,
      unavailable_reason: 'dependency_missing',
      parameters: [],
    },
    {
      id: 'deterministic',
      version: '1.0.0',
      display_name: 'Deterministic (development)',
      description: 'Reproducible ranking without a model.',
      supported_tasks: ['classification', 'detection', 'segmentation'],
      development_only: true,
      unavailable_reason: null,
      parameters: [
        { name: 'retain_helper_models', kind: 'boolean', default: false, nullable: false, options: null, minimum: null, maximum: null, minimum_inclusive: null, maximum_inclusive: null, advanced: false, unit: null, help: 'Keep the artifact folders after a success.' },
        { name: 'model_name', kind: 'string', default: null, nullable: true, options: null, minimum: null, maximum: null, minimum_inclusive: null, maximum_inclusive: null, advanced: false, unit: null, help: 'Model; the task default when omitted.' },
      ],
    },
  ],
  evaluation_metrics: {
    classification: ['accuracy', 'f1'],
    detection: ['map50'],
    segmentation: ['mean_iou'],
  },
}
