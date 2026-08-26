import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearSetup,
  loadSetup,
  saveSetup,
  stageIndex,
} from './setup-recovery'

describe('project setup recovery', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('returns null when no setup is in flight', () => {
    expect(loadSetup()).toBeNull()
  })

  it('round-trips a snapshot', () => {
    saveSetup({ projectId: 'project-1', stage: 'members' })
    expect(loadSetup()).toEqual({ projectId: 'project-1', stage: 'members' })
  })

  it('discards a snapshot with an unknown stage', () => {
    sessionStorage.setItem(
      'dada.project-setup',
      JSON.stringify({ projectId: 'project-1', stage: 'teleported' }),
    )
    expect(loadSetup()).toBeNull()
  })

  it('discards a snapshot without a project id', () => {
    sessionStorage.setItem('dada.project-setup', JSON.stringify({ stage: 'created' }))
    expect(loadSetup()).toBeNull()
  })

  it('discards unreadable content', () => {
    sessionStorage.setItem('dada.project-setup', 'not json')
    expect(loadSetup()).toBeNull()
  })

  it('clears a finished setup', () => {
    saveSetup({ projectId: 'project-1', stage: 'activated' })
    clearSetup()
    expect(loadSetup()).toBeNull()
  })

  it('orders stages so completed work is skipped', () => {
    expect(stageIndex('created')).toBeLessThan(stageIndex('classes'))
    expect(stageIndex('policy')).toBeLessThan(stageIndex('uploaded'))
    expect(stageIndex('activated')).toBeGreaterThan(stageIndex('uploaded'))
  })
})
