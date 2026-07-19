import { z } from 'zod'

const envSchema = z.object({
  VITE_API_BASE_URL: z.string().url().transform((url) => url.replace(/\/$/, '')),
  VITE_REALTIME_URL: z.string().url().optional(),
  VITE_UPLOAD_CHUNK_BYTES: z.coerce.number().int().positive().default(8_388_608),
})

export type AppConfig = {
  apiBaseUrl: string
  realtimeUrl?: string
  uploadChunkBytes: number
}

export function parseEnv(source: Record<string, unknown>): AppConfig {
  const parsed = envSchema.safeParse(source)

  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((issue) => `${issue.path.join('.')}: ${issue.message}`)
      .join('; ')
    throw new Error(`Invalid application configuration: ${issues}`)
  }

  return {
    apiBaseUrl: parsed.data.VITE_API_BASE_URL,
    realtimeUrl: parsed.data.VITE_REALTIME_URL,
    uploadChunkBytes: parsed.data.VITE_UPLOAD_CHUNK_BYTES,
  }
}

export const config = parseEnv({
  ...import.meta.env,
  VITE_API_BASE_URL:
    import.meta.env.VITE_API_BASE_URL ??
    (import.meta.env.DEV ? 'http://localhost:8000' : undefined),
})
