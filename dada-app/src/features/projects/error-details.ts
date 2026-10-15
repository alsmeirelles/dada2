/**
 * The readable lines of an API error's details: the `errors` list of
 * `422 invalid_resolver_configuration` or `422 invalid_review_evidence`, and
 * the unmet prerequisites (`missing`) of `422 resolver_unavailable`.
 */
export function detailErrorLines(error: unknown): string[] {
  const details = error && typeof error === 'object' ? (error as { details?: unknown }).details : undefined
  const errors = details && typeof details === 'object' ? (details as { errors?: unknown }).errors : undefined
  const missing = details && typeof details === 'object' ? (details as { missing?: unknown }).missing : undefined
  if (Array.isArray(missing)) {
    return missing.map(({ requirement, ...rest }: Record<string, unknown>) => {
      const extra = Object.entries(rest).map(([name, value]) => `${name.replaceAll('_', ' ')} ${String(value)}`).join(', ')
      return `Missing ${String(requirement).replaceAll('_', ' ')}${extra ? ` (${extra})` : ''}`
    })
  }
  if (!Array.isArray(errors)) return []
  return errors.map((entry: Record<string, unknown>) => {
    const location = Array.isArray(entry.loc) ? entry.loc.join('.') : typeof entry.field === 'string' ? entry.field : ''
    const message = typeof entry.msg === 'string' ? entry.msg : typeof entry.code === 'string' ? entry.code.replaceAll('_', ' ') : 'invalid'
    return location ? `${location}: ${message}` : message
  })
}
