import { describe, expect, it } from 'vitest'

import { findDuplicateGroups, mergeSelections, scanImageFiles, type LocalImage } from './ingest'

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

  it('uses the file name as the path of individually chosen files', () => {
    const loose = new File(['image'], 'frame.png', { type: 'image/png' })

    expect(scanImageFiles([loose]).images[0]?.relativePath).toBe('frame.png')
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

describe('mergeSelections', () => {
  it('adds a second folder to the first and skips a path already taken', () => {
    const first = scanImageFiles([
      fileAt('north/0001.jpg', 'a', 'image/jpeg'),
      fileAt('north/day/0002.jpg', 'b', 'image/jpeg'),
    ]).images
    const second = scanImageFiles([
      fileAt('south/0001.jpg', 'c', 'image/jpeg'),
      fileAt('south/0003.jpg', 'd', 'image/jpeg'),
    ]).images

    const merged = mergeSelections(first, second)

    expect(merged.images.map((image) => image.relativePath)).toEqual(['0001.jpg', 'day/0002.jpg', '0003.jpg'])
    expect(merged.rejected).toEqual([{ relativePath: '0001.jpg', reason: 'duplicate_path' }])
  })
})
