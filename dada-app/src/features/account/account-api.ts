import { apiRequest } from '../../api/client'

export function changePassword(
  currentPassword: string,
  newPassword: string,
  token: string,
) {
  return apiRequest<void>('/api/v1/auth/me/password', {
    method: 'POST',
    token,
    body: { current_password: currentPassword, new_password: newPassword },
  })
}
