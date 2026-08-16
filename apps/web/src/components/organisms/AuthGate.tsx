"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { apiClient } from "@/lib/api-client";

const PUBLIC_PATHS = new Set(["/login"]);

/**
 * Every route except /login requires a valid session. The actual auth
 * check happens server-side on every real API call anyway (this is
 * defense in depth, not the source of truth) — this component's only job
 * is to hold off rendering protected content until we know /auth/me
 * succeeds, and to skip the check entirely on the login page itself.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.has(pathname);
  // Tracks the last pathname that successfully passed the /auth/me check —
  // `ready` below is derived from comparing it to the current pathname,
  // so the public-path case needs no state write at all and the
  // protected-path case only ever sets state from inside the async
  // callback, never synchronously in the effect body.
  const [checkedPathname, setCheckedPathname] = useState<string | null>(null);

  useEffect(() => {
    if (isPublic) return;
    let cancelled = false;
    apiClient
      .get("/auth/me")
      .then(() => {
        if (!cancelled) setCheckedPathname(pathname);
      })
      .catch(() => {
        // api-client's shared 401 handler already redirects to /login for a
        // clean HTTP 401 — but that only fires once fetch() actually gets a
        // response. A failure before that (CORS rejection, connection
        // refused, DNS failure, timeout) rejects here instead, with no
        // response and thus no redirect from api-client. Without a fallback
        // here too, that leaves the "Checking session…" screen hanging
        // forever with no way out — this is the fallback.
        if (!cancelled && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
          // Deliberate hard reload, not client-side routing — same
          // rationale as api-client.ts's redirect.
          // eslint-disable-next-line @next/next/no-location-assign-relative-destination
          window.location.href = "/login";
        }
      });
    return () => {
      cancelled = true;
    };
  }, [pathname, isPublic]);

  const ready = isPublic || checkedPathname === pathname;

  if (!ready) {
    return <div className="flex min-h-[50vh] items-center justify-center text-sm text-ink-faint">Checking session…</div>;
  }
  return <>{children}</>;
}
