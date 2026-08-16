"use client";

import { useId, type InputHTMLAttributes } from "react";

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  helperText?: string;
  errorText?: string;
  monospace?: boolean;
}

export function TextField({ label, helperText, errorText, monospace, className = "", id, ...props }: TextFieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const helperId = `${inputId}-helper`;
  const hasError = Boolean(errorText);

  return (
    <div className="space-y-1.5">
      <label htmlFor={inputId} className="block text-sm font-medium text-ink">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={hasError || undefined}
        aria-describedby={helperText || errorText ? helperId : undefined}
        className={`w-full rounded-md border bg-surface-raised px-3 py-2.5 text-sm text-ink placeholder:text-ink-faint transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-60 ${
          hasError
            ? "border-error focus:border-error focus:ring-error/25"
            : "border-line-strong focus:border-accent focus:ring-accent/20"
        } ${monospace ? "font-mono" : ""} ${className}`}
        {...props}
      />
      {(helperText || errorText) && (
        <p id={helperId} className={`text-xs ${hasError ? "text-error" : "text-ink-faint"}`} role={hasError ? "alert" : undefined}>
          {errorText || helperText}
        </p>
      )}
    </div>
  );
}
