import { useQuery } from '@tanstack/react-query'

import { useAuth } from '../auth/auth-context'
import { listProjects } from './project-api'

export function useProjects() {
  const { token } = useAuth()
  return useQuery({
    queryKey: ['projects'],
    queryFn: () => listProjects(token!),
    enabled: token !== null,
  })
}
