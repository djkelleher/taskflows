import { AlertTriangle, Inbox } from "lucide-react";
import { type HTMLAttributes, type ReactNode, useId } from "react";

import { cx } from "../lib/cx";
import { LoadingSpinner } from "./LoadingSpinner";

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  action?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  title: ReactNode;
}

export function EmptyState({
  "aria-describedby": ariaDescribedBy,
  "aria-labelledby": ariaLabelledBy,
  action,
  className,
  description,
  icon,
  title,
  ...props
}: EmptyStateProps) {
  const generatedId = useId();
  const titleId = `${generatedId}-title`;
  const descriptionId = `${generatedId}-description`;

  return (
    <section
      aria-describedby={ariaDescribedBy ?? (description ? descriptionId : undefined)}
      aria-labelledby={ariaLabelledBy ?? titleId}
      className={cx(
        "grid place-items-center rounded-lg border border-dashed border-border bg-card/60 px-4 py-10 text-center",
        className
      )}
      {...props}
    >
      <div className="grid max-w-md justify-items-center gap-3">
        <div className="grid size-10 place-items-center rounded-full bg-background text-muted">
          {icon ?? <Inbox className="size-5" aria-hidden="true" />}
        </div>
        <div>
          <h2 className="text-sm font-semibold text-foreground" id={titleId}>
            {title}
          </h2>
          {description ? (
            <div className="mt-1 text-sm leading-6 text-muted" id={descriptionId}>
              {description}
            </div>
          ) : null}
        </div>
        {action ? <div className="mt-1">{action}</div> : null}
      </div>
    </section>
  );
}

export interface ErrorStateProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  action?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  title?: ReactNode;
}

export function ErrorState({
  "aria-describedby": ariaDescribedBy,
  "aria-labelledby": ariaLabelledBy,
  action,
  className,
  description,
  icon,
  role,
  title = "Something went wrong",
  ...props
}: ErrorStateProps) {
  const generatedId = useId();
  const titleId = `${generatedId}-title`;
  const descriptionId = `${generatedId}-description`;

  return (
    <section
      aria-describedby={ariaDescribedBy ?? (description ? descriptionId : undefined)}
      aria-labelledby={ariaLabelledBy ?? titleId}
      className={cx(
        "grid place-items-center rounded-lg border border-negative/20 bg-negative/5 px-4 py-10 text-center",
        className
      )}
      role={role ?? "alert"}
      {...props}
    >
      <div className="grid max-w-md justify-items-center gap-3">
        <div className="grid size-10 place-items-center rounded-full bg-negative/10 text-negative">
          {icon ?? <AlertTriangle className="size-5" aria-hidden="true" />}
        </div>
        <div>
          <h2 className="text-sm font-semibold text-foreground" id={titleId}>
            {title}
          </h2>
          {description ? (
            <div className="mt-1 text-sm leading-6 text-muted" id={descriptionId}>
              {description}
            </div>
          ) : null}
        </div>
        {action ? <div className="mt-1">{action}</div> : null}
      </div>
    </section>
  );
}

export interface LoadingStateProps extends HTMLAttributes<HTMLDivElement> {
  label?: string;
}

export function LoadingState({ className, label = "Loading", ...props }: LoadingStateProps) {
  return (
    <div className={cx("grid place-items-center rounded-lg px-4 py-10", className)} {...props}>
      <LoadingSpinner label={label} />
    </div>
  );
}
