import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { getCapabilities } from '../../api/capabilities'
import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import {
  addMember,
  changeMemberRole,
  deleteProject,
  getAnnotationPolicy,
  getProject,
  listMembers,
  removeMember,
  saveAnnotationPolicy,
  type ProjectMember,
} from './project-api'
import { resolverLabel } from './resolver-label'
import type { AnnotationMode } from './types'

export function ProjectSettingsPage() {
  const { projectId = '' } = useParams()
  const { token, user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => getProject(projectId, token!), enabled: Boolean(token && projectId) })
  const members = useQuery({ queryKey: ['project-members', projectId], queryFn: () => listMembers(projectId, token!), enabled: Boolean(token && projectId) })
  const policy = useQuery({ queryKey: ['project-policy', projectId], queryFn: () => getAnnotationPolicy(projectId, token!), enabled: Boolean(token && projectId) })
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: getCapabilities, staleTime: Infinity })
  const [mode, setMode] = useState<AnnotationMode>('single')
  const [annotatorIds, setAnnotatorIds] = useState<string[]>([])
  const [resolver, setResolver] = useState('')
  const [agreement, setAgreement] = useState(0.75)
  const [username, setUsername] = useState('')
  const [memberRole, setMemberRole] = useState<'manager' | 'annotator' | 'viewer'>('annotator')

  useEffect(() => {
    if (!policy.data) return
    setMode(policy.data.mode)
    setAnnotatorIds(policy.data.annotator_ids)
    setResolver(policy.data.resolver ?? '')
    setAgreement(policy.data.review_thresholds?.agreement ?? 0.75)
  }, [policy.data])

  const eligibleMembers = useMemo(
    () => (members.data?.items ?? []).filter((member) => member.role !== 'viewer'),
    [members.data],
  )
  const self = members.data?.items.find((member) => member.user_id === user?.id)
  const canManage = Boolean(user?.is_administrator || self?.role === 'owner' || self?.role === 'manager')
  const resolverOptions = capabilities.data?.consensus_resolvers[project.data?.task_type ?? ''] ?? []
  const formError = mode === 'consensus'
    ? annotatorIds.length < 2
      ? 'Consensus annotation needs at least two eligible annotators.'
      : !resolver ? 'Choose a resolution method offered by the API.' : null
    : null

  const save = useMutation({
    mutationFn: () => saveAnnotationPolicy(projectId, {
      mode,
      annotator_ids: mode === 'consensus' ? annotatorIds : [],
      resolver: mode === 'consensus' ? resolver : null,
      parameters: {},
      review_thresholds: mode === 'consensus' ? { agreement } : {},
      version: policy.data!.version,
    }, token!),
    onSuccess: (updated) => {
      queryClient.setQueryData(['project-policy', projectId], updated)
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    },
  })
  const refreshMembers = () => {
    queryClient.invalidateQueries({ queryKey: ['project-members', projectId] })
    queryClient.invalidateQueries({ queryKey: ['project-policy', projectId] })
  }
  const add = useMutation({
    mutationFn: () => addMember(projectId, username.trim(), memberRole, token!),
    onSuccess: () => { setUsername(''); refreshMembers() },
  })
  const changeRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: 'manager' | 'annotator' | 'viewer' }) => changeMemberRole(projectId, userId, role, token!),
    onSuccess: refreshMembers,
  })
  const remove = useMutation({
    mutationFn: (userId: string) => removeMember(projectId, userId, token!),
    onSuccess: refreshMembers,
  })
  const removeProject = useMutation({
    mutationFn: () => deleteProject(projectId, token!),
    onSuccess: () => { queryClient.removeQueries({ queryKey: ['projects'] }); navigate('/projects') },
  })

  if (project.isLoading || members.isLoading || policy.isLoading) return <main className="page-container"><div className="panel status-panel">Loading annotation settings…</div></main>
  if (project.isError || members.isError || policy.isError) return <main className="page-container"><div className="panel error-panel" role="alert">Annotation settings could not be loaded. Refresh and try again.</div></main>
  if (!canManage) return <main className="page-container"><div className="panel error-panel" role="alert">Only project owners and managers can change annotation settings.</div></main>

  return <main className="wizard-page">
    <div className="wizard-heading">
      <Link to="/projects" className="back-link">Projects</Link>
      <p className="eyebrow">{project.data?.name}</p>
      <h1>Annotation settings</h1>
      <p className="muted">Changes apply to future batches. Active batches keep their policy snapshot.</p>
    </div>
    <section className="wizard-card">
      <div className="wizard-section">
        <fieldset className="task-picker"><legend>Annotation strategy</legend>
          <label aria-label="Single annotation" htmlFor="settings-mode-single" className={mode === 'single' ? 'task-option selected' : 'task-option'}><input id="settings-mode-single" type="radio" name="settings-mode" checked={mode === 'single'} onChange={() => setMode('single')} /> <span><strong>Single annotation</strong><small>One submission resolves each selected image.</small></span></label>
          <label aria-label="Consensus annotation" htmlFor="settings-mode-consensus" className={mode === 'consensus' ? 'task-option selected' : 'task-option'}><input id="settings-mode-consensus" type="radio" name="settings-mode" checked={mode === 'consensus'} onChange={() => { setMode('consensus'); setResolver((value) => value || resolverOptions[0] || '') }} /> <span><strong>Consensus annotation</strong><small>Each selected member annotates independently; ambiguous items require review.</small></span></label>
        </fieldset>
        {mode === 'consensus' && <div className="field-grid">
          <label className="field">Consensus annotators
            <select multiple value={annotatorIds} onChange={(event) => setAnnotatorIds([...event.currentTarget.selectedOptions].map((option) => option.value))}>
              {eligibleMembers.map((member: ProjectMember) => <option key={member.user_id} value={member.user_id}>{member.display_name} ({member.username})</option>)}
            </select>
            <small>Select at least two owners, managers, or annotators.</small>
          </label>
          <label className="field">Resolution method
            <select value={resolver} onChange={(event) => setResolver(event.target.value)}>
              <option value="" disabled>Choose a method</option>
              {resolverOptions.map((identifier) => <option key={identifier} value={identifier}>{resolverLabel(identifier)}</option>)}
            </select>
            <small>Methods come from the API's provisional catalog.</small>
          </label>
          <label className="number-field"><span>Review threshold</span><input type="number" min="0" max="100" step="1" value={Math.round(agreement * 100)} onChange={(event) => setAgreement(Math.max(0, Math.min(1, Number(event.target.value) / 100)))} /><small>Lower agreement requires manager review.</small></label>
        </div>}
        {formError && <p className="form-error" role="alert">{formError}</p>}
        {save.isError && <p className="form-error" role="alert">{saveError(save.error)}</p>}
        <footer className="wizard-actions"><span /><Button onClick={() => save.mutate()} disabled={Boolean(formError) || save.isPending}>{save.isPending ? 'Saving…' : 'Save settings'}</Button></footer>
      </div>
    </section>
    <section className="wizard-card settings-members">
      <div className="wizard-section">
        <div><p className="eyebrow">Team</p><h2>Project members</h2><p className="muted">Managers, annotators, and viewers can be changed here. The project owner cannot be removed or transferred.</p></div>
        <div className="member-add">
          <label className="field">Existing username<input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="username" /></label>
          <label className="field">Role<select value={memberRole} onChange={(event) => setMemberRole(event.target.value as typeof memberRole)}><option value="manager">Manager</option><option value="annotator">Annotator</option><option value="viewer">Viewer</option></select></label>
          <Button onClick={() => add.mutate()} disabled={!username.trim() || add.isPending}>{add.isPending ? 'Adding…' : 'Add member'}</Button>
        </div>
        {(add.isError || changeRole.isError || remove.isError) && <p className="form-error" role="alert">{saveError((add.error ?? changeRole.error ?? remove.error) as Error)}</p>}
        <div className="member-list">
          {(members.data?.items ?? []).map((member) => <div className="member-row" key={member.user_id}><span><strong>{member.display_name}</strong><small>@{member.username}</small></span>{member.role === 'owner' ? <strong>Owner</strong> : <><select aria-label={`Role for ${member.username}`} value={member.role} onChange={(event) => changeRole.mutate({ userId: member.user_id, role: event.target.value as 'manager' | 'annotator' | 'viewer' })}><option value="manager">Manager</option><option value="annotator">Annotator</option><option value="viewer">Viewer</option></select><Button variant="ghost" onClick={() => remove.mutate(member.user_id)} disabled={remove.isPending}>Remove</Button></>}</div>)}
        </div>
      </div>
    </section>
    {self?.role === 'owner' && <section className="danger-zone"><h2>Delete project</h2><p>Deletion permanently purges uploaded media and cannot be undone.</p>{removeProject.isError && <p className="form-error" role="alert">{saveError(removeProject.error as Error)}</p>}<Button variant="secondary" disabled={removeProject.isPending} onClick={() => { if (window.confirm('Delete this project and permanently purge its uploaded media?')) removeProject.mutate() }}>{removeProject.isPending ? 'Deleting…' : 'Delete project'}</Button></section>}
  </main>
}

function saveError(error: Error) {
  if (error instanceof ApiError && error.code === 'version_conflict') return 'Settings changed elsewhere. The latest policy was loaded; review it and save again.'
  return error.message || 'Settings could not be saved.'
}
