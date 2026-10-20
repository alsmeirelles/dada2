import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  buildPolicyBody,
  buildProjectCreateBody,
  listEligibleAnnotators,
  minimumDatasetSize,
  resolveAnnotatorIds,
  resolveDraftSplitSize,
  resolvedFirstTrainingSize,
  type ProjectMember,
} from './project-api'
import type { ProjectDraft } from './types'

afterEach(() => vi.unstubAllGlobals())

const members: ProjectMember[] = [
  { user_id: 'id-owner', username: 'owner', display_name: 'Owner', role: 'owner' },
  { user_id: 'id-ana', username: 'ana', display_name: 'Ana', role: 'annotator' },
  { user_id: 'id-bruno', username: 'bruno', display_name: 'Bruno', role: 'annotator' },
]

const baseDraft: ProjectDraft = {
  name: 'Road defects',
  description: '',
  taskType: 'detection',
  classes: [],
  acquisitionStrategy: 'random',
  datasetLayout: 'split',
  initialTrainingSize: 10,
  testSetSize: 5,
  testSetUnit: 'count',
  validationSetSize: 10,
  validationSetUnit: 'percentage',
  iterationBatchSize: 5,
  collaborators: ['ana', 'bruno'],
  annotationPolicy: { mode: 'single' },
}

describe('eligible annotators', () => {
  it('loads every page of active users', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        items: [{ id: 'id-ana', username: 'ana', display_name: 'Ana' }],
        next_cursor: 'next page',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        items: [{ id: 'id-bruno', username: 'bruno', display_name: 'Bruno' }],
        next_cursor: null,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)

    await expect(listEligibleAnnotators('token')).resolves.toEqual([
      { id: 'id-ana', username: 'ana', display_name: 'Ana' },
      { id: 'id-bruno', username: 'bruno', display_name: 'Bruno' },
    ])
    expect(fetch).toHaveBeenNthCalledWith(2, expect.stringContaining('cursor=next%20page'), expect.anything())
  })
})

describe('resolveAnnotatorIds', () => {
  it('maps usernames to persisted member IDs in order', () => {
    expect(resolveAnnotatorIds(members, ['bruno', 'ana'])).toEqual([
      'id-bruno',
      'id-ana',
    ])
  })

  it('resolves the owner, who may annotate', () => {
    expect(resolveAnnotatorIds(members, ['owner'])).toEqual(['id-owner'])
  })

  it('refuses a username that is not a member', () => {
    expect(() => resolveAnnotatorIds(members, ['ghost'])).toThrow(
      'ghost is not a project member.',
    )
  })
})

describe('split sizing', () => {
  it('sends exactly one size definition for each held-out split', () => {
    expect(buildProjectCreateBody(baseDraft)).toMatchObject({
      test_set_size: 5,
      test_set_percentage: null,
      validation_set_size: null,
      validation_set_percentage: 10,
    })
  })

  it('rounds percentage sizes up like the API', () => {
    expect(resolveDraftSplitSize(12, 20, 'percentage')).toBe(3)
    expect(resolveDraftSplitSize(12, 4, 'count')).toBe(4)
  })

  it('finds the smallest dataset a percentage-sized held-out set can fit (I6-01)', () => {
    const defaults: ProjectDraft = { ...baseDraft, initialTrainingSize: null, testSetSize: 10, testSetUnit: 'count', validationSetSize: 10, validationSetUnit: 'percentage', iterationBatchSize: 20 }

    expect(minimumDatasetSize(defaults)).toBe(34)
    expect(resolveDraftSplitSize(33, 10, 'percentage') + 10 + 20).toBeGreaterThan(33)
    expect(minimumDatasetSize({ ...defaults, validationSetUnit: 'count' })).toBe(40)
    expect(minimumDatasetSize({ ...defaults, testSetSize: 90, testSetUnit: 'percentage' })).toBeNull()
  })
})

describe('dataset layout', () => {
  it('sends a null first batch so the API uses the iteration size', () => {
    const draft: ProjectDraft = { ...baseDraft, initialTrainingSize: null }

    expect(buildProjectCreateBody(draft)).toMatchObject({
      dataset_layout: 'split',
      initial_training_size: null,
      iteration_batch_size: 5,
    })
    expect(resolvedFirstTrainingSize(draft)).toBe(5)
    expect(resolvedFirstTrainingSize(baseDraft)).toBe(10)
  })

  it('sends no size fields for a static single batch', () => {
    expect(buildProjectCreateBody({ ...baseDraft, datasetLayout: 'single_batch' })).toEqual({
      name: 'Road defects',
      description: null,
      task_type: 'detection',
      acquisition_strategy: 'random',
      dataset_layout: 'single_batch',
    })
  })
})

describe('acquisition strategy', () => {
  it('persists the chosen strategy with the project', () => {
    expect(buildProjectCreateBody(baseDraft)).toMatchObject({ acquisition_strategy: 'random' })
    expect(buildProjectCreateBody({ ...baseDraft, acquisitionStrategy: 'active_learning' })).toMatchObject({
      acquisition_strategy: 'active_learning',
      dataset_layout: 'split',
    })
  })
})

describe('buildPolicyBody', () => {
  it('uses the closed interim policy contract in single mode', () => {
    expect(buildPolicyBody(baseDraft, members, 1)).toEqual({
      mode: 'single',
      annotator_ids: [],
      required_consensus_annotations: null,
      required_consensus_reviewers: null,
      resolver: null,
      parameters: {},
      review_thresholds: {},
      require_independent_adjudicator: false,
      version: 1,
    })
  })

  it('sends resolved IDs, the pipeline, and its typed configuration in consensus mode', () => {
    const configuration = {
      parameters: { class_strategy: { strategy: 'dirichlet_vote', alpha: 0.5, minimum_posterior: 0.9 }, matching_iou: 0.5, box_refinement: { strategy: 'coordinate_median' } },
      review_thresholds: { minimum_support: { numerator: 3, denominator: 4 }, minimum_median_iou: 0.5 },
    }
    const draft: ProjectDraft = {
      ...baseDraft,
      annotationPolicy: {
        mode: 'consensus',
        annotatorUsernames: ['ana', 'bruno'],
        requiredAnnotations: 2,
        requiredReviewers: 1,
        resolver: 'two_stage_detection_consensus',
        configuration,
        requireIndependentAdjudicator: true,
      },
    }

    expect(buildPolicyBody(draft, members, 3)).toEqual({
      mode: 'consensus',
      annotator_ids: ['id-ana', 'id-bruno'],
      required_consensus_annotations: 2,
      required_consensus_reviewers: 1,
      resolver: 'two_stage_detection_consensus',
      parameters: configuration.parameters,
      review_thresholds: configuration.review_thresholds,
      require_independent_adjudicator: true,
      version: 3,
    })
  })

  it('always carries the version the caller believes is current', () => {
    expect(buildPolicyBody(baseDraft, members, 7).version).toBe(7)
  })
})
