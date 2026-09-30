import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { importLabels, prepareDataset, readLabelFiles } from './dataset-api'
import { saveSetup } from './setup-recovery'

function selected(path: string, content: string) {
  const file = new File([content], path.split('/').pop()!)
  const bytes = new TextEncoder().encode(content)
  Object.defineProperty(file, 'webkitRelativePath', { value: path })
  // jsdom's File lacks the arrayBuffer() every supported browser provides.
  Object.defineProperty(file, 'arrayBuffer', { value: async () => bytes.buffer })
  return file
}

function mockJsonResponses(...payloads: unknown[]) {
  const fetch = vi.fn()
  for (const payload of payloads) {
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(payload), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
  }
  vi.stubGlobal('fetch', fetch)
  return fetch
}

beforeEach(() => sessionStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('label files', () => {
  it('keeps the format extension with paths relative to the selected folder', async () => {
    const labels = await readLabelFiles([
      selected('labels/camera-a/0001.txt', '0 0.5 0.5 0.1 0.1\n'),
      selected('labels/classes.yaml', 'names: [pothole]'),
    ], 'yolo_detection')

    expect(labels).toHaveLength(1)
    expect(labels[0]).toMatchObject({ relativePath: 'camera-a/0001.txt', sizeBytes: 18 })
    expect(labels[0]!.sha256).toMatch(/^[0-9a-f]{64}$/)
  })

  it('creates the import, sends each file whole, and validates it', async () => {
    const fetch = mockJsonResponses(
      { id: 'import-1' },
      {},
      { id: 'import-1', status: 'validated' },
    )
    const labels = await readLabelFiles([selected('labels/a.txt', '0 0.5 0.5 0.1 0.1\n')], 'yolo_detection')

    const result = await importLabels('project-1', 'yolo_detection', labels, 'token')

    expect(result.status).toBe('validated')
    const [create, upload, validate] = fetch.mock.calls
    expect(create![0]).toMatch(/\/projects\/project-1\/annotation-imports$/)
    expect(JSON.parse(create![1].body)).toEqual({
      format: 'yolo_detection',
      files: [{
        client_file_id: labels[0]!.clientFileId,
        relative_path: 'a.txt',
        size_bytes: labels[0]!.sizeBytes,
        sha256: labels[0]!.sha256,
      }],
    })
    expect(upload![0]).toMatch(new RegExp(`/annotation-imports/import-1/files/${labels[0]!.clientFileId}$`))
    expect(upload![1].body).toBe(labels[0]!.file)
    expect(validate![0]).toMatch(/\/annotation-imports\/import-1\/validate$/)
  })
})

describe('dataset preparation', () => {
  it('reuses the setup key so a lost response replays instead of failing', async () => {
    saveSetup({ projectId: 'project-1', stage: 'uploaded' })
    const fetch = mockJsonResponses({}, {})

    await prepareDataset('project-1', 'token')
    await prepareDataset('project-1', 'token')

    const keys = fetch.mock.calls.map((call) => call[1].headers['Idempotency-Key'])
    expect(keys[0]).toBeTruthy()
    expect(keys[1]).toBe(keys[0])
  })
})
