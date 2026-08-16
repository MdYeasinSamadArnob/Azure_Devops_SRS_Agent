import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
