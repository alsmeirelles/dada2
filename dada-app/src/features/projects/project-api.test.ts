import { describe, expect, it } from 'vitest'

import { buildPolicyBody, resolveAnnotatorIds, type ProjectMember } from './project-api'
import type { ProjectDraft } from './types'

const members: ProjectMember[] = [
  { user_id: 'id-owner', username: 'owner', display_name: 'Owner', role: 'owner' },
  { user_id: 'id-ana', username: 'ana', display_name: 'Ana', role: 'annotator' },
  { user_id: 'id-bruno', username: 'bruno', display_name: 'Bruno', role: 'annotator' },
]

const baseDraft: ProjectDraft = {
  name: 'Road defects',
  description: '',
  taskType: 'detection',
  classes: [],
  initialTrainingSize: 10,
  testSetSize: 5,
  iterationBatchSize: 5,
  collaborators: ['ana', 'bruno'],
  annotationPolicy: { mode: 'single' },
}

describe('resolveAnnotatorIds', () => {
  it('maps usernames to persisted member IDs in order', () => {
    expect(resolveAnnotatorIds(members, ['bruno', 'ana'])).toEqual([
      'id-bruno',
      'id-ana',
    ])
  })

  it('resolves the owner, who may annotate', () => {
    expect(resolveAnnotatorIds(members, ['owner'])).toEqual(['id-owner'])
  })

  it('refuses a username that is not a member', () => {
    expect(() => resolveAnnotatorIds(members, ['ghost'])).toThrow(
      'ghost is not a project member.',
    )
  })
})

describe('buildPolicyBody', () => {
  it('uses the closed interim policy contract in single mode', () => {
    expect(buildPolicyBody(baseDraft, members, 1)).toEqual({
      mode: 'single',
      annotator_ids: [],
      resolver: null,
      parameters: {},
      review_thresholds: {},
      version: 1,
    })
  })

  it('sends resolved IDs, resolver, and thresholds in consensus mode', () => {
    const draft: ProjectDraft = {
      ...baseDraft,
      annotationPolicy: {
        mode: 'consensus',
        annotatorUsernames: ['ana', 'bruno'],
        resolver: 'two_stage_box_fusion',
        reviewThreshold: 0.75,
      },
    }

    expect(buildPolicyBody(draft, members, 3)).toEqual({
      mode: 'consensus',
      annotator_ids: ['id-ana', 'id-bruno'],
      resolver: 'two_stage_box_fusion',
      parameters: {},
      review_thresholds: { agreement: 0.75 },
      version: 3,
    })
  })

  it('always carries the version the caller believes is current', () => {
    expect(buildPolicyBody(baseDraft, members, 7).version).toBe(7)
  })
})
