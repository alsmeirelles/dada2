import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from './auth-context'

type LocationState = { from?: { pathname?: string } }

export function LoginPage() {
  const { login, token } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (token) return <Navigate to="/projects" replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    const data = new FormData(event.currentTarget)

    try {
      await login({
        username: String(data.get('username')),
        password: String(data.get('password')),
      })
      const state = location.state as LocationState | null
      navigate(state?.from?.pathname ?? '/projects', { replace: true })
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : 'Unable to contact the DADA API. Please try again.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-panel" aria-labelledby="login-title">
        <div className="brand-mark" aria-hidden="true">D</div>
        <p className="eyebrow">DADA workspace</p>
        <h1 id="login-title">Welcome back</h1>
        <p className="muted">Sign in to manage projects and annotate datasets.</p>

        <form className="form-stack" onSubmit={handleSubmit}>
          <label>
            Username
            <input name="username" autoComplete="username" required minLength={3} />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              minLength={8}
            />
          </label>
          {error && <div className="form-error" role="alert">{error}</div>}
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
      </section>
      <aside className="auth-art" aria-hidden="true">
        <span>Classify.</span><span>Detect.</span><span>Segment.</span>
      </aside>
    </main>
  )
}
