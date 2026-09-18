import { KeyRound } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { changePassword } from './account-api'
import './account.css'

export function ChangePasswordPage() {
  const { token, user } = useAuth()
  const currentRef = useRef<HTMLInputElement>(null)
  const [current, setCurrent] = useState('')
  const [replacement, setReplacement] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [saved, setSaved] = useState(false)
  const change = useMutation({
    mutationFn: () => changePassword(current, replacement, token!),
    onSuccess: () => {
      setCurrent('')
      setReplacement('')
      setConfirmation('')
      setSaved(true)
    },
    onError: (error) => {
      setSaved(false)
      if (error instanceof ApiError && error.code === 'current_password_incorrect') {
        currentRef.current?.focus()
      }
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    setSaved(false)
    if (replacement.length < 8 || replacement !== confirmation) return
    change.mutate()
  }

  const currentIncorrect = change.error instanceof ApiError
    && change.error.code === 'current_password_incorrect'

  return <main className="page-container account-page">
    <section className="panel account-card">
      <div className="account-icon"><KeyRound aria-hidden="true" /></div>
      <p className="eyebrow">Account security</p>
      <h1>Change password</h1>
      <p className="muted">Signed in as {user?.display_name ?? user?.username}. Changing your password revokes your refresh sessions.</p>
      {saved && <p className="success-message" role="status">Password changed. The submitted credentials were cleared.</p>}
      <form className="account-form" onSubmit={submit}>
        <label>Current password<input ref={currentRef} required type="password" autoComplete="current-password" value={current} aria-invalid={currentIncorrect} aria-describedby={currentIncorrect ? 'current-password-error' : undefined} onChange={(event) => setCurrent(event.target.value)} /></label>
        {currentIncorrect && <p id="current-password-error" className="field-error">The current password is incorrect.</p>}
        <label>New password<input required minLength={8} maxLength={128} type="password" autoComplete="new-password" value={replacement} onChange={(event) => setReplacement(event.target.value)} /><small>Use at least 8 characters.</small></label>
        <label>Confirm new password<input required type="password" autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
        {confirmation && replacement !== confirmation && <p className="field-error">Passwords do not match.</p>}
        {change.isError && !currentIncorrect && <p className="form-error" role="alert">{passwordError(change.error)}</p>}
        <Button disabled={change.isPending || replacement.length < 8 || replacement !== confirmation}>{change.isPending ? 'Changing…' : 'Change password'}</Button>
      </form>
    </section>
  </main>
}

function passwordError(error: Error) {
  if (error instanceof ApiError) return `${error.message}${error.traceId ? ` (trace ${error.traceId})` : ''}`
  return error.message || 'The password could not be changed.'
}
