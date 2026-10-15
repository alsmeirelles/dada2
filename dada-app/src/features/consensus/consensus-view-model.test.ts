import { describe, expect, it } from 'vitest'

import { batch, candidate, classes, evidence, polygon, run } from './consensus-fixtures'
import {
  candidateMetricRows,
  candidateRegions,
  classVoteRows,
  defaultBatchId,
  evidenceSources,
  formatAge,
  geometrySummary,
  queueMetricsSummary,
  reasonLabel,
  resolveLayout,
  settingsLines,
} from './consensus-view-model'

const classificationMetrics = {
  classes: {
    cat: { outcome: 'positive', passed: true, reasons: [], votes: { positive: 3, negative: 0 }, valid_votes: 3, support: { numerator: 3, denominator: 3 } },
    dog: { outcome: null, passed: false, reasons: ['class_tie'], votes: { positive: 1, negative: 1 }, valid_votes: 2, support: { numerator: 1, denominator: 2 } },
  },
}

describe('queue metrics summary', () => {
  it('counts undecided classes and the lowest support for classification', () => {
    expect(queueMetricsSummary(classificationMetrics, 'classification', classes)).toBe('1 of 2 classes need review · lowest support 1/2 (50%)')
  })

  it('shows the decision, support, and median IoU for detection', () => {
    expect(queueMetricsSummary(candidate().metrics, 'detection', classes)).toBe('Decision Cat · support 2/2 (100%) · median IoU 0.410')
  })

  it('names the matching metric for segmentation and a tie when no class won', () => {
    const metrics = { outcome: null, support: { numerator: 1, denominator: 2 }, median_overlap: 0.7, matching_metric: 'dice' }
    expect(queueMetricsSummary(metrics, 'segmentation', classes)).toBe('Decision tie, no unique winner · support 1/2 (50%) · median Dice 0.700')
  })

  it('says so when a failed run left no metrics', () => {
    expect(queueMetricsSummary({}, 'detection', classes)).toBe('No proposal metrics')
  })
})

describe('candidate metrics', () => {
  it('lists the detection keys the pipeline records, in reading order', () => {
    expect(candidateMetricRows(candidate(), 'detection', classes)).toEqual([
      { label: 'Decision', value: 'Cat' },
      { label: 'Votes', value: 'Cat 2' },
      { label: 'Valid votes', value: '2' },
      { label: 'Support', value: '2/2 (100%)' },
      { label: 'Margin', value: '2' },
      { label: 'Normalized entropy', value: '0' },
      { label: 'Decision rule', value: 'Supermajority' },
      { label: 'Median pairwise IoU', value: '0.410' },
      { label: 'Supporting boxes', value: '2' },
    ])
  })

  it('shows segmentation overlap, clean-up, and tracing diagnostics', () => {
    const rows = candidateMetricRows({
      metrics: {
        outcome: 'no_object', votes: { no_object: 2, cat: 1 }, median_overlap: 0.55, matching_metric: 'iou', supporting_masks: 3,
        area: 410, refinement: { strategy: 'staple' },
        post_processing: { area_change: 0.25, topology_change: 0, material_change: true },
        polygonization: { outer_rings: 1, holes: 2, dropped_degenerate: 0 },
      },
    }, 'segmentation', classes)

    expect(rows).toEqual([
      { label: 'Decision', value: 'No object' },
      { label: 'Votes', value: 'No object 2 · Cat 1' },
      { label: 'Median pairwise IoU', value: '0.550' },
      { label: 'Supporting masks', value: '3' },
      { label: 'Mask area (pixels)', value: '410' },
      { label: 'Mask refinement', value: 'staple' },
      { label: 'Area change after clean-up', value: '0.250' },
      { label: 'Topology change after clean-up', value: '0' },
      { label: 'Material change', value: 'Yes' },
      { label: 'Traced outline', value: '1 outer rings · 2 holes · 0 degenerate rings dropped' },
    ])
  })

  it('turns classification votes into marked and not-marked counts per class', () => {
    expect(classVoteRows({ metrics: classificationMetrics }, classes)).toEqual([
      { classId: 'cat', name: 'Cat', marked: 3, notMarked: 0, validVotes: 3, support: '3/3 (100%)', share: 1, outcome: 'Present', passed: true, reasons: [], posterior: null },
      { classId: 'dog', name: 'Dog', marked: 1, notMarked: 1, validVotes: 2, support: '1/2 (50%)', share: 0.5, outcome: 'Tie', passed: false, reasons: ['class_tie'], posterior: null },
    ])
  })
})

