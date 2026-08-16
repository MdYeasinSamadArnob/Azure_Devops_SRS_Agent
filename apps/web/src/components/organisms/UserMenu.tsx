"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { apiClient } from "@/lib/api-client";

interface CurrentUser {
  email: string;
  is_superuser: boolean;
}

export function UserMenu() {
  const pathname = usePathname();
  const [user, setUser] = useState<CurrentUser | null>(null);

  useEffect(() => {
    // Re-checks on every navigation, not just on mount — AppHeader lives in
    // the root layout, which persists across client-side route changes
    // (router.push, not a full reload). Logging in navigates from /login to
    // / without remounting this component, so a mount-only check would
    // permanently miss that transition and keep showing "logged out" even
    // after a successful login.
    apiClient
      .get<CurrentUser>("/auth/me")
      .then(setUser)
      .catch(() => setUser(null));
  }, [pathname]);

  async function handleLogout() {
    try {
      await apiClient.post("/auth/logout");
    } finally {
      // Deliberate hard reload, not client-side routing — clears every
      // in-memory React/query state that assumed an authenticated session.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
  }

  if (!user) return null;

  return (
    <div className="flex items-center gap-3">
      <span className="hidden font-mono text-[11px] text-ink-faint sm:inline">{user.email}</span>
      <button
        type="button"
        onClick={handleLogout}
        className="rounded-md px-2 py-1 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
      >
        Log out
      </button>
    </div>
  );
}
