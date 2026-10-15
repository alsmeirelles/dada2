import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { getCapabilities } from '../../api/capabilities'
import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { consensusKeys, getPolicyHistory, getResolverEligibility } from '../consensus/consensus-api'
import { detailErrorLines } from './error-details'
import {
  addMember,
  changeMemberRole,
  deleteProject,
  getAnnotationPolicy,
  getProject,
  listMembers,
  removeMember,
  saveAnnotationPolicy,
  updateProject,
  type ProjectMember,
} from './project-api'
import { ResolverConfigForm } from './ResolverConfigForm'
import {
  configurationIsValid,
  formatSetting,
  projectConfiguration,
  type EligibilityState,
  type ResolverConfiguration,
} from './resolver-config'
import { resolverLabel } from './resolver-label'
import { clearSetup, loadSetup } from './setup-recovery'
import type { AcquisitionStrategy, AnnotationMode } from './types'

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
  const [requiredAnnotations, setRequiredAnnotations] = useState(2)
  const [requiredReviewers, setRequiredReviewers] = useState(1)
  const [configuration, setConfiguration] = useState<ResolverConfiguration | null>(null)
  const [requireIndependent, setRequireIndependent] = useState(false)
  const [username, setUsername] = useState('')
  const [memberRole, setMemberRole] = useState<'manager' | 'annotator' | 'viewer'>('annotator')
  const [strategy, setStrategy] = useState<AcquisitionStrategy>('random')

  useEffect(() => {
    if (project.data) setStrategy(project.data.acquisition_strategy)
  }, [project.data])

  useEffect(() => {
    if (!policy.data) return
    setMode(policy.data.mode)
    setAnnotatorIds(policy.data.annotator_ids)
    setRequiredAnnotations(policy.data.required_consensus_annotations ?? 2)
    setRequiredReviewers(policy.data.required_consensus_reviewers ?? 1)
    setConfiguration(null)
    setRequireIndependent(policy.data.require_independent_adjudicator ?? false)
  }, [policy.data])

  const eligibleMembers = useMemo(
    () => (members.data?.items ?? []).filter((member) => member.role !== 'viewer'),
    [members.data],
  )
  const self = members.data?.items.find((member) => member.user_id === user?.id)
  const canManage = Boolean(user?.is_administrator || self?.role === 'owner' || self?.role === 'manager')
  const taskType = project.data?.task_type
  const pipeline = taskType ? capabilities.data?.consensus_pipelines[taskType] : undefined
  const resolverSettings = configuration ?? (taskType && pipeline ? projectConfiguration(taskType, pipeline, policy.data) : null)
  const eligibilityQuery = useQuery({
    queryKey: consensusKeys.eligibility(projectId),
    queryFn: () => getResolverEligibility(projectId, token!),
    enabled: Boolean(token && projectId && canManage && mode === 'consensus'),
  })
  const history = useQuery({
    queryKey: consensusKeys.policyHistory(projectId),
    queryFn: () => getPolicyHistory(projectId, token!),
    enabled: Boolean(token && projectId && canManage),
  })
  const eligibility: EligibilityState = eligibilityQuery.data
    ? { status: 'ready', report: eligibilityQuery.data }
    : eligibilityQuery.isError ? { status: 'error' } : { status: 'loading' }
  const formError = mode === 'consensus'
    ? consensusError(annotatorIds.length, requiredAnnotations, requiredReviewers) ??
      (!taskType || !pipeline || !resolverSettings ? 'The resolver catalog has not loaded from the API yet.'
        : configurationIsValid(taskType, pipeline, resolverSettings) ? null : 'Fix the resolver settings marked above.')
    : null

  const save = useMutation({
    mutationFn: () => saveAnnotationPolicy(projectId, {
      mode,
      annotator_ids: mode === 'consensus' ? annotatorIds : [],
      required_consensus_annotations: mode === 'consensus' ? requiredAnnotations : null,
      required_consensus_reviewers: mode === 'consensus' ? requiredReviewers : null,
      resolver: mode === 'consensus' ? pipeline!.id : null,
      parameters: mode === 'consensus' ? resolverSettings!.parameters : {},
      review_thresholds: mode === 'consensus' ? resolverSettings!.review_thresholds : {},
      require_independent_adjudicator: requireIndependent,
      version: policy.data!.version,
    }, token!),
    onSuccess: (updated) => {
      queryClient.setQueryData(['project-policy', projectId], updated)
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      queryClient.invalidateQueries({ queryKey: consensusKeys.policyHistory(projectId) })
      queryClient.invalidateQueries({ queryKey: consensusKeys.eligibility(projectId) })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'version_conflict') {
        queryClient.invalidateQueries({ queryKey: ['project-policy', projectId] })
        queryClient.invalidateQueries({ queryKey: consensusKeys.policyHistory(projectId) })
      }
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
  const saveStrategy = useMutation({
    mutationFn: () => updateProject(projectId, { acquisition_strategy: strategy, version: project.data!.version }, token!),
    onSuccess: (updated) => {
      queryClient.setQueryData(['project', projectId], updated)
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: () => queryClient.invalidateQueries({ queryKey: ['project', projectId] }),
  })
  const removeProject = useMutation({
    mutationFn: () => deleteProject(projectId, token!),
    onSuccess: () => {
      if (loadSetup()?.projectId === projectId) clearSetup()
      queryClient.removeQueries({ queryKey: ['projects'] })
      navigate('/projects')
    },
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
          <label aria-label="Consensus annotation" htmlFor="settings-mode-consensus" className={mode === 'consensus' ? 'task-option selected' : 'task-option'}><input id="settings-mode-consensus" type="radio" name="settings-mode" checked={mode === 'consensus'} onChange={() => setMode('consensus')} /> <span><strong>Consensus annotation</strong><small>A fixed cohort annotates each image; ambiguous candidates receive independent review.</small></span></label>
        </fieldset>
        {mode === 'consensus' && <div className="field-grid">
          <label className="field">Consensus annotators
            <select multiple value={annotatorIds} onChange={(event) => setAnnotatorIds([...event.currentTarget.selectedOptions].map((option) => option.value))}>
              {eligibleMembers.map((member: ProjectMember) => <option key={member.user_id} value={member.user_id}>{member.display_name} ({member.username})</option>)}
            </select>
            <small>Eligible owners, managers, and annotators. Pool size: {annotatorIds.length}.</small>
          </label>
          <label className="number-field"><span>Initial annotations per image</span><input type="number" min="2" step="1" value={requiredAnnotations} onChange={(event) => setRequiredAnnotations(Number(event.target.value))} /><small>Exact initial assignments: {requiredAnnotations} per selected image.</small></label>
          <label className="number-field"><span>Additional reviewers</span><input type="number" min="1" step="1" value={requiredReviewers} onChange={(event) => setRequiredReviewers(Number(event.target.value))} /><small>Per escalated candidate; the total depends on resolver outcomes.</small></label>
        </div>}
        {mode === 'consensus' && (taskType && pipeline && resolverSettings
          ? <ResolverConfigForm
            taskType={taskType}
            pipeline={pipeline}
            value={resolverSettings}
            onChange={setConfiguration}
            eligibility={eligibility}
            requireIndependentAdjudicator={requireIndependent}
            onRequireIndependentAdjudicatorChange={setRequireIndependent}
          />
          : <p className="notice">{capabilities.isError ? 'The resolver catalog could not be loaded from the API.' : 'Loading the resolver catalog from the API…'}</p>)}
        <p className="notice">{futureBatchesNotice(history.data?.preparing_batches)}</p>
        {formError && <p className="form-error" role="alert">{formError}</p>}
        {save.isError && <div className="form-error" role="alert">{saveError(save.error)}{detailErrorLines(save.error).map((line) => <small key={line}>{line}</small>)}</div>}
        <footer className="wizard-actions"><span /><Button onClick={() => save.mutate()} disabled={Boolean(formError) || save.isPending}>{save.isPending ? 'Saving…' : 'Save settings'}</Button></footer>
      </div>
    </section>
    {canManage && <section className="wizard-card">
      <div className="wizard-section">
        <div><p className="eyebrow">History</p><h2>Default policy history</h2><p className="muted">Every saved change to the default policy, newest first. It is read-only.</p></div>
        {history.isLoading && <p className="muted">Loading the policy history…</p>}
        {history.isError && <p className="form-error" role="alert">The policy history could not be loaded.</p>}
        {history.data && (history.data.items.length
          ? <ol className="policy-history">{history.data.items.map((change) => <li key={change.version}>
            <header><strong>Version {change.version}</strong><small>{change.actor_name ?? 'System'} · {new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(change.changed_at))}</small></header>
            {change.resolver && <small>{resolverLabel(change.resolver)}{change.resolver_version ? ` · version ${change.resolver_version}` : ''}</small>}
            <dl>{Object.entries(change.changed_fields).map(([name, values]) => <div key={name}><dt>{resolverLabel(name)}</dt><dd>{formatSetting(values.before)} → {formatSetting(values.after)}</dd></div>)}</dl>
          </li>)}</ol>
          : <p className="muted">The default policy has not been changed since the project was created.</p>)}
      </div>
    </section>}
    <section className="wizard-card">
      <div className="wizard-section">
        <div><p className="eyebrow">Acquisition</p><h2>Acquisition strategy</h2><p className="muted">Decides how later training batches are chosen. It never changes the fixed validation and test sets or the initial batches.</p></div>
        {project.data?.dataset_layout === 'single_batch'
          ? <p className="notice">Random acquisition. A static single-batch project has no later training batches, so the strategy cannot change.</p>
          : <>
            <label className="field">Strategy
              <select value={strategy} onChange={(event) => setStrategy(event.target.value as AcquisitionStrategy)}>
                <option value="random">Random acquisition</option>
                <option value="active_learning">Active learning</option>
              </select>
              <small>{strategy === 'random' ? 'Randomly selected from the remaining eligible training images.' : 'A learning model chooses later training batches once the learning adapter is available.'}</small>
            </label>
            {saveStrategy.isError && <p className="form-error" role="alert">{saveError(saveStrategy.error)}</p>}
            <footer className="wizard-actions"><span /><Button onClick={() => saveStrategy.mutate()} disabled={strategy === project.data?.acquisition_strategy || saveStrategy.isPending}>{saveStrategy.isPending ? 'Saving…' : 'Save strategy'}</Button></footer>
          </>}
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

function consensusError(poolSize: number, initial: number, reviewers: number) {
  if (initial < 2 || !Number.isInteger(initial)) return 'Initial annotations must be a whole number of at least two.'
  if (reviewers < 1 || !Number.isInteger(reviewers)) return 'Additional reviewers must be a positive whole number.'
  if (poolSize < initial + reviewers) return 'The eligible pool must fit the initial annotators and distinct reviewers.'
  return null
}

function futureBatchesNotice(preparing: number | undefined) {
  const base = 'Saving changes the default for future batches only. Started batches keep their policy snapshot.'
  if (preparing === undefined) return base
  if (!preparing) return `${base} No batch is still preparing.`
  const batches = preparing === 1 ? '1 batch is still preparing and keeps its current snapshot' : `${preparing} batches are still preparing and keep their current snapshots`
  return `${base} ${batches} until you apply the new default from Annotation batches.`
}
