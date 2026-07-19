import { config } from '../config/env'
import type { ApiErrorEnvelope } from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly traceId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  rawBody?: BodyInit
  token?: string | null
}

export async function apiRequest<T>(
  path: string,
  { body, rawBody, token, headers, ...init }: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    ...init,
    body: rawBody ?? (body === undefined ? undefined : JSON.stringify(body)),
    headers: {
      Accept: 'application/json',
      ...(body === undefined || rawBody !== undefined
        ? {}
        : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  })

  if (!response.ok) {
    const payload = await readJson<ApiErrorEnvelope>(response)
    throw new ApiError(
      payload?.error?.message ?? payload?.detail ?? response.statusText,
      response.status,
      payload?.error?.code,
      payload?.error?.trace_id,
    )
  }

  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }
  return (await response.json()) as T
}

async function readJson<T>(response: Response): Promise<T | undefined> {
  try {
    return (await response.json()) as T
  } catch {
    return undefined
  }
}
