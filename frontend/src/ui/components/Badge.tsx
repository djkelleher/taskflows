import { forwardRef, type HTMLAttributes } from "react";

import { cx } from "../lib/cx";

export type BadgeVariant = "default" | "accent" | "success" | "warning" | "danger" | "muted";
export type BadgeSize = "sm" | "md";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  size?: BadgeSize;
  variant?: BadgeVariant;
}

const variantClass: Record<BadgeVariant, string> = {
  default: "bg-background text-foreground ring-1 ring-border",
  accent: "bg-accent/10 text-accent ring-1 ring-accent/20",
  success: "bg-positive/10 text-positive ring-1 ring-positive/20",
  warning: "bg-warning/10 text-warning ring-1 ring-warning/20",
  danger: "bg-negative/10 text-negative ring-1 ring-negative/20",
  muted: "bg-background text-muted ring-1 ring-border",
};

const sizeClass: Record<BadgeSize, string> = {
  sm: "px-[7px] py-0.5 text-[11px]",
  md: "px-2 py-0.5 text-xs",
};

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { className, size = "sm", variant = "default", ...props },
  ref
) {
  return (
    <span
      ref={ref}
      className={cx(
        "inline-flex items-center rounded-full font-semibold leading-5",
        sizeClass[size],
        variantClass[variant],
        className
      )}
      {...props}
    />
  );
});
