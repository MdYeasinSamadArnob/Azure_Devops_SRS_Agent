export function Card({
  children,
  className = "",
  padded = true,
}: {
  children: React.ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border border-line bg-surface-raised shadow-[var(--shadow-sm)] ${padded ? "p-5" : ""} ${className}`}
    >
      {children}
    </div>
  );
}
