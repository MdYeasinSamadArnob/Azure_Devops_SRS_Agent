/**
 * Resolves the browser-reachable API origin.
 *
 * Prefers an explicit NEXT_PUBLIC_API_BASE_URL (baked in at build time) for
 * advanced deployments — a reverse proxy, a non-default port mapping, the
 * API on a separate domain. Left unset (the default), it derives the API
 * origin from whatever host the browser actually used to load the page —
 * this is what makes the app work whether it's opened via localhost, a LAN
 * IP, or a real domain, without a separate build per access pattern. A
 * value baked in as "localhost" breaks the moment anyone loads the page
 * from a different device, since "localhost" then resolves to *their*
 * machine, not the server.
 */
const EXPLICIT_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

// Matches docker-compose.yml's default `api` port mapping (container 8000
// -> host 8010). Only relevant when EXPLICIT_BASE_URL isn't set.
const DEFAULT_API_PORT = "8010";

export function resolveApiBaseUrl(): string {
  if (EXPLICIT_BASE_URL) return EXPLICIT_BASE_URL;
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:${DEFAULT_API_PORT}`;
  }
  // No window (SSR) — none of this app's actual data fetching runs
  // server-side today (every apiClient/SSE call is inside a "use client"
  // effect), so this branch is defensive only, not exercised in practice.
  return `http://localhost:${DEFAULT_API_PORT}`;
}
