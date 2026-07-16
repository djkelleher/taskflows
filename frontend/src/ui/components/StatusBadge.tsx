import { forwardRef } from "react";

import { Badge, type BadgeProps, type BadgeVariant } from "./Badge";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger" | "muted";

export interface StatusBadgeProps extends Omit<BadgeProps, "variant"> {
  tone?: StatusTone;
}

const toneToVariant: Record<StatusTone, BadgeVariant> = {
  neutral: "default",
  info: "accent",
  success: "success",
  warning: "warning",
  danger: "danger",
  muted: "muted",
};

export const StatusBadge = forwardRef<HTMLSpanElement, StatusBadgeProps>(function StatusBadge(
  { tone = "neutral", ...props },
  ref
) {
  return <Badge ref={ref} variant={toneToVariant[tone]} {...props} />;
});
