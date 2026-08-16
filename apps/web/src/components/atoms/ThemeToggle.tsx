"use client";

export function ThemeToggle() {
  function toggle() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("srs-agent-theme", next ? "dark" : "light");
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle color theme"
      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
    >
      {/* The `.dark` class is already applied (by the no-flash inline script
          in layout.tsx) before this component ever hydrates, so the correct
          icon can be picked with pure `dark:` CSS — no state/effect, and no
          possible flash-of-wrong-icon. */}
      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="h-4 w-4 dark:hidden">
        <path
          d="M17 10.8A7 7 0 019.2 3a7 7 0 107.8 7.8z"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>
      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="hidden h-4 w-4 dark:block">
        <path
          d="M10 2v2M10 16v2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M2 10h2M16 10h2M4.2 15.8l1.4-1.4M14.4 5.6l1.4-1.4"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <circle cx="10" cy="10" r="3.5" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </button>
  );
}
