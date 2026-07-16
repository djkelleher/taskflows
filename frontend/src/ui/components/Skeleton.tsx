import { type HTMLAttributes } from "react";

import { cx } from "../lib/cx";

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** Convenience shape presets. */
  variant?: "text" | "circle" | "rect";
}

const variantClass: Record<NonNullable<SkeletonProps["variant"]>, string> = {
  text: "h-4 w-full rounded",
  circle: "rounded-full",
  rect: "rounded-md",
};

/**
 * Animated placeholder for content that is loading. Decorative by default
 * (aria-hidden); wrap a labelled region with aria-busy for screen readers.
 */
export function Skeleton({ className, variant = "rect", ...props }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cx("animate-pulse bg-surface-muted", variantClass[variant], className)}
      {...props}
    />
  );
}

export interface SkeletonTextProps extends HTMLAttributes<HTMLDivElement> {
  /** Number of lines to render. */
  lines?: number;
}

/** Multi-line text skeleton; the last line is shortened for realism. */
export function SkeletonText({ className, lines = 3, ...props }: SkeletonTextProps) {
  return (
    <div className={cx("grid gap-2", className)} {...props}>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          variant="text"
          className={index === lines - 1 && lines > 1 ? "w-3/5" : undefined}
        />
      ))}
    </div>
  );
}
