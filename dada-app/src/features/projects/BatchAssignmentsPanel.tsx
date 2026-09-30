import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { STATUS_LABELS } from '../annotation/assignment-view'
import type { BatchAssignment } from '../annotation/types'
import { useAuth } from '../auth/auth-context'
import { cancelBatchItem, listBatchAssignments, reassignAssignment, reopenAssignment } from './batch-api'
import type { ProjectMember } from './project-api'
import type { AnnotationBatch } from './types'

const CANCEL_WARNING = 'Cancel this image? Its assignments stop, and the image returns to the unlabeled training pool.'

export function BatchAssignmentsPanel({ projectId, batch, members }: {
  projectId: string
  batch: AnnotationBatch
  members: ProjectMember[]
}) {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const assignments = useQuery({
    queryKey: ['batch-assignments', projectId, batch.id],
    queryFn: () => listBatchAssignments(projectId, batch.id, token!),
    enabled: open && Boolean(token),
  })
  const act = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['batch-assignments', projectId, batch.id] })
      void queryClient.invalidateQueries({ queryKey: ['project-batches', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['dataset-layout', projectId] })
    },
  })
  const names = new Map(members.map((member) => [member.user_id, member.display_name]))
  const eligible = members.filter((member) => member.role !== 'viewer')
  const trainingBatch = batch.purpose === 'initial_training' || batch.purpose === 'acquisition'

  function changeable(entry: BatchAssignment) {
    return ['pending', 'in_progress', 'submitted'].includes(entry.status) && entry.item_status !== 'resolved'
  }

  return <details className="batch-details" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Assignments</summary>
    {assignments.isLoading && <p className="muted">Loading assignments…</p>}
    {act.isError && <p className="form-error" role="alert">{assignmentError(act.error)}</p>}
    {assignments.data && <table className="assignment-table">
      <thead><tr><th>Image</th><th>Annotator</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>{assignments.data.map((entry) => <tr key={entry.id}>
        <td>{entry.relative_path}</td>
        <td>{names.get(entry.annotator_id) ?? entry.annotator_id}</td>
        <td>{STATUS_LABELS[entry.status]}</td>
        <td className="assignment-actions">{changeable(entry) && <>
          {entry.status === 'submitted' && <Button variant="ghost" disabled={act.isPending} onClick={() => act.mutate(() => reopenAssignment(projectId, entry.id, token!))}>Reopen</Button>}
          <select aria-label={`Reassign ${entry.relative_path}`} value="" disabled={act.isPending} onChange={(event) => {
            const target = event.target.value
            if (target) act.mutate(() => reassignAssignment(projectId, entry.id, target, token!))
          }}>
            <option value="">Reassign to…</option>
            {eligible.filter((member) => member.user_id !== entry.annotator_id).map((member) => <option key={member.user_id} value={member.user_id}>{member.display_name}</option>)}
          </select>
          {trainingBatch && <Button variant="ghost" disabled={act.isPending} onClick={() => {
            if (window.confirm(CANCEL_WARNING)) act.mutate(() => cancelBatchItem(projectId, entry.batch_item_id, token!))
          }}>Cancel image</Button>}
        </>}</td>
      </tr>)}</tbody>
    </table>}
  </details>
}

function assignmentError(error: Error) {
  if (error instanceof ApiError && error.code === 'already_assigned') return 'That annotator already holds this image.'
  if (error instanceof ApiError && error.code === 'item_closed') return 'This image is already resolved or cancelled.'
  if (error instanceof ApiError && error.code === 'invalid_assignee') return 'Choose a member who is allowed to annotate.'
  return error.message || 'The assignment could not be changed.'
}
