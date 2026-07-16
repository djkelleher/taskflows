import {
  type HTMLAttributes,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
} from "react";
import { createPortal } from "react-dom";

import { cx } from "../lib/cx";
import { Button } from "./Button";

export interface ConfirmDialogProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  cancelLabel?: string;
  children?: ReactNode;
  closeOnBackdropClick?: boolean;
  closeOnEscape?: boolean;
  confirmLabel?: string;
  confirming?: boolean;
  confirmingLabel?: string;
  description?: ReactNode;
  initialFocus?: "cancel" | "confirm";
  onCancel: () => void;
  onConfirm: () => void;
  open: boolean;
  portal?: boolean;
  title: ReactNode;
  tone?: "default" | "danger";
}

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function ConfirmDialog({
  cancelLabel = "Cancel",
  children,
  className,
  closeOnBackdropClick = true,
  closeOnEscape = true,
  "aria-busy": ariaBusy,
  confirmLabel = "Confirm",
  confirming = false,
  confirmingLabel = "Working...",
  description,
  initialFocus = "cancel",
  onCancel,
  onConfirm,
  open,
  portal = true,
  role,
  title,
  tone = "default",
  ...props
}: ConfirmDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    window.setTimeout(() => {
      const fallback = initialFocus === "confirm" ? confirmRef.current : cancelRef.current;
      const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(focusableSelector);
      (fallback ?? firstFocusable ?? dialogRef.current)?.focus();
    }, 0);

    return () => {
      document.body.style.overflow = originalOverflow;
      previousFocusRef.current?.focus?.();
    };
  }, [initialFocus, open]);

  if (!open) {
    return null;
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    props.onKeyDown?.(event);
    if (event.defaultPrevented) {
      return;
    }

    if (event.key === "Escape" && closeOnEscape) {
      event.preventDefault();
      onCancel();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []
    ).filter((element) => !element.hasAttribute("disabled") && element.tabIndex !== -1);

    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const handleBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (closeOnBackdropClick && event.target === event.currentTarget) {
      onCancel();
    }
  };

  const content = (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[var(--color-overlay)] p-4"
      onMouseDown={handleBackdropMouseDown}
    >
      <div
        ref={dialogRef}
        aria-busy={ariaBusy ?? (confirming ? true : undefined)}
        aria-describedby={description ? descriptionId : undefined}
        aria-labelledby={titleId}
        aria-modal="true"
        className={cx("w-full max-w-md rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-dialog)]", className)}
        role={role ?? (tone === "danger" ? "alertdialog" : "dialog")}
        tabIndex={-1}
        {...props}
        onKeyDown={handleKeyDown}
      >
        <h2 className="text-base font-semibold text-foreground" id={titleId}>
          {title}
        </h2>
        {description ? (
          <div className="mt-2 text-sm leading-6 text-muted" id={descriptionId}>
            {description}
          </div>
        ) : null}
        {children ? <div className="mt-4">{children}</div> : null}
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button ref={cancelRef} className="w-full sm:w-auto" onClick={onCancel} variant="secondary">
            {cancelLabel}
          </Button>
          <Button
            ref={confirmRef}
            aria-live={confirming ? "polite" : undefined}
            className="w-full sm:w-auto"
            disabled={confirming}
            onClick={onConfirm}
            variant={tone === "danger" ? "danger" : "primary"}
          >
            {confirming ? confirmingLabel : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );

  if (portal && typeof document !== "undefined") {
    return createPortal(content, document.body);
  }

  return content;
}
