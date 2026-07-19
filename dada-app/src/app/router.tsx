import { createBrowserRouter, Navigate } from 'react-router-dom'

import { AppShell } from '../components/layout/AppShell'
import { LoginPage } from '../features/auth/LoginPage'
import { RequireAuth } from '../features/auth/RequireAuth'
import { NotFoundPage } from '../pages/NotFoundPage'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/projects/:projectId/annotate',
        lazy: async () => ({
          Component: (await import('../features/annotation/AnnotationWorkspacePage')).AnnotationWorkspacePage,
        }),
      },
      {
        element: <AppShell />,
        children: [
          { index: true, element: <Navigate to="/projects" replace /> },
          {
            path: '/projects',
            lazy: async () => ({
              Component: (await import('../features/projects/ProjectsPage')).ProjectsPage,
            }),
          },
          {
            path: '/projects/new',
            lazy: async () => ({
              Component: (await import('../features/projects/NewProjectPage')).NewProjectPage,
            }),
          },
          {
            path: '/projects/:projectId/activity',
            lazy: async () => ({
              Component: (await import('../features/annotation/ProjectActivityPage')).ProjectActivityPage,
            }),
          },
        ],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
])
