import { Component, type ErrorInfo, type PropsWithChildren } from 'react'

type State = { error: Error | null }

export class AppErrorBoundary extends Component<PropsWithChildren, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep diagnostic context available without sending user data externally.
    console.error('DADA application error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="centered-status" id="main-content">
        <div className="fatal-error" role="alert">
          <p className="eyebrow">Application error</p>
          <h1>The workspace could not continue</h1>
          <p>Your last local annotation recovery snapshot is retained in this browser tab.</p>
          <button className="button button--primary" onClick={() => window.location.reload()}>
            Reload workspace
          </button>
        </div>
      </main>
    )
  }
}
