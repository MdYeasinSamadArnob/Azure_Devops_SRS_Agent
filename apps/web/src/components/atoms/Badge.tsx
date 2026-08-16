const TONE_CLASSES = {
  neutral: "bg-surface-sunken text-ink-muted ring-1 ring-inset ring-line",
  success: "bg-success/10 text-success ring-1 ring-inset ring-success/25",
  warning: "bg-warning/10 text-warning ring-1 ring-inset ring-warning/25",
  error: "bg-error/10 text-error ring-1 ring-inset ring-error/25",
  info: "bg-info/10 text-info ring-1 ring-inset ring-info/25",
  accent: "bg-accent/10 text-accent ring-1 ring-inset ring-accent/25",
} as const;

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof TONE_CLASSES;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px] font-medium tracking-tight uppercase ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
