export type User = {
  id: string
  username: string
  display_name: string
  is_administrator: boolean
  is_active: boolean
  created_at: string
}

export type LoginRequest = {
  username: string
  password: string
}

export type TokenResponse = {
  access_token: string
  token_type: 'bearer'
}

export type ApiErrorEnvelope = {
  error?: {
    code?: string
    message?: string
    details?: unknown
    trace_id?: string
  }
  detail?: string
}
