"use client";

import { AccentPicker } from "@/components/molecules/AccentPicker";

export function AppearanceSettingsTemplate() {
  return (
    <div className="space-y-8 pt-6">
      <div className="space-y-2">
        <h2 className="text-lg font-semibold tracking-[-0.01em] text-ink">Accent color</h2>
        <p className="max-w-lg text-sm leading-relaxed text-ink-muted">
          Pick the accent used across buttons, links, and highlights. Applies immediately and only to your
          browser — the quick light/dark switch stays in the header.
        </p>
      </div>
      <AccentPicker />
    </div>
  );
}
