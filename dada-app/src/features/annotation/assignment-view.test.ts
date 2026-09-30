import { describe, expect, it } from 'vitest'

import { submissionKey } from './annotation-api'
import { filterAssignments, isEditable, neighbor, openWork, validateDocument } from './assignment-view'
import type { AnnotationDocument, AssignmentDetail, AssignmentQueueItem } from './types'

function item(id: string, overrides: Partial<AssignmentQueueItem> = {}): AssignmentQueueItem {
  return {
    id, batch_id: 'batch-1', batch_purpose: 'test', media_id: `media-${id}`, relative_path: `${id}.png`,
    width: 100, height: 80, status: 'pending', version: 1, seeded_from_import: false, updated_at: '2026-09-30T12:00:00Z',
    ...overrides,
  }
}

function detail(overrides: Partial<AssignmentDetail> = {}): AssignmentDetail {
  return {
    id: 'assignment-1', project_id: 'project-1', batch_id: 'batch-1', batch_purpose: 'test', task_type: 'detection',
    status: 'in_progress', version: 3, objects: [], seeded_from_import: false, draft_saved_at: null, revision: null,
    submitted_at: null, media: { id: 'media-1', relative_path: 'a.png', width: 100, height: 80, image_url: 'http://api/a' },
    ...overrides,
  }
}

const box = { id: 'box-1', class_id: 'class-1', geometry: { type: 'rectangle' as const, coordinates: [1, 2, 3, 4] as [number, number, number, number] }, attributes: {} }

describe('assignment queue view', () => {
  it('lists every one of the caller\'s assignments whatever peers are doing', () => {
    const items = [item('a'), item('b', { status: 'in_progress' }), item('c', { status: 'submitted' })]

    expect(filterAssignments(items, 'all', 'all')).toEqual(items)
    expect(filterAssignments(items, 'all', 'submitted').map((entry) => entry.id)).toEqual(['c'])
    expect(filterAssignments([...items, item('d', { batch_purpose: 'validation' })], 'validation', 'all').map((entry) => entry.id)).toEqual(['d'])
  })

  it('walks the visible list and stops at both ends', () => {
    const items = [item('a'), item('b'), item('c')]

    expect(neighbor(items, null, 1)?.id).toBe('a')
    expect(neighbor(items, 'b', 1)?.id).toBe('c')
    expect(neighbor(items, 'c', 1)?.id).toBe('c')
    expect(neighbor(items, 'a', -1)?.id).toBe('a')
  })

  it('only open work is editable', () => {
    expect(isEditable('pending')).toBe(true)
    expect(isEditable('in_progress')).toBe(true)
    expect(['submitted', 'reassigned', 'cancelled'].map((status) => isEditable(status as never))).toEqual([false, false, false])
  })
})

describe('opening an assignment', () => {
  const local = (baseVersion: number): { savedAt: number; baseVersion: number; document: AnnotationDocument } => ({
    savedAt: 1_000, baseVersion, document: { media_id: 'media-1', task_type: 'detection', version: baseVersion, objects: [box] },
  })

  it('restores local work built on the current server version', () => {
    const opened = openWork(detail(), local(3))

    expect(opened.document.objects).toEqual([box])
    expect(opened.dirty).toBe(true)
    expect(opened.conflict).toBeNull()
  })

  it('asks which version to keep when the server moved on', () => {
    const opened = openWork(detail({ version: 4 }), local(3))

    expect(opened.document.objects).toEqual([])
    expect(opened.document.version).toBe(4)
    expect(opened.conflict?.baseVersion).toBe(3)
  })

  it('never presents local work as a submission', () => {
    const opened = openWork(detail({ status: 'submitted', objects: [] }), local(3))

    expect(opened.document.objects).toEqual([])
    expect(opened.dirty).toBe(false)
    expect(opened.notice).toBe('Submission received. This image is read-only.')
  })

  it('explains a manager reassignment and keeps local work in the browser', () => {
    expect(openWork(detail({ status: 'reassigned' }), local(3)).notice).toBe(
      'A manager reassigned this image to another annotator. Your unsaved work stays in this browser.',
    )
  })

  it('says seeded work begins from imported labels but belongs to the annotator', () => {
    expect(openWork(detail({ status: 'pending', seeded_from_import: true, objects: [box] }), null).notice).toBe(
      'This image starts from imported labels. What you save and submit is your own work.',
    )
  })
})

describe('submission', () => {
  it('allows an explicitly empty detection image but not an empty classification', () => {
    expect(validateDocument({ media_id: 'm', task_type: 'detection', version: 1, objects: [] })).toBe('')
    expect(validateDocument({ media_id: 'm', task_type: 'classification', version: 1, objects: [] })).toBe(
      'Choose at least one class before submitting.',
    )
  })

  it('uses one idempotency key per assignment version', () => {
    expect(submissionKey('assignment-1', 3)).toBe('submit:assignment-1:3')
    expect(submissionKey('assignment-1', 4)).not.toBe(submissionKey('assignment-1', 3))
  })
})
