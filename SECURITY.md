# Security Policy

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for a suspected security vulnerability.

Instead, use GitHub's private vulnerability reporting: go to the repository's **Security** tab → **Report a vulnerability**. This opens a private advisory visible only to maintainers, where you can describe the issue and coordinate a fix and disclosure timeline.

If private reporting isn't available for this repository, open a regular issue asking a maintainer to open a private channel — without describing the vulnerability itself in the public issue.

Please include, as applicable:
- The affected component (`apps/api`, `apps/worker`, `apps/web`, `packages/srs_core`)
- Steps to reproduce, or a minimal proof of concept
- The potential impact as you understand it (e.g. auth bypass, data exposure, injection)

## Scope notes specific to this project

- **Azure DevOps PATs** are encrypted at rest (`srs_core.crypto.SecretBox`, Fernet) and are never returned by any API endpoint after initial submission. If you find a code path that logs, echoes, or otherwise exposes a stored PAT, treat it as high severity.
- **Session cookies** are httpOnly, opaque UUIDs backed by a server-side `user_sessions` table — logout is a row deletion, not client-side token invalidation. A vulnerability that lets one user access another user's session or data (`created_by_user_id` scoping bypass) is high severity.
- **Sealed snapshots are meant to be immutable**, enforced by a Postgres trigger, not just application logic. A way to write to a sealed snapshot's `snapshot_work_items`/`snapshot_relations`/`assets` rows would undermine the audit-trail guarantee the whole seal/generate workflow is built on.

## Supported Versions

This project does not yet follow a formal versioned release process — security fixes land on `main`. If that changes, this section will be updated with a support table.
