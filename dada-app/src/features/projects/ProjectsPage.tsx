import { useQuery } from '@tanstack/react-query'
import { Activity, AlertCircle, ClipboardCheck, FolderOpen, Layers3, PenLine, Plus, Settings, Users, Wrench } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../auth/auth-context'
import { listBatches } from './batch-api'
import type { Project } from './types'
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
          {projects.data.items.map((project) => <ProjectCard key={project.id} project={project} />)}
        </section>
      )}
    </main>
  )
}

function ProjectCard({ project }: { project: Project }) {
  const totals = useResolutionTotals(project.id, project.status === 'active')
  return (
    <article className="project-card">
      <div className="project-card__top">
        <span className={`status-badge status-badge--${project.status}`}>
          {statusLabels[project.status]}
        </span>
        <span className="task-label">{project.task_type}</span>
      </div>
      <h2>{project.name}</h2>
      <p>{project.description || 'No description'}</p>
      {totals && totals.reviewRequired > 0 && (
        <Link className="project-card__badge" to={`/projects/${project.id}/consensus`}>
          <ClipboardCheck size={14} aria-hidden="true" /> {totals.reviewRequired} image{totals.reviewRequired === 1 ? '' : 's'} need{totals.reviewRequired === 1 ? 's' : ''} review
        </Link>
      )}
      <dl>
        <div><dt>Images</dt><dd>{project.media_count ?? '—'}</dd></div>
        <div><dt>Resolved</dt><dd>{totals?.resolved ?? '—'}</dd></div>
        <div><dt>Batch</dt><dd>{project.iteration_batch_size ?? 'Static'}</dd></div>
      </dl>
      <nav className="project-card__actions" aria-label={`${project.name} actions`}>
        {project.status === 'active' && (
          <Link className="project-card__action" to={`/projects/${project.id}/reviews`}>
            <Users size={16} aria-hidden="true" /> Open my candidate reviews
          </Link>
        )}
        {project.status === 'active' && (
          <Link className="project-card__action" to={`/projects/${project.id}/annotate`}>
            <PenLine size={16} aria-hidden="true" /> Open my assignments
          </Link>
        )}
        {(project.status === 'active' || project.status === 'ready') && (
          <Link className="project-card__action" to={`/projects/${project.id}/batches`}>
            <Layers3 size={16} aria-hidden="true" /> View annotation batches
          </Link>
        )}
        {project.status === 'draft' && (
          <Link className="project-card__action" to={`/projects/${project.id}/setup`}>
            <Wrench size={16} aria-hidden="true" /> Resume project setup
          </Link>
        )}
        <Link className="project-card__action" to={`/projects/${project.id}/settings`}>
          <Settings size={16} aria-hidden="true" /> Annotation settings
        </Link>
        {(project.status === 'training' || project.status === 'completed' || project.status === 'failed') && (
          <Link className="project-card__action" to={`/projects/${project.id}/activity`}>
            <Activity size={16} aria-hidden="true" /> View iteration activity
          </Link>
        )}
      </nav>
    </article>
  )
}

/**
 * Resolved and review-required images summed over a project's batches. The
 * batches are an owner and manager view, so anyone else gets a `403` and sees
 * neither number.
 */
function useResolutionTotals(projectId: string, enabled: boolean) {
  const { token } = useAuth()
  const batches = useQuery({
    queryKey: ['project-batches', projectId],
    queryFn: () => listBatches(projectId, token!),
    enabled: Boolean(token && enabled),
    retry: (failures, error) => !(error instanceof ApiError && error.status === 403) && failures < 3,
  })
  if (!batches.data) return null
  return {
    resolved: batches.data.items.reduce((total, batch) => total + batch.resolved_items, 0),
    reviewRequired: batches.data.items.reduce((total, batch) => total + batch.review_required_items, 0),
  }
}

function errorMessage(error: Error) {
  if (error instanceof ApiError && error.status === 404) {
    return 'The projects endpoint is not available on the configured API yet.'
  }
  return error.message || 'Check the API connection and try again.'
}
