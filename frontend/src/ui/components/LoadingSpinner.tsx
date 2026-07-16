import { type HTMLAttributes } from "react";

import { cx } from "../lib/cx";

export interface LoadingSpinnerProps extends HTMLAttributes<HTMLDivElement> {
  label?: string;
  size?: "sm" | "md" | "lg";
}

const sizeClass = {
  sm: "size-3",
  md: "size-4",
  lg: "size-6",
};

export function LoadingSpinner({
  className,
  label = "Loading",
  size = "md",
  ...props
}: LoadingSpinnerProps) {
  return (
    <div
      aria-live="polite"
      className={cx("inline-flex items-center gap-2 text-sm text-muted", className)}
      role="status"
      {...props}
    >
      <span
        aria-hidden="true"
        className={cx("animate-spin rounded-full border-2 border-border border-t-accent", sizeClass[size])}
      />
      <span>{label}</span>
    </div>
  );
}
