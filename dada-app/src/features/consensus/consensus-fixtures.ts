import { vi } from 'vitest'

import type { User } from '../../api/types'
import type { AnnotationObject } from '../annotation/types'
import type { AnnotationBatch, ProjectClassInput } from '../projects/types'
import type { CandidateDecision, ImageEvidence, LeaseView, RunView, WorkItemView } from './consensus-types'

export const classes: ProjectClassInput[] = [
  { id: 'cat', name: 'Cat', color: '#ff0000' },
  { id: 'dog', name: 'Dog', color: '#00ff00' },
]

export const manager: User = {
  id: 'manager', username: 'mia', display_name: 'Mia', is_administrator: false, is_active: true, version: 1,
  created_at: '2026-10-01T12:00:00Z',
}

export function box(id: string, classId: string, coordinates: [number, number, number, number]): AnnotationObject {
  return { id, class_id: classId, geometry: { type: 'rectangle', coordinates }, attributes: {} }
}

export function polygon(id: string, classId: string, ring: number[]): AnnotationObject {
  return { id, class_id: classId, geometry: { type: 'polygon', coordinates: [ring] }, attributes: {} }
}

export function candidate(overrides: Partial<CandidateDecision> = {}): CandidateDecision {
  return {
    key: 'c-1', ordinal: 0, scope: 'candidate', passed: false, reasons: ['geometry_below_threshold'],
    objects: [box('c-1', 'cat', [10, 10, 21, 21])],
    region: [8, 8, 26, 26],
    members: [
      { source_id: 's1', object_id: 'a1', annotator_index: 0, class_id: 'cat' },
      { source_id: 's2', object_id: 'b1', annotator_index: 1, class_id: 'cat' },
    ],
    metrics: {
      outcome: 'cat', votes: { cat: 2, dog: 0, no_object: 0 }, valid_votes: 2, support: { numerator: 2, denominator: 2 },
      margin: 2, normalized_entropy: 0, decision_rule: 'supermajority', median_iou: 0.41, supporting_boxes: 2,
    },
    ...overrides,
  }
}

export function run(overrides: Partial<RunView> = {}): RunView {
  return {
    id: 'run-1', sequence: 1, trigger: 'initial', status: 'review_required',
    pipeline: 'two_stage_detection_consensus', pipeline_version: '1.0.0',
    configuration: {
      parameters: { class_strategy: { strategy: 'categorical_vote', decision_rule: 'supermajority' }, matching_iou: 0.5 },
      review_thresholds: { minimum_support: { numerator: 2, denominator: 3 }, minimum_median_iou: 0.5 },
    },
    configuration_fingerprint: 'cfg-1', input_fingerprint: 'input-1', dependency_versions: { scipy: '1.14.1' },
    attempt: 1, failure_code: null, failure_detail: null, requested_by: null,
    created_at: '2026-10-14T10:00:00Z', started_at: '2026-10-14T10:00:01Z', finished_at: '2026-10-14T10:00:02Z',
    proposal: {
      id: 'proposal-1', outcome: 'review_required', objects: [box('c-2', 'dog', [50, 40, 10, 10])],
      candidates: [candidate(), candidate({
        key: 'c-2', ordinal: 1, passed: true, reasons: [], objects: [box('c-2', 'dog', [50, 40, 10, 10])],
        region: [49, 39, 12, 12], members: [], metrics: { outcome: 'dog', median_iou: 0.9 },
      })],
      diagnostics: {}, content_hash: 'hash-1', created_at: '2026-10-14T10:00:02Z',
    },
    ...overrides,
  }
}

export function workItem(overrides: Partial<WorkItemView> = {}): WorkItemView {
  return {
    id: 'w1', candidate_key: 'c-1', candidate_ordinal: 0, scope: 'candidate', status: 'review_required',
    reason: 'geometry_below_threshold', candidate_context: { region: [8, 8, 26, 26] }, run_id: 'run-1',
    reviews_submitted: 0, reviews_required: 0, lease: null, adjudications: [],
    created_at: '2026-10-14T10:00:02Z', closed_at: null,
    ...overrides,
  }
}

export function evidence(overrides: Partial<ImageEvidence> = {}): ImageEvidence {
  return {
    batch_item_id: 'item-1', batch_id: 'batch-1', purpose: 'test', status: 'review_required', task_type: 'detection',
    media: { id: 'media-1', relative_path: 'frames/a.png', width: 100, height: 80, image_url: 'http://localhost:8000/img' },
    versions: { evidence_generation: 1, configuration_fingerprint: 'cfg-1', resolution_version: 0 },
    require_independent_adjudicator: false,
    contributors: ['ana', 'bruno'],
    submissions: [
      { id: 's1', assignment_id: 'as1', annotator_id: 'ana', annotator_name: 'Ana', revision: 1, content_hash: 'h1', objects: [box('a1', 'cat', [10, 10, 20, 20]), box('a2', 'dog', [50, 40, 10, 10])], submitted_at: '2026-10-14T09:00:00Z', current_generation: true },
      { id: 's2', assignment_id: 'as2', annotator_id: 'bruno', annotator_name: 'Bruno', revision: 1, content_hash: 'h2', objects: [box('b1', 'cat', [12, 12, 22, 22])], submitted_at: '2026-10-14T09:10:00Z', current_generation: true },
    ],
    reviews: [],
    runs: [run()],
    resolutions: [],
    work_items: [workItem()],
    ...overrides,
  }
}

export function lease(overrides: Partial<LeaseView> = {}): LeaseView {
  return {
    work_item_id: 'w1', holder_id: 'manager', acquired_at: '2026-10-14T10:05:00Z', renewed_at: '2026-10-14T10:05:00Z',
    expires_at: '2099-10-14T10:20:00Z', cap_at: '2099-10-14T12:05:00Z',
    ...overrides,
  }
}

export function batch(overrides: Partial<AnnotationBatch> = {}): AnnotationBatch {
  return {
    id: 'batch-1', project_id: 'p1', purpose: 'test', status: 'review_required', mode: 'consensus', annotator_ids: [],
    required_consensus_annotations: 2, required_consensus_reviewers: 1, resolver: 'two_stage_detection_consensus',
    resolver_version: '1.0.0', parameters: {}, review_thresholds: {}, require_independent_adjudicator: false,
    source_policy_version: 1, selection_strategy: 'random', selection_seed: 1, selection_input_fingerprint: 'f',
    requested_size: 2, total_items: 2, resolved_items: 0, awaiting_resolution_items: 0, resolving_items: 0,
    in_review_items: 0, review_required_items: 1, cancelled_items: 0, total_assignments: 4, available_assignments: 0,
    in_progress_assignments: 0, submitted_assignments: 4, started_at: '2026-10-14T08:00:00Z',
    created_at: '2026-10-14T08:00:00Z', updated_at: '2026-10-14T08:00:00Z',
    ...overrides,
  }
}

export type Route = (request: { method: string; path: string; search: URLSearchParams; body: unknown }) => Response | undefined

export function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } })
}

export function apiError(status: number, code: string, message = code) {
  return json({ error: { code, message, details: {}, trace_id: `trace-${code}` } }, status)
}

/** Stubs `fetch` with the first route that answers; an unanswered request fails the test loudly. */
export function stubApi(route: Route) {
  const fetch = vi.fn().mockImplementation((input: string, init?: RequestInit) => {
    const url = new URL(String(input))
    const response = route({
      method: init?.method ?? 'GET',
      path: url.pathname,
      search: url.searchParams,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    })
    if (!response) throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url.pathname}`)
    return Promise.resolve(response)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

export function stubResizeObserver() {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  })
}
