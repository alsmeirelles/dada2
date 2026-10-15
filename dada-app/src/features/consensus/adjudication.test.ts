import { describe, expect, it } from 'vitest'

import {
  acceptRequest,
  draftChanged,
  editRequest,
  leaseState,
  proposalObjects,
  rationaleReasons,
  rationaleRule,
  startDraft,
  submissionObjects,
} from './adjudication'
import { box, evidence, lease, run, workItem } from './consensus-fixtures'

const plain = { contributor: false, overridingExpert: false }

describe('rationale rules', () => {
  it('makes a note optional only for a plain acceptance', () => {
    expect(rationaleRule('accept_proposal', plain)).toBe('optional')
    expect(rationaleRule('edit_proposal', plain)).toBe('required')
    expect(rationaleRule('edit_submission', plain)).toBe('required')
    expect(rationaleRule('replace', plain)).toBe('required')
  })

  it('requires a rationale to accept as a contributor or over an expert decision', () => {
    expect(rationaleRule('accept_proposal', { contributor: true, overridingExpert: false })).toBe('required')
    expect(rationaleRule('accept_proposal', { contributor: false, overridingExpert: true })).toBe('required')
    expect(rationaleReasons('accept_proposal', { contributor: true, overridingExpert: true })).toHaveLength(2)
  })
})

describe('starting documents', () => {
  it('starts a candidate edit from the candidate only, not the whole proposal', () => {
    const draft = startDraft(evidence(), workItem(), { kind: 'proposal' })

    expect(draft).toMatchObject({ action: 'edit_proposal', sourceSubmissionId: null, objects: [box('c-1', 'cat', [10, 10, 21, 21])] })
    expect(draft.base).toEqual(evidence().versions)
  })

  it('takes only a submission’s member objects for a candidate case', () => {
    expect(submissionObjects(evidence(), workItem(), 's1')).toEqual([box('a1', 'cat', [10, 10, 20, 20])])
    expect(startDraft(evidence(), workItem(), { kind: 'submission', submissionId: 's1' })).toMatchObject({ action: 'edit_submission', sourceSubmissionId: 's1' })
  })

  it('takes the whole submission for an image case and nothing for a replacement', () => {
    const image = workItem({ id: 'w2', scope: 'image', candidate_key: 'image' })

    expect(submissionObjects(evidence(), image, 's1')).toHaveLength(2)
    expect(startDraft(evidence(), image, { kind: 'blank' })).toMatchObject({ action: 'replace', objects: [] })
  })

  it('accepts the whole proposal for an image case without a candidate and nothing after a failed run', () => {
    const image = workItem({ scope: 'image', candidate_key: 'image' })
    expect(proposalObjects(evidence(), image)).toEqual(run().proposal!.objects)
    expect(proposalObjects(evidence({ runs: [run({ proposal: null, status: 'failed' })] }), image)).toBeNull()
  })
})

describe('requests', () => {
  it('sends the draft base versions and its source', () => {
    const draft = { ...startDraft(evidence(), workItem(), { kind: 'submission', submissionId: 's2' }), objects: [] }

    expect(editRequest(draft, 'Nothing is there.')).toEqual({
      expected_evidence_generation: 1, expected_configuration_fingerprint: 'cfg-1', expected_resolution_version: 0,
      action: 'edit_submission', objects: [], source_submission_id: 's2', rationale: 'Nothing is there.',
    })
    expect(draftChanged(draft)).toBe(true)
  })

  it('omits an empty acceptance note', () => {
    expect(acceptRequest(evidence().versions, '  ')).not.toHaveProperty('rationale')
    expect(acceptRequest(evidence().versions, 'Checked')).toMatchObject({ action: 'accept_proposal', rationale: 'Checked' })
  })
})

describe('lease state', () => {
  it('ignores an expired lease and distinguishes the caller from another holder', () => {
    const now = Date.now()
    expect(leaseState(lease({ expires_at: new Date(now - 1).toISOString() }), 'manager', now)).toEqual({ kind: 'free' })
    expect(leaseState(lease(), 'manager', now).kind).toBe('mine')
    expect(leaseState(lease({ holder_id: 'other' }), 'manager', now).kind).toBe('other')
  })
})
