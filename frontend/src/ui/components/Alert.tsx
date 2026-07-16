import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { type HTMLAttributes, type ReactNode, useId } from "react";

import { cx } from "../lib/cx";
import { IconButton } from "./Button";

export type AlertTone = "info" | "success" | "warning" | "danger";

export interface AlertProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  action?: ReactNode;
  description?: ReactNode;
  /** Override the default tone icon, or pass null to hide it. */
  icon?: ReactNode | null;
  onClose?: () => void;
  title?: ReactNode;
  tone?: AlertTone;
}

const toneClass: Record<AlertTone, string> = {
  info: "border-info/30 bg-info/10 text-foreground",
  success: "border-positive/30 bg-positive/10 text-foreground",
  warning: "border-warning/30 bg-warning/10 text-foreground",
  danger: "border-negative/30 bg-negative/10 text-foreground",
};

const iconColor: Record<AlertTone, string> = {
  info: "text-info",
  success: "text-positive",
  warning: "text-warning",
  danger: "text-negative",
};

const toneIcon: Record<AlertTone, ReactNode> = {
  info: <Info className="size-4" aria-hidden="true" />,
  success: <CheckCircle2 className="size-4" aria-hidden="true" />,
  warning: <AlertTriangle className="size-4" aria-hidden="true" />,
  danger: <XCircle className="size-4" aria-hidden="true" />,
};

/**
 * Inline, persistent message banner (distinct from transient toasts). Danger
 * tone announces as an alert; other tones as a status region.
 */
export function Alert({
  "aria-describedby": ariaDescribedBy,
  "aria-labelledby": ariaLabelledBy,
  action,
  className,
  children,
  description,
  icon,
  onClose,
  role,
  title,
  tone = "info",
  ...props
}: AlertProps) {
  const generatedId = useId();
  const titleId = `${generatedId}-title`;
  const descriptionId = `${generatedId}-description`;
  const body = description ?? children;
  const resolvedIcon = icon === null ? null : (icon ?? toneIcon[tone]);

  return (
    <div
      aria-describedby={ariaDescribedBy ?? (body ? descriptionId : undefined)}
      aria-labelledby={ariaLabelledBy ?? (title ? titleId : undefined)}
      className={cx(
        "grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 rounded-lg border p-3 text-sm",
        toneClass[tone],
        className
      )}
      role={role ?? (tone === "danger" ? "alert" : "status")}
      {...props}
    >
      {resolvedIcon ? (
        <span className={cx("mt-0.5", iconColor[tone])}>{resolvedIcon}</span>
      ) : (
        <span aria-hidden="true" />
      )}
      <div className="min-w-0">
        {title ? (
          <div className="font-semibold leading-5" id={titleId}>
            {title}
          </div>
        ) : null}
        {body ? (
          <div className={cx("leading-5", title && "mt-1 text-xs opacity-90")} id={descriptionId}>
            {body}
          </div>
        ) : null}
        {action ? <div className="mt-2">{action}</div> : null}
      </div>
      {onClose ? (
        <IconButton
          aria-label="Dismiss"
          className="size-6 border-transparent bg-transparent"
          icon={<X className="size-4" aria-hidden="true" />}
          onClick={onClose}
          size="sm"
          variant="ghost"
        />
      ) : (
        <span aria-hidden="true" />
      )}
    </div>
  );
}
