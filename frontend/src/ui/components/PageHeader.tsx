import { type HTMLAttributes, type ReactNode } from "react";

import { cx } from "../lib/cx";

export interface PageHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  actions?: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  title: ReactNode;
}

export function PageHeader({ actions, className, description, eyebrow, title, ...props }: PageHeaderProps) {
  return (
    <div className={cx("flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between", className)} {...props}>
      <div className="min-w-0">
        {eyebrow ? <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-accent">{eyebrow}</div> : null}
        <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
        {description ? <div className="mt-1 max-w-3xl text-sm leading-6 text-muted">{description}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
