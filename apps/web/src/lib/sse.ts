import { resolveApiBaseUrl } from "@/lib/api-base-url";

const API_BASE_URL = resolveApiBaseUrl();

/**
 * SSE is a notification channel over durable server-side state, not the
 * source of truth — the API replays missed `job_events` rows using the
 * `Last-Event-ID` the browser sends automatically on reconnect, so a
 * dropped connection never loses progress.
 */
export function openJobEventSource(jobId: string): EventSource {
  // `/jobs/{id}/events` is behind the same session-cookie auth as every
  // other route. Without withCredentials, the browser never attaches that
  // cookie cross-origin (web and api run on different ports/origins) — the
  // connection gets a 401, and per spec a non-2xx response makes
  // EventSource fail permanently (no auto-retry), silently freezing
  // progress at whatever the one-time initial REST fetch returned.
  return new EventSource(`${API_BASE_URL}/jobs/${jobId}/events`, { withCredentials: true });
}
