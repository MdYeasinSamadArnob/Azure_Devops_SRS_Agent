"use client";

import { useState, useSyncExternalStore } from "react";

// No real external event source ever fires here (the dataset attribute only
// ever changes via this component's own click handler) — subscribe is a
// no-op. useSyncExternalStore still gets us a hydration-safe first read of
// `document.documentElement.dataset.accent` without a mount-time effect.
function subscribeToNothing() {
  return () => {};
}
function readCurrentAccent() {
  return document.documentElement.dataset.accent || "signal";
}
function readServerAccent() {
  return "signal";
}

interface AccentOption {
  id: string;
  label: string;
  swatch: string;
}

// Swatch colors mirror each accent's LIGHT-mode --color-accent value in
// globals.css — the picker itself doesn't switch with dark mode, so it
// shows the more commonly-seen (light-mode) shade.
const ACCENT_OPTIONS: AccentOption[] = [
  { id: "signal", label: "Signal (default)", swatch: "#e8491f" },
  { id: "azure", label: "Azure", swatch: "#2563a8" },
  { id: "forest", label: "Forest", swatch: "#2f7d4f" },
  { id: "violet", label: "Violet", swatch: "#6d28d9" },
  { id: "rose", label: "Rose", swatch: "#be185d" },
  { id: "amber", label: "Amber", swatch: "#a16207" },
];

export function AccentPicker() {
  const initialAccent = useSyncExternalStore(subscribeToNothing, readCurrentAccent, readServerAccent);
  const [accent, setAccent] = useState(initialAccent);

  function choose(id: string) {
    if (id === "signal") {
      document.documentElement.removeAttribute("data-accent");
      localStorage.removeItem("srs-agent-accent");
    } else {
      document.documentElement.setAttribute("data-accent", id);
      localStorage.setItem("srs-agent-accent", id);
    }
    setAccent(id);
  }

  return (
    <div className="flex flex-wrap gap-3" role="radiogroup" aria-label="Accent color">
      {ACCENT_OPTIONS.map((option) => {
        const selected = accent === option.id;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => choose(option.id)}
            className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs font-medium transition-colors ${
              selected ? "border-accent bg-surface-sunken text-ink" : "border-line text-ink-muted hover:border-line-strong hover:text-ink"
            }`}
          >
            <span
              aria-hidden="true"
              className="h-4 w-4 shrink-0 rounded-full border border-black/10"
              style={{ backgroundColor: option.swatch }}
            />
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
