import { X } from "lucide-react";
import { type HTMLAttributes, type ReactNode, useId } from "react";

import { cx } from "../lib/cx";
import { IconButton } from "./Button";

export type ToastTone = "info" | "success" | "warning" | "danger";

export interface ToastMessage {
  action?: ReactNode;
  description?: ReactNode;
  id: string;
  title: ReactNode;
  tone?: ToastTone;
}

export interface ToastProps extends HTMLAttributes<HTMLDivElement> {
  message: ToastMessage;
  onClose?: (id: string) => void;
}

const toneClass: Record<ToastTone, string> = {
  info: "border-accent/30 bg-accent/10 text-foreground",
  success: "border-positive/30 bg-positive/10 text-foreground",
  warning: "border-warning/30 bg-warning/10 text-foreground",
  danger: "border-negative/30 bg-negative/10 text-foreground",
};

export function Toast({
  "aria-describedby": ariaDescribedBy,
  "aria-labelledby": ariaLabelledBy,
  className,
  message,
  onClose,
  role,
  ...props
}: ToastProps) {
  const generatedId = useId();
  const tone = message.tone ?? "info";
  const titleId = `${generatedId}-title`;
  const descriptionId = `${generatedId}-description`;

  return (
    <div
      aria-atomic="true"
      aria-describedby={ariaDescribedBy ?? (message.description ? descriptionId : undefined)}
      aria-labelledby={ariaLabelledBy ?? titleId}
      aria-live={tone === "danger" ? "assertive" : "polite"}
      className={cx(
        "grid w-80 max-w-[calc(100vw-2rem)] grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-lg border p-3 shadow-[var(--shadow-popover)]",
        toneClass[tone],
        className
      )}
      role={role ?? (tone === "danger" ? "alert" : "status")}
      {...props}
    >
      <div className="min-w-0">
        <div className="text-sm font-semibold leading-5" id={titleId}>
          {message.title}
        </div>
        {message.description ? (
          <div className="mt-1 text-xs leading-5 opacity-80" id={descriptionId}>
            {message.description}
          </div>
        ) : null}
        {message.action ? <div className="mt-2">{message.action}</div> : null}
      </div>
      {onClose ? (
        <IconButton
          aria-label="Dismiss notification"
          className="size-7 border-transparent bg-transparent hover:bg-white/60"
          icon={<X className="size-4" aria-hidden="true" />}
          onClick={() => onClose(message.id)}
          size="sm"
          variant="ghost"
        />
      ) : null}
    </div>
  );
}

export interface ToastStackProps extends HTMLAttributes<HTMLDivElement> {
  messages: ToastMessage[];
  onClose?: (id: string) => void;
  position?: "top-right" | "bottom-right";
}

export function ToastStack({
  "aria-label": ariaLabel = "Notifications",
  className,
  messages,
  onClose,
  position = "top-right",
  role = "region",
  ...props
}: ToastStackProps) {
  return (
    <div
      aria-label={ariaLabel}
      className={cx(
        "fixed right-4 z-50 grid gap-2",
        position === "top-right" ? "top-4" : "bottom-4",
        className
      )}
      role={role}
      {...props}
    >
      {messages.map((message) => (
        <Toast key={message.id} message={message} onClose={onClose} />
      ))}
    </div>
  );
}
