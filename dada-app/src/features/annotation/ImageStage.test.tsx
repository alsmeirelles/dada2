import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { stubResizeObserver } from '../consensus/consensus-fixtures'
import { ImageStage } from './ImageStage'

const STAGE = { width: 1000, height: 600 }

beforeEach(() => {
  stubResizeObserver()
  for (const [property, size] of [['clientWidth', STAGE.width], ['clientHeight', STAGE.height]] as const) {
    Object.defineProperty(HTMLElement.prototype, property, {
      configurable: true,
      get() { return (this as HTMLElement).classList.contains('image-stage') ? size : 0 },
    })
  }
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  Reflect.deleteProperty(HTMLElement.prototype, 'clientWidth')
  Reflect.deleteProperty(HTMLElement.prototype, 'clientHeight')
})

function renderStage(width: number, height: number) {
  render(<ImageStage
    media={{ id: 'm1', relative_path: 'frame.png', width, height, image_url: 'http://localhost/frame.png' }}
    document={{ media_id: 'm1', task_type: 'detection', version: 1, objects: [] }}
    classes={[]}
    tool="select"
    selectedClassId={null}
    selectedObjectId={null}
    locked={false}
    onChange={() => undefined}
    onSelectObject={() => undefined}
    onNotice={() => undefined}
  />)
  return () => (document.querySelector('.image-layer') as HTMLElement).style.transform
}

describe('I7-04: image position in the annotation canvas', () => {
  it('opens the image centred across the full canvas width', () => {
    const transform = renderStage(2000, 1000)

    expect(transform()).toBe('translate(0px, 50px) scale(0.5)')
  })

  it('zooms with the buttons around the canvas centre, so the image stays in place', () => {
    const transform = renderStage(2000, 1000)

    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))

    expect(transform()).toBe('translate(-100px, 0px) scale(0.6)')
  })

  it('fits the whole image on request', () => {
    const transform = renderStage(500, 1000)
    expect(transform()).toBe('translate(0px, -700px) scale(2)')

    fireEvent.click(screen.getByRole('button', { name: 'Fit image' }))

    expect(transform()).toBe('translate(350px, 0px) scale(0.6)')
  })
})
