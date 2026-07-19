import { AlertCircle, FolderOpen, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useProjects } from './useProjects'

const statusLabels = {
  draft: 'Draft', ingesting: 'Importing', ready: 'Ready', active: 'Annotating',
  training: 'Training', completed: 'Completed', failed: 'Needs attention',
}

export function ProjectsPage() {
  const projects = useProjects()

  return (
    <main className="page-container">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Projects</h1>
          <p className="muted">Create and manage active-learning datasets.</p>
        </div>
        <Link to="/projects/new" className="button button--primary">
          <Plus size={18} aria-hidden="true" /> New project
        </Link>
      </div>

      {projects.isLoading && <div className="panel status-panel">Loading projects…</div>}
      {projects.isError && (
        <div className="panel error-panel" role="alert">
          <AlertCircle aria-hidden="true" />
          <div>
            <strong>Projects could not be loaded</strong>
            <p>{errorMessage(projects.error)}</p>
            <Button variant="secondary" onClick={() => projects.refetch()}>Try again</Button>
          </div>
        </div>
      )}
      {projects.data?.items.length === 0 && (
        <section className="empty-state" aria-labelledby="empty-title">
          <FolderOpen size={36} aria-hidden="true" />
          <h2 id="empty-title">Start your first project</h2>
          <p>Choose a task, configure its classes, and import an image folder.</p>
          <Link to="/projects/new" className="button button--secondary">Create project</Link>
        </section>
      )}
      {projects.data && projects.data.items.length > 0 && (
        <section className="project-grid" aria-label="Projects">
          {projects.data.items.map((project) => (
            <article className="project-card" key={project.id}>
              <div className="project-card__top">
                <span className={`status-badge status-badge--${project.status}`}>
                  {statusLabels[project.status]}
                </span>
                <span className="task-label">{project.task_type}</span>
              </div>
              <h2>{project.name}</h2>
              <p>{project.description || 'No description'}</p>
              <dl>
                <div><dt>Images</dt><dd>{project.media_count ?? '—'}</dd></div>
                <div><dt>Annotated</dt><dd>{project.completed_annotations ?? '—'}</dd></div>
                <div><dt>Batch</dt><dd>{project.iteration_batch_size}</dd></div>
              </dl>
              {(project.status === 'active' || project.status === 'ready') && (
                <Link className="project-card__action" to={`/projects/${project.id}/annotate`}>
                  Open annotation workspace
                </Link>
              )}
            </article>
          ))}
        </section>
      )}
    </main>
  )
}

function errorMessage(error: Error) {
  if (error instanceof ApiError && error.status === 404) {
    return 'The projects endpoint is not available on the configured API yet.'
  }
  return error.message || 'Check the API connection and try again.'
}
