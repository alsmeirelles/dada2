import { describe, expect, it } from 'vitest'

import { insideRegion, readDraft, submittableEvidence } from './review-draft'

const box = { type: 'rectangle' as const, coordinates: [12, 12, 10, 10] as [number, number, number, number] }

describe('review evidence', () => {
  it('builds the exact image-case evidence', () => {
    expect(submittableEvidence('image', { class_ids: ['a', 'b', 'a'] })).toEqual({ evidence: { class_ids: ['a', 'b'] } })
    expect(submittableEvidence('image', {})).toEqual({ problem: 'Choose at least one class for this image.' })
  })

  it('sends only the decision for no object, whatever the draft still holds', () => {
    expect(submittableEvidence('candidate', { decision: 'no_object', class_id: 'a', geometry: box })).toEqual({ evidence: { decision: 'no_object' } })
  })

  it('needs a decision, a class, and a drawing for an object', () => {
    expect(submittableEvidence('candidate', {})).toEqual({ problem: 'Say whether the region contains an object.' })
    expect(submittableEvidence('candidate', { decision: 'object' })).toEqual({ problem: 'Choose the object\'s class.' })
    expect(submittableEvidence('candidate', { decision: 'object', class_id: 'a' })).toEqual({ problem: 'Draw the object inside the region.' })
    expect(submittableEvidence('candidate', { decision: 'object', class_id: 'a', geometry: box })).toEqual({ evidence: { decision: 'object', class_id: 'a', geometry: box } })
  })

  it('keeps only the known parts of a free-form draft', () => {
    expect(readDraft({ decision: 'object', class_id: 'a', geometry: box, votes: 3 })).toEqual({ decision: 'object', class_id: 'a', geometry: box })
    expect(readDraft({ decision: 'maybe', geometry: { type: 'rectangle', coordinates: [1, 2] } })).toEqual({})
    expect(readDraft('nonsense')).toEqual({})
  })
})

describe('the review region', () => {
  const region: [number, number, number, number] = [10, 10, 30, 20]

  it('accepts a box or polygon wholly inside it', () => {
    expect(insideRegion(box, region)).toBe(true)
    expect(insideRegion({ type: 'polygon', coordinates: [[10, 10, 40, 10, 40, 30]] }, region)).toBe(true)
  })

  it('refuses a drawing that crosses its edge', () => {
    expect(insideRegion({ type: 'rectangle', coordinates: [35, 12, 10, 5] }, region)).toBe(false)
    expect(insideRegion({ type: 'polygon', coordinates: [[12, 12, 20, 12, 20, 31]] }, region)).toBe(false)
  })

  it('accepts anything when the case has no region', () => {
    expect(insideRegion({ type: 'rectangle', coordinates: [90, 90, 5, 5] }, null)).toBe(true)
  })
})