describe('evidence sources', () => {
  it('orders the proposal and resolution first and gives every source a distinct colour and pattern', () => {
    const many = Array.from({ length: 8 }, (_, index) => ({
      ...evidence().submissions[0]!, id: `s${index}`, annotator_name: `Rater ${index}`, current_generation: index < 7,
    }))
    const sources = evidenceSources(evidence({
      submissions: many,
      resolutions: [{ id: 'r1', version: 1, source: 'automatic_consensus', objects: [], content_hash: 'h', accepted_by: null, run_id: 'run-1', created_at: '2026-10-14T10:00:00Z', superseded_at: null }],
    }))

    expect(sources.map((source) => source.kind).slice(0, 3)).toEqual(['proposal', 'resolution', 'submission'])
    expect(new Set(sources.map((source) => `${source.color}|${source.dash}`)).size).toBe(sources.length)
    expect(sources.every((source) => source.pattern)).toBe(true)
    expect(sources.at(-1)).toMatchObject({ label: 'Rater 7, submission revision 1', defaultVisible: false, detail: 'Earlier evidence generation' })
  })

  it('keeps a submission style when the proposal changes', () => {
    const before = evidenceSources(evidence()).find((source) => source.id === 'submission:s2')
    const after = evidenceSources(evidence({ runs: [run(), run({ id: 'run-2', sequence: 2 })] })).find((source) => source.id === 'submission:s2')

    expect(after?.color).toBe(before?.color)
    expect(after?.dash).toBe(before?.dash)
  })

  it('labels every candidate region with its result', () => {
    expect(candidateRegions(run().proposal).map((region) => region.label)).toEqual(['Object 1 needs review', 'Object 2 passed'])
  })
})

describe('evidence layout', () => {
  it('overlays up to four sources on a wide screen', () => {
    expect(resolveLayout(null, 1400, 4)).toBe('overlay')
  })

  it('goes side by side on a narrow screen or above four sources', () => {
    expect(resolveLayout(null, 1199, 2)).toBe('side-by-side')
    expect(resolveLayout(null, 1600, 5)).toBe('side-by-side')
  })

  it('keeps an explicit choice', () => {
    expect(resolveLayout('overlay', 800, 6)).toBe('overlay')
  })
})

describe('formatting', () => {
  it('describes geometry without colour', () => {
    expect(geometrySummary(polygon('p', 'cat', [0, 0, 10, 0, 10, 10]))).toBe('Polygon, 1 ring, 3 points')
    expect(geometrySummary({ geometry: { type: 'rectangle', coordinates: [1.4, 2.6, 10, 20] } })).toBe('Box at 1, 3, 10 × 20 px')
    expect(geometrySummary({ geometry: null })).toBe('Image label')
  })

  it('renders ages and reasons in plain words', () => {
    const now = new Date('2026-10-14T12:00:00Z').getTime()
    expect(formatAge('2026-10-14T11:55:00Z', now)).toBe('5 min')
    expect(formatAge('2026-10-12T12:00:00Z', now)).toBe('2 d')
    expect(reasonLabel('worker_failed')).toBe('Resolver run failed')
  })

  it('flattens a run configuration into readable lines', () => {
    expect(settingsLines(run().configuration)).toEqual([
      { label: 'Parameters · class strategy · strategy', value: 'categorical_vote' },
      { label: 'Parameters · class strategy · decision rule', value: 'supermajority' },
      { label: 'Parameters · matching iou', value: '0.500' },
      { label: 'Review thresholds · minimum support', value: '2/3 (67%)' },
      { label: 'Review thresholds · minimum median iou', value: '0.500' },
    ])
  })
})

describe('default batch', () => {
  it('prefers a consensus batch with cases waiting, then the first started one', () => {
    const single = batch({ id: 'single', mode: 'single', review_required_items: 3 })
    const quiet = batch({ id: 'quiet', review_required_items: 0 })
    const busy = batch({ id: 'busy', review_required_items: 2 })
    const preparing = batch({ id: 'preparing', status: 'preparing', review_required_items: 0 })

    expect(defaultBatchId([single, preparing, quiet, busy])).toBe('busy')
    expect(defaultBatchId([single, preparing, quiet])).toBe('quiet')
    expect(defaultBatchId([single, preparing])).toBeNull()
  })
})
