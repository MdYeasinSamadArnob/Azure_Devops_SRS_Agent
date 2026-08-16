"use client";

import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANT_CLASSES: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-ink hover:bg-accent-hover active:bg-accent-hover disabled:bg-line disabled:text-ink-faint",
  secondary:
    "bg-transparent text-ink border border-line-strong hover:bg-surface-sunken active:bg-surface-sunken disabled:text-ink-faint disabled:border-line",
  ghost: "bg-transparent text-ink-muted hover:bg-surface-sunken hover:text-ink disabled:text-ink-faint",
  danger: "bg-error text-white hover:opacity-90 active:opacity-90 disabled:bg-line disabled:text-ink-faint",
};

const SIZE_CLASSES: Record<Size, string> = {
  sm: "px-3 py-1.5 text-sm gap-1.5",
  md: "px-4 py-2.5 text-sm gap-2",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-md font-medium tracking-[-0.01em] transition-colors duration-150 ease-out disabled:cursor-not-allowed ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
