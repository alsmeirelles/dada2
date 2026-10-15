import { beforeEach, describe, expect, it } from 'vitest'

import {
  REVIEW_RECOVERY_TTL_MS,
  clearReviewRecovery,
  loadReviewRecovery,
  openReview,
  saveReviewRecovery,
} from './review-recovery'
import type { ReviewAssignmentDetail } from './review-types'

function detail(overrides: Partial<ReviewAssignmentDetail> = {}): ReviewAssignmentDetail {
  return {
    id: 'review-1', project_id: 'project-1', work_item_id: 'work-1', source_input_id: 'input-1',
    candidate_key: 'c-1', candidate_ordinal: 0, scope: 'candidate', status: 'in_progress', version: 3,
    media: { id: 'media-1', relative_path: 'a.png', width: 100, height: 80, image_url: 'http://api/a' },
    candidate_context: { region: [10, 10, 30, 20] }, evidence: {}, draft_saved_at: null, submitted_at: null,
    ...overrides,
  }
}

beforeEach(() => sessionStorage.clear())

describe('review recovery', () => {
  it('keys local work by project, review, and base version', () => {
    saveReviewRecovery('project-1', 'review-1', 3, { decision: 'no_object' }, 1_000)

    expect(sessionStorage.getItem('dada.review-recovery:project-1:review-1:3')).not.toBeNull()
    expect(loadReviewRecovery('project-1', 'review-1', 2_000)).toEqual({ savedAt: 1_000, baseVersion: 3, evidence: { decision: 'no_object' } })
  })

  it('keeps one snapshot per review and never mixes two reviews of the same image', () => {
    saveReviewRecovery('project-1', 'review-1', 3, { decision: 'no_object' })
    saveReviewRecovery('project-1', 'review-1', 4, { decision: 'object', class_id: 'class-1' })
    saveReviewRecovery('project-1', 'review-2', 1, { class_ids: ['class-2'] })

    expect(sessionStorage.getItem('dada.review-recovery:project-1:review-1:3')).toBeNull()
    expect(loadReviewRecovery('project-1', 'review-1')?.evidence).toEqual({ decision: 'object', class_id: 'class-1' })
    expect(loadReviewRecovery('project-1', 'review-2')?.evidence).toEqual({ class_ids: ['class-2'] })
    clearReviewRecovery('project-1', 'review-1')
    expect(loadReviewRecovery('project-1', 'review-1')).toBeNull()
    expect(loadReviewRecovery('project-1', 'review-2')).not.toBeNull()
  })

  it('drops expired and unreadable snapshots', () => {
    saveReviewRecovery('project-1', 'review-1', 3, { decision: 'no_object' }, 0)
    expect(loadReviewRecovery('project-1', 'review-1', REVIEW_RECOVERY_TTL_MS + 1)).toBeNull()

    sessionStorage.setItem('dada.review-recovery:project-1:review-1:3', 'not json')
    expect(loadReviewRecovery('project-1', 'review-1')).toBeNull()
  })

  it('no longer reads the unversioned localStorage key', () => {
    localStorage.setItem('dada:candidate-review:project-1:review-1', '{"decision":"no_object"}')
    expect(loadReviewRecovery('project-1', 'review-1')).toBeNull()
    localStorage.clear()
  })
})

describe('opening a review', () => {
  it('restores local work built on the current version', () => {
    const opened = openReview(detail(), { savedAt: 0, baseVersion: 3, evidence: { decision: 'no_object' } })
    expect(opened).toMatchObject({ evidence: { decision: 'no_object' }, dirty: true, conflict: null })
  })

  it('keeps older local work aside as a conflict and shows the server draft', () => {
    const local = { savedAt: 0, baseVersion: 2, evidence: { decision: 'no_object' as const } }
    const opened = openReview(detail({ evidence: { decision: 'object', class_id: 'class-1' } }), local)

    expect(opened.evidence).toEqual({ decision: 'object', class_id: 'class-1' })
    expect(opened.conflict).toBe(local)
  })

  it('shows a submitted review read-only from the server', () => {
    const opened = openReview(detail({ status: 'submitted', evidence: { decision: 'no_object' } }), { savedAt: 0, baseVersion: 3, evidence: { decision: 'object' } })
    expect(opened).toMatchObject({ evidence: { decision: 'no_object' }, conflict: null, notice: 'Review submitted. It is read-only.' })
  })
})
