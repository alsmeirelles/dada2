import { config } from '../config/env'
import type { ApiErrorEnvelope } from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly traceId?: string,
    readonly details?: unknown,
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

let unauthorizedHandler: (() => void) | null = null

/**
 * Registers what happens when a request made with an access token is refused
 * with `401`: the session is over, so the App signs out and returns to the
 * login page (I7-05).
 */
export function onUnauthorized(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

async function send(
  path: string,
  { body, rawBody, token, headers, ...init }: RequestOptions,
): Promise<Response> {
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
    if (response.status === 401 && token) unauthorizedHandler?.()
    const payload = await readJson<ApiErrorEnvelope>(response)
    throw new ApiError(
      payload?.error?.message ?? payload?.detail ?? response.statusText,
      response.status,
      payload?.error?.code,
      payload?.error?.trace_id,
      payload?.error?.details,
    )
  }
  return response
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options)
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }
  return (await response.json()) as T
}

/** Downloads a file response, with the name the API gives it in `Content-Disposition`. */
export async function apiDownload(path: string, options: RequestOptions = {}) {
  const response = await send(path, options)
  const disposition = response.headers.get('content-disposition') ?? ''
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? 'download'
  return { blob: await response.blob(), name }
}

async function readJson<T>(response: Response): Promise<T | undefined> {
  try {
    return (await response.json()) as T
  } catch {
    return undefined
  }
}
