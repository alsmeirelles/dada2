import { describe, expect, it } from 'vitest'

import { findDuplicateGroups, scanImageFiles, type LocalImage } from './ingest'

function fileAt(path: string, content: string, type: string) {
  const file = new File([content], path.split('/').at(-1)!, { type })
  Object.defineProperty(file, 'webkitRelativePath', { value: path })
  return file
}

describe('scanImageFiles', () => {
  it('keeps nested relative paths and filters hidden and unsupported files', () => {
    const result = scanImageFiles([
      fileAt('dataset/camera-a/frame.jpg', 'image', 'image/jpeg'),
      fileAt('dataset/.cache/thumb.png', 'image', 'image/png'),
      fileAt('dataset/notes.txt', 'notes', 'text/plain'),
    ])

    expect(result.images).toHaveLength(1)
    expect(result.images[0]?.relativePath).toBe('camera-a/frame.jpg')
    expect(result.rejected.map((item) => item.reason)).toEqual(['hidden', 'unsupported'])
  })

  it('groups equal digests and sizes as duplicates', () => {
    const base = { file: new File(['x'], 'x.jpg'), mediaType: 'image/jpeg', sizeBytes: 1, sha256: 'abc' }
    const images: LocalImage[] = [
      { ...base, clientFileId: '1', relativePath: 'a/x.jpg' },
      { ...base, clientFileId: '2', relativePath: 'b/x.jpg' },
      { ...base, clientFileId: '3', relativePath: 'c/x.jpg', sha256: 'def' },
    ]
    expect(findDuplicateGroups(images)).toHaveLength(1)
    expect(findDuplicateGroups(images)[0]).toHaveLength(2)
  })
})
