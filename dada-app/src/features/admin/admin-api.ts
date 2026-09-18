import { apiRequest } from '../../api/client'
import type { Page } from '../projects/types'

export type AdminUser = {
  id: string
  username: string
  display_name: string
  is_administrator: boolean
  is_active: boolean
  version: number
  created_at: string
}

export type UserCreate = {
  username: string
  display_name: string
  password: string
  is_administrator: boolean
  is_active: boolean
}

export function listUsers(token: string, active: boolean | null, cursor?: string) {
  const parameters = new URLSearchParams()
  if (active !== null) parameters.set('active', String(active))
  if (cursor) parameters.set('cursor', cursor)
  const query = parameters.size ? `?${parameters}` : ''
  return apiRequest<Page<AdminUser>>(`/api/v1/users${query}`, { token })
}

export function createUser(body: UserCreate, token: string) {
  return apiRequest<AdminUser>('/api/v1/users', {
    method: 'POST', token, body,
  })
}

export function getUser(userId: string, token: string) {
  return apiRequest<AdminUser>(`/api/v1/users/${userId}`, { token })
}

export function updateUser(
  userId: string,
  body: Pick<AdminUser, 'display_name' | 'is_active' | 'is_administrator' | 'version'>,
  token: string,
) {
  return apiRequest<AdminUser>(`/api/v1/users/${userId}`, {
    method: 'PATCH', token, body,
  })
}

export function resetUserPassword(userId: string, newPassword: string, token: string) {
  return apiRequest<void>(`/api/v1/users/${userId}/reset-password`, {
    method: 'POST', token, body: { new_password: newPassword },
  })
}

export function deleteUser(userId: string, version: number, token: string) {
  return apiRequest<void>(`/api/v1/users/${userId}`, {
    method: 'DELETE', token, headers: { 'If-Match': String(version) },
  })
}
