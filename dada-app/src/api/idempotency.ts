/**
 * An idempotency key that replays the original response for an identical retry
 * and becomes a new request when the body changes.
 *
 * The API stores every response below 500 under its key, including a `422`.
 * A key without the body would turn a corrected resubmission into
 * `409 idempotency_conflict`.
 */
export async function requestKey(scope: string, body: unknown) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(body)))
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${scope}:${hex.slice(0, 32)}`
}
