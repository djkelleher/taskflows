import { type HTMLAttributes, type ReactNode } from "react";

import { cx } from "../lib/cx";
import { Card } from "./Card";

export type MetricTone = "neutral" | "positive" | "negative" | "warning" | "accent";

export interface BigNumberProps extends HTMLAttributes<HTMLDivElement> {
  delta?: ReactNode;
  hint?: ReactNode;
  label?: ReactNode;
  tone?: MetricTone;
  value: ReactNode;
}

const toneClass: Record<MetricTone, string> = {
  neutral: "text-foreground",
  positive: "text-positive",
  negative: "text-negative",
  warning: "text-warning",
  accent: "text-accent",
};

export function BigNumber({ className, delta, hint, label, tone = "neutral", value, ...props }: BigNumberProps) {
  return (
    <div className={cx("min-w-0", className)} {...props}>
      {label ? <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div> : null}
      <div className={cx("mt-1 truncate text-2xl font-semibold tabular-nums tracking-tight", toneClass[tone])}>
        {value}
      </div>
      {(delta || hint) ? (
        <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-muted">
          {delta ? <span className={cx("font-medium", toneClass[tone])}>{delta}</span> : null}
          {hint ? <span className="truncate">{hint}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

export interface MetricCardProps extends BigNumberProps {
  icon?: ReactNode;
}

export function MetricCard({ className, icon, ...props }: MetricCardProps) {
  return (
    <Card className={cx("flex items-start justify-between gap-3", className)}>
      <BigNumber {...props} />
      {icon ? <div className="grid size-9 shrink-0 place-items-center rounded-md bg-background text-muted">{icon}</div> : null}
    </Card>
  );
}
