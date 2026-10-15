import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiRequest } from '../../api/client'
import { detailErrorLines } from './error-details'

afterEach(() => vi.unstubAllGlobals())

describe('detailErrorLines', () => {
  it('reads validation and review error entries', () => {
    const error = new ApiError('The resolver settings are not valid for this pipeline.', 422, 'invalid_resolver_configuration', undefined, {
      errors: [
        { loc: ['parameters', 'matching_iou'], msg: 'Input should be less than or equal to 1' },
        { field: 'geometry', code: 'out_of_bounds' },
      ],
    })

    expect(detailErrorLines(error)).toEqual(['parameters.matching_iou: Input should be less than or equal to 1', 'geometry: out of bounds'])
  })

  it('names every missing prerequisite of an unavailable strategy', () => {
    const error = new ApiError('The project evidence cannot calibrate this strategy yet.', 422, 'resolver_unavailable', undefined, {
      strategy: 'dawid_skene',
      missing: [{ requirement: 'calibration_items', required: 50, found: 3 }],
    })

    expect(detailErrorLines(error)).toEqual(['Missing calibration items (required 50, found 3)'])
  })

  it('receives the details from the API error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'invalid_review_evidence', message: 'Invalid.', details: { errors: [{ field: 'class_ids', code: 'unknown_class' }] }, trace_id: 't1' },
    }), { status: 422, headers: { 'Content-Type': 'application/json' } })))

    const failure = await apiRequest('/x').catch((error: unknown) => error)

    expect(detailErrorLines(failure)).toEqual(['class_ids: unknown class'])
  })

  it('returns nothing when the error carries no details', () => {
    expect(detailErrorLines(new ApiError('Conflict', 409, 'version_conflict'))).toEqual([])
    expect(detailErrorLines(undefined)).toEqual([])
  })
})
