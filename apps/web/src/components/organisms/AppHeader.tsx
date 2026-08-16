import Link from "next/link";
import { ThemeToggle } from "@/components/atoms/ThemeToggle";
import { UserMenu } from "./UserMenu";

const NAV_LINKS = [
  { href: "/", label: "Projects" },
  { href: "/settings", label: "Settings" },
];

export function AppHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-surface/85 backdrop-blur-sm">
      <div className="mx-auto flex h-14 w-full max-w-4xl items-center justify-between px-6">
        <div className="flex items-center gap-6">
          <Link href="/" className="group flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="flex h-6 w-6 items-center justify-center rounded-[5px] bg-accent text-[13px] font-bold leading-none text-accent-ink"
            >
              S
            </span>
            <span className="font-display text-[15px] font-semibold tracking-[-0.01em] text-ink">
              SRS Agent
            </span>
          </Link>
          <nav className="hidden items-center gap-4 sm:flex">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-xs font-medium text-ink-muted transition-colors hover:text-ink"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <UserMenu />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
