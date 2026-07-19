import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <main className="centered-status">
      <div>
        <p className="eyebrow">404</p>
        <h1>Page not found</h1>
        <Link to="/projects">Return to projects</Link>
      </div>
    </main>
  )
}
