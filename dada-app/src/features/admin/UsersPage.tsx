import { AlertTriangle, ChevronLeft, ChevronRight, Plus, Shield, UserRound } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import {
  createUser,
  deleteUser,
  getUser,
  listUsers,
  resetUserPassword,
  updateUser,
  type AdminUser,
  type UserCreate,
} from './admin-api'
import './admin.css'

type ActiveFilter = 'all' | 'active' | 'inactive'
type UserEdit = Pick<AdminUser, 'display_name' | 'is_active' | 'is_administrator' | 'version'>

const blankCreate: UserCreate & { confirmation: string } = {
  username: '', display_name: '', password: '', confirmation: '',
  is_administrator: false, is_active: true,
}

export function UsersPage() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<ActiveFilter>('all')
  const [cursor, setCursor] = useState<string | undefined>()
  const [history, setHistory] = useState<Array<string | undefined>>([])
  const [createDraft, setCreateDraft] = useState(blankCreate)
  const [selected, setSelected] = useState<AdminUser | null>(null)
  const [edit, setEdit] = useState<UserEdit | null>(null)
  const [serverConflict, setServerConflict] = useState<AdminUser | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [resetConfirmation, setResetConfirmation] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const active = filter === 'all' ? null : filter === 'active'
  const users = useQuery({
    queryKey: ['admin-users', active, cursor],
    queryFn: () => listUsers(token!, active, cursor),
    enabled: Boolean(token),
  })

  useEffect(() => {
    if (!selected) return
    setEdit({
      display_name: selected.display_name,
      is_active: selected.is_active,
      is_administrator: selected.is_administrator,
      version: selected.version,
    })
    setServerConflict(null)
    setResetPassword('')
    setResetConfirmation('')
  }, [selected])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin-users'] })
  const create = useMutation({
    mutationFn: () => createUser({
      username: createDraft.username.trim(),
      display_name: createDraft.display_name.trim(),
      password: createDraft.password,
      is_active: createDraft.is_active,
      is_administrator: createDraft.is_administrator,
    }, token!),
    onSuccess: () => {
      setCreateDraft(blankCreate)
      setMessage('User created. The submitted password was cleared from this page.')
      refresh()
    },
  })
  const save = useMutation({
    mutationFn: () => updateUser(selected!.id, edit!, token!),
    onSuccess: (updated) => {
      setSelected(updated)
      setMessage(`${updated.display_name} was updated.`)
      refresh()
    },
    onError: async (error) => {
      if (!(error instanceof ApiError) || error.code !== 'version_conflict' || !selected) return
      const current = await getUser(selected.id, token!)
      setServerConflict(current)
    },
  })
  const reset = useMutation({
    mutationFn: () => resetUserPassword(selected!.id, resetPassword, token!),
    onSuccess: () => {
      setResetPassword('')
      setResetConfirmation('')
      setMessage(`Password reset for ${selected!.username}. Their refresh sessions were revoked.`)
    },
  })
  const remove = useMutation({
    mutationFn: () => deleteUser(selected!.id, selected!.version, token!),
    onSuccess: () => {
      setMessage('User permanently removed.')
      setSelected(null)
      refresh()
    },
  })

  function submitCreate(event: FormEvent) {
    event.preventDefault()
    setMessage(null)
    if (createDraft.password !== createDraft.confirmation) return
    create.mutate()
  }

  function submitEdit(event: FormEvent) {
    event.preventDefault()
    if (!selected || !edit) return
    if (selected.is_active && !edit.is_active && !window.confirm(`Disable ${selected.username}? They will immediately lose access.`)) return
    setServerConflict(null)
    save.mutate()
  }

  function submitReset(event: FormEvent) {
    event.preventDefault()
    if (!selected || resetPassword !== resetConfirmation || resetPassword.length < 8) return
    if (window.confirm(`Reset ${selected.username}'s password and revoke all of their refresh sessions?`)) reset.mutate()
  }

  function removeSelected() {
    if (!selected) return
    if (window.confirm(`Permanently delete ${selected.username}? This has no restore option.`)) remove.mutate()
  }

  return <main className="page-container admin-users-page">
    <div className="page-heading"><div><p className="eyebrow">Administration</p><h1>Users</h1><p className="muted">Create accounts and manage global access. Project membership is managed inside each project.</p></div></div>
    {message && <p className="success-message" role="status">{message}</p>}
    <section className="admin-layout">
      <div className="admin-main">
        <section className="panel admin-panel">
          <div className="section-row"><div><h2>User directory</h2><p className="muted">Username, access state, and administrator authority.</p></div><label className="compact-field">Status<select value={filter} onChange={(event) => { setFilter(event.target.value as ActiveFilter); setCursor(undefined); setHistory([]) }}><option value="all">All users</option><option value="active">Active</option><option value="inactive">Inactive</option></select></label></div>
          {users.isLoading && <p>Loading users…</p>}
          {users.isError && <p className="form-error" role="alert">{adminError(users.error)}</p>}
          <div className="user-table-wrap"><table className="user-table"><thead><tr><th>User</th><th>Status</th><th>Authority</th><th>Created</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{users.data?.items.map((entry) => <tr key={entry.id}><td><strong>{entry.display_name}</strong><small>@{entry.username}</small></td><td><span className={`status-badge ${entry.is_active ? 'status-badge--active' : 'status-badge--failed'}`}>{entry.is_active ? 'Active' : 'Disabled'}</span></td><td>{entry.is_administrator ? <span className="authority"><Shield size={15} />Administrator</span> : 'User'}</td><td>{formatDate(entry.created_at)}</td><td><Button variant="ghost" onClick={() => setSelected(entry)}>Manage</Button></td></tr>)}</tbody></table></div>
          <footer className="pagination"><Button variant="secondary" disabled={!history.length} onClick={() => { const previous = [...history]; setCursor(previous.pop()); setHistory(previous) }}><ChevronLeft size={16} /> Previous</Button><Button variant="secondary" disabled={!users.data?.next_cursor} onClick={() => { setHistory((items) => [...items, cursor]); setCursor(users.data?.next_cursor ?? undefined) }}>Next <ChevronRight size={16} /></Button></footer>
        </section>
        <section className="panel admin-panel"><div><h2>Create user</h2><p className="muted">Credentials are submitted directly to the API and cleared after success.</p></div><form className="admin-form" onSubmit={submitCreate}><label>Username<input required minLength={3} maxLength={64} autoComplete="off" value={createDraft.username} onChange={(event) => setCreateDraft((draft) => ({ ...draft, username: event.target.value }))} /></label><label>Display name<input required maxLength={120} value={createDraft.display_name} onChange={(event) => setCreateDraft((draft) => ({ ...draft, display_name: event.target.value }))} /></label><label>Initial password<input required minLength={8} maxLength={128} type="password" autoComplete="new-password" value={createDraft.password} onChange={(event) => setCreateDraft((draft) => ({ ...draft, password: event.target.value }))} /></label><label>Confirm password<input required type="password" autoComplete="new-password" value={createDraft.confirmation} onChange={(event) => setCreateDraft((draft) => ({ ...draft, confirmation: event.target.value }))} /></label><label className="check-field"><input type="checkbox" checked={createDraft.is_active} onChange={(event) => setCreateDraft((draft) => ({ ...draft, is_active: event.target.checked }))} /> Active account</label><label className="check-field"><input type="checkbox" checked={createDraft.is_administrator} onChange={(event) => setCreateDraft((draft) => ({ ...draft, is_administrator: event.target.checked }))} /> Global administrator</label>{createDraft.confirmation && createDraft.password !== createDraft.confirmation && <p className="form-error">Passwords do not match.</p>}{create.isError && <p className="form-error" role="alert">{adminError(create.error)}</p>}<Button disabled={create.isPending || createDraft.password !== createDraft.confirmation}><Plus size={16} />{create.isPending ? 'Creating…' : 'Create user'}</Button></form></section>
      </div>
      <aside className="panel admin-panel user-editor" aria-live="polite">{selected && edit ? <><div><p className="eyebrow">Manage account</p><h2>{selected.display_name}</h2><p className="muted">@{selected.username}</p></div><form className="admin-form" onSubmit={submitEdit}><label>Display name<input required maxLength={120} value={edit.display_name} onChange={(event) => setEdit({ ...edit, display_name: event.target.value })} /></label><label className="check-field"><input type="checkbox" checked={edit.is_active} onChange={(event) => setEdit({ ...edit, is_active: event.target.checked })} /> Active account</label><label className="check-field"><input type="checkbox" checked={edit.is_administrator} onChange={(event) => setEdit({ ...edit, is_administrator: event.target.checked })} /> Global administrator</label>{serverConflict && <div className="conflict-panel" role="alert"><AlertTriangle size={18} /><div><strong>The account changed elsewhere.</strong><p>Server now has “{serverConflict.display_name}”, {serverConflict.is_active ? 'active' : 'disabled'}, {serverConflict.is_administrator ? 'administrator' : 'regular user'}, version {serverConflict.version}. Your edits are retained.</p><Button type="button" variant="secondary" onClick={() => { setSelected(serverConflict); setServerConflict(null) }}>Use server values</Button><Button type="button" variant="ghost" onClick={() => { setEdit({ ...edit, version: serverConflict.version }); setServerConflict(null) }}>Keep my edits with version {serverConflict.version}</Button></div></div>}{save.isError && !serverConflict && <p className="form-error" role="alert">{adminError(save.error)}</p>}<Button disabled={save.isPending || Boolean(serverConflict)}>{save.isPending ? 'Saving…' : 'Save account'}</Button></form><hr /><form className="admin-form" onSubmit={submitReset}><h3>Reset password</h3><p className="muted">This revokes the user’s refresh sessions.</p><label>New password<input type="password" minLength={8} maxLength={128} autoComplete="new-password" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} /></label><label>Confirm password<input type="password" autoComplete="new-password" value={resetConfirmation} onChange={(event) => setResetConfirmation(event.target.value)} /></label>{resetConfirmation && resetPassword !== resetConfirmation && <p className="form-error">Passwords do not match.</p>}{reset.isError && <p className="form-error" role="alert">{adminError(reset.error)}</p>}<Button variant="secondary" disabled={reset.isPending || resetPassword.length < 8 || resetPassword !== resetConfirmation}>{reset.isPending ? 'Resetting…' : 'Reset password'}</Button></form><div className="delete-user"><h3>Remove user</h3><p>Permanently deletes the account. Users with retained project or audit references cannot be deleted.</p>{remove.isError && <p className="form-error" role="alert">{adminError(remove.error)}</p>}<Button variant="secondary" disabled={remove.isPending} onClick={removeSelected}>{remove.isPending ? 'Removing…' : 'Permanently remove user'}</Button></div></> : <div className="empty-editor"><UserRound size={30} /><h2>Select a user</h2><p className="muted">Choose Manage in the directory to edit, reset credentials, disable, or remove an account.</p></div>}</aside>
    </section>
  </main>
}

function adminError(error: Error) {
  if (!(error instanceof ApiError)) return error.message || 'The user operation failed.'
  const messages: Record<string, string> = {
    username_taken: 'That username is already in use.',
    user_in_use: 'This user has retained project or audit references and cannot be removed.',
    last_active_administrator: 'This is the last active administrator. Create or enable another administrator first.',
    self_administration_change: 'You cannot remove your own active administrator access.',
    version_conflict: 'The account changed elsewhere. Review the current server values before saving.',
  }
  return `${messages[error.code ?? ''] ?? error.message}${error.traceId ? ` (trace ${error.traceId})` : ''}`
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value))
}
