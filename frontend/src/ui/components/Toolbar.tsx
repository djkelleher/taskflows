import { type HTMLAttributes } from "react";

import { cx } from "../lib/cx";

export interface ToolbarProps extends HTMLAttributes<HTMLDivElement> {
  wrap?: boolean;
}

export function Toolbar({ className, wrap = true, ...props }: ToolbarProps) {
  return (
    <div
      className={cx(
        "flex items-center gap-2 rounded-lg border border-border bg-card p-2",
        wrap ? "flex-wrap" : "overflow-x-auto",
        className
      )}
      {...props}
    />
  );
}

export function ToolbarSpacer({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("min-w-2 flex-1", className)} aria-hidden="true" {...props} />;
}
