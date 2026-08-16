"use client";

import { useEffect, useRef, useState } from "react";
import { openJobEventSource } from "@/lib/sse";
import { apiClient } from "@/lib/api-client";
import type { JobSummary } from "@/lib/types";

interface JobEventPayload {
  stage: string;
  message?: string;
  progress_percent?: number;
}

/**
 * Wraps EventSource against /jobs/{id}/events. The browser's native
 * `Last-Event-ID` reconnect behavior means a dropped connection resumes
 * from the last event the server confirmed, not from scratch — the API's
 * job_events replay is what makes that safe.
 */
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
// Safety net: even with SSE auth working, a connection quietly dying over a
// multi-hour job (proxy idle timeout, laptop sleep, container restart) with
// no reconnect would otherwise freeze the UI forever with no way to notice.
// This bounds how stale the display can ever get, independent of SSE health.
const FALLBACK_POLL_MS = 15_000;

export function useJobEventSource(jobId: string | null) {
  const [job, setJob] = useState<JobSummary | null>(null);
  const [events, setEvents] = useState<JobEventPayload[]>([]);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    function fetchJob() {
      return apiClient
        .get<JobSummary>(`/jobs/${jobId}`)
        .then((latest) => {
          if (cancelled) return latest;
          setJob(latest);
          if (TERMINAL_STATUSES.has(latest.status) && pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
          return latest;
        })
        .catch(() => undefined);
    }

    // Fetch the baseline BEFORE opening the stream — otherwise early SSE
    // backlog messages arrive while `job` is still null and have nothing to
    // merge into.
    fetchJob().then(() => {
      if (cancelled) return;

      const source = openJobEventSource(jobId);
      sourceRef.current = source;

      source.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as JobEventPayload;
          setEvents((prev) => [...prev, payload]);
          setJob((prev) =>
            prev
              ? { ...prev, stage: payload.stage, progress_percent: payload.progress_percent ?? prev.progress_percent }
              : prev,
          );
          // The server ends the stream on a terminal stage, but a plain
          // EventSource auto-reconnects after any closed connection per the
          // SSE spec — without this, a completed job's progress tab left
          // open keeps silently reconnecting every few seconds forever,
          // each one briefly pinning a server-side DB connection.
          if (payload.stage === "completed" || payload.stage === "failed") {
            source.close();
          }
        } catch {
          // ignore malformed event
        }
      };

      pollTimer = setInterval(fetchJob, FALLBACK_POLL_MS);
    });

    return () => {
      cancelled = true;
      sourceRef.current?.close();
      sourceRef.current = null;
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [jobId]);

  return { job, events };
}
