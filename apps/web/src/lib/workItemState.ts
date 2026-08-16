import type { Badge } from "@/components/atoms/Badge";
import type { ComponentProps } from "react";

type BadgeTone = NonNullable<ComponentProps<typeof Badge>["tone"]>;

/**
 * Azure DevOps process templates define their own state names per team —
 * this org's real backlog alone has "Active", "Under-Analysis N Design",
 * "Deployed for UAT", "Testing Failed", "In-Live", "Mitigated", and more,
 * not a fixed Agile/Scrum state set. A generic keyword-bucket classifier
 * (same approach as the backend's custom-field discovery) works across any
 * org's customized states instead of hardcoding one org's exact strings.
 */
export function stateTone(state: string): BadgeTone {
  const key = state.toLowerCase();
  if (/removed|rejected|cancelled|canceled|failed|blocked/.test(key)) return "error";
  if (/hold/.test(key)) return "warning";
  if (/closed|resolved|completed|done|live|passed|mitigated|deployed/.test(key)) return "success";
  if (/new|proposed|backlog|to do/.test(key)) return "neutral";
  return "info"; // Active, In Progress, Design, Ready, Under-*, ... — the default "in flight" bucket
}
