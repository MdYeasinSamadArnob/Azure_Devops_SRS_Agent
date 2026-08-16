import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Minimal, self-contained production server bundle (.next/standalone) —
  // only the node_modules subset actually needed at runtime gets traced in,
  // instead of shipping the full deps tree. Used by the Dockerfile's `prod`
  // build target; has no effect on `next dev`.
  output: "standalone",
  // Next.js's dev server only serves its own JS chunks (/_next/static/...)
  // to origins it recognizes, as a CSRF-hardening measure — accessing the
  // app via anything other than localhost (a LAN IP, a hostname) gets a
  // silent 403 on every chunk otherwise, which breaks hydration entirely
  // (forms render but no click handler ever fires, no error is ever
  // shown). Add every non-localhost origin you'll actually open this app
  // from here.
  allowedDevOrigins: ["10.11.200.99"],
};

export default nextConfig;
