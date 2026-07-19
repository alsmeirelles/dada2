import { describe, expect, it } from 'vitest'

import { parseEnv } from './env'

describe('parseEnv', () => {
  it('normalizes a valid API URL and applies upload defaults', () => {
    expect(parseEnv({ VITE_API_BASE_URL: 'https://api.example.test/' })).toEqual({
      apiBaseUrl: 'https://api.example.test',
      realtimeUrl: undefined,
      uploadChunkBytes: 8_388_608,
    })
  })

  it('rejects an invalid API URL', () => {
    expect(() => parseEnv({ VITE_API_BASE_URL: 'api-host' })).toThrow(
      'Invalid application configuration',
    )
  })
})
