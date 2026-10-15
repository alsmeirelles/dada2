import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'

import { getCapabilities } from '../../api/capabilities'
import { ResolverConfigForm } from '../projects/ResolverConfigForm'
import {
  configurationIsValid,
  projectConfiguration,
  type EligibilityState,
  type ResolverConfiguration,
} from '../projects/resolver-config'
import { ConfirmDialog } from './ConfirmDialog'
import { consensusKeys, getResolverEligibility } from './consensus-api'
import type { ImageEvidence, RetryRequest } from './consensus-types'

type RetryDialogProps = {
  projectId: string
  evidence: ImageEvidence
  token: string
  pending: boolean
  error: unknown
  onConfirm: (rationale: string, configuration?: RetryRequest['configuration']) => void
  onCancel: () => void
}

/**
 * Confirms a retry over the image's latest evidence. By default the run uses
 * the batch configuration; an explicit configuration starts from the latest
 * run's and is validated against the same descriptors as a policy.
 */
export function RetryDialog({ projectId, evidence, token, pending, error, onConfirm, onCancel }: RetryDialogProps) {
  const overrideId = useId()
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getCapabilities, staleTime: Infinity })
  const eligibilityQuery = useQuery({
    queryKey: consensusKeys.eligibility(projectId),
    queryFn: () => getResolverEligibility(projectId, token),
  })
  const pipeline = capabilities.data?.consensus_pipelines[evidence.task_type]
  const latest = evidence.runs[evidence.runs.length - 1]
  const [override, setOverride] = useState(false)
  const [configuration, setConfiguration] = useState<ResolverConfiguration | null>(null)
  const eligibility: EligibilityState = eligibilityQuery.data
    ? { status: 'ready', report: eligibilityQuery.data }
    : eligibilityQuery.isError ? { status: 'error' } : { status: 'loading' }
  const invalid = override && (!pipeline || !configuration || !configurationIsValid(evidence.task_type, pipeline, configuration))

  function toggle(checked: boolean) {
    setOverride(checked)
    if (checked && pipeline && !configuration) setConfiguration(projectConfiguration(evidence.task_type, pipeline, latest?.configuration))
  }

  return <ConfirmDialog
    title="Retry resolution"
    effect={override
      ? 'This queues a new resolver run over the image\'s latest evidence with the configuration below. The batch configuration is not changed, and the current resolution stays in place unless the new run\'s result is accepted.'
      : 'This queues a new resolver run over the image\'s latest evidence with the batch configuration. The current resolution stays in place unless the new run\'s result is accepted.'}
    confirmLabel="Queue a new run"
    rationale="required"
    pending={pending}
    error={error}
    confirmDisabled={invalid}
    onConfirm={(rationale) => onConfirm(rationale, override && configuration ? configuration : undefined)}
    onCancel={onCancel}
  >
    <div className="resolver-check">
      <input id={overrideId} type="checkbox" checked={override} disabled={pending || !pipeline} onChange={(event) => toggle(event.target.checked)} />
      <label htmlFor={overrideId}><strong>Use a different configuration for this run</strong><small>It starts from the latest run's configuration{latest ? ` (run ${latest.sequence})` : ''}.</small></label>
    </div>
    {override && pipeline && configuration && <ResolverConfigForm
      taskType={evidence.task_type}
      pipeline={pipeline}
      value={configuration}
      onChange={setConfiguration}
      eligibility={eligibility}
      disabled={pending}
    />}
  </ConfirmDialog>
}
