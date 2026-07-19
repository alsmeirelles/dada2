import { config } from '../../config/env'

export function projectWebSocketUrl(projectId: string, providedUrl?: string) {
  if (providedUrl) return providedUrl
  const base = config.realtimeUrl ?? config.apiBaseUrl.replace(/^http/, 'ws')
  return `${base}/api/v1/projects/${encodeURIComponent(projectId)}/events`
}

export function reconnectDelay(attempt: number) {
  return Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5))
}
