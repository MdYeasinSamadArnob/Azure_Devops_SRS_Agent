export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`animate-pulse rounded-lg border border-line bg-surface-sunken ${className}`}
    />
  );
}
