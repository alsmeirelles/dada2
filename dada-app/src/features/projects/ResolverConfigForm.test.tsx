import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PipelineCapability, TaskTypeName } from '../../api/capabilities'
import { consensusPipelines } from './resolver-catalog.fixture'
import { defaultConfiguration, type EligibilityState, type ResolverConfiguration } from './resolver-config'
import { ResolverConfigForm } from './ResolverConfigForm'

afterEach(cleanup)

function Harness({ taskType, pipeline, eligibility, onChange }: {
  taskType: TaskTypeName
  pipeline: PipelineCapability
  eligibility: EligibilityState
  onChange: (value: ResolverConfiguration) => void
}) {
  const [value, setValue] = useState(() => defaultConfiguration(taskType, pipeline))
  const [independent, setIndependent] = useState(false)
  return <ResolverConfigForm
    taskType={taskType}
    pipeline={pipeline}
    value={value}
    onChange={(next) => { setValue(next); onChange(next) }}
    eligibility={eligibility}
    requireIndependentAdjudicator={independent}
    onRequireIndependentAdjudicatorChange={setIndependent}
  />
}

function renderForm(taskType: TaskTypeName = 'detection', eligibility: EligibilityState = { status: 'no_project' }, pipeline = consensusPipelines[taskType]) {
  const onChange = vi.fn()
  render(<Harness taskType={taskType} pipeline={pipeline} eligibility={eligibility} onChange={onChange} />)
  return onChange
}

describe('ResolverConfigForm', () => {
  it('shows the pipeline, the strategies, and the main settings with their help and bounds', () => {
    renderForm()

    expect(screen.getByText('Two stage detection consensus')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Categorical vote/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /Coordinate median/ })).toBeChecked()
    expect(screen.getByLabelText('Matching IoU')).toHaveValue(0.5)
    expect(screen.getByText(/Minimum IoU for two raters' boxes to describe one object\. Greater than 0 and at most 1\./)).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Minimum support, votes' })).toHaveValue(2)
    expect(screen.getByRole('spinbutton', { name: 'Minimum support, out of' })).toHaveValue(3)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('disables conditional strategies before the project exists, with the reason', () => {
    renderForm()
    const dawidSkene = screen.getByRole('radio', { name: /Dawid skene/ })

    expect(dawidSkene).toBeDisabled()
    expect(dawidSkene).toHaveAccessibleDescription(/project's own resolved images/)
  })

  it('names the exact missing evidence once the API reports it', () => {
    renderForm('classification', {
      status: 'ready',
      report: { strategies: [
        { strategy: 'reliability_weighted_vote', eligible: true, missing: [], report: {} },
        { strategy: 'dawid_skene', eligible: false, missing: [{ requirement: 'convergence', iterations: 100 }], report: {} },
      ] },
    })

    expect(screen.getByRole('radio', { name: /Reliability weighted vote/ })).toBeEnabled()
    expect(screen.getByRole('radio', { name: /Dawid skene/ })).toHaveAccessibleDescription('Not enough project evidence: convergence (iterations 100).')
  })

  it('shows an unavailable strategy disabled with its reason', () => {
    const pipeline: PipelineCapability = {
      ...consensusPipelines.segmentation,
      geometry_strategies: consensusPipelines.segmentation.geometry_strategies.map((item) => item.id === 'staple' ? { ...item, unavailable_reason: 'quarantined' } : item),
    }
    renderForm('segmentation', { status: 'no_project' }, pipeline)

    expect(screen.getByRole('radio', { name: /STAPLE/ })).toBeDisabled()
    expect(screen.getByText('Unavailable: an operator quarantined this version.')).toBeInTheDocument()
  })

  it('switches strategy fields and keeps priors in the advanced section', () => {
    const onChange = renderForm()

    fireEvent.click(screen.getByRole('radio', { name: /Dirichlet vote/ }))

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      parameters: expect.objectContaining({ class_strategy: { strategy: 'dirichlet_vote', alpha: 0.5, minimum_posterior: 0.9 } }),
    }))
    expect(screen.queryByLabelText('Decision rule')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Minimum posterior')).toHaveValue(0.9)
    const advanced = screen.getByText('Advanced settings').closest('details')!
    expect(within(advanced).getByLabelText('Alpha')).toHaveValue(0.5)
  })

  it('refuses a support threshold at the majority floor and warns about stricter gates', () => {
    renderForm()

    fireEvent.change(screen.getByRole('spinbutton', { name: 'Minimum support, votes' }), { target: { value: '1' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Minimum support, out of' }), { target: { value: '2' } })
    expect(screen.getByText('Must be greater than 1/2.')).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Minimum support, votes' })).toHaveAttribute('aria-invalid', 'true')

    fireEvent.change(screen.getByRole('spinbutton', { name: 'Minimum support, votes' }), { target: { value: '3' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Minimum support, out of' }), { target: { value: '4' } })
    expect(screen.queryByText('Must be greater than 1/2.')).not.toBeInTheDocument()
    expect(screen.getByText(/Minimum support is stricter than its default of 2\/3/)).toBeInTheDocument()
  })

  it('warns before enabling a topology-changing mask step', () => {
    renderForm('segmentation')
    const advanced = screen.getByText('Advanced settings').closest('details')!

    fireEvent.change(within(advanced).getByLabelText('Simplify tolerance'), { target: { value: '1' } })

    expect(screen.getByText(/Simplify tolerance can change the topology of accepted masks/)).toBeInTheDocument()
  })
})
