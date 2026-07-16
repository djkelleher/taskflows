import { X } from "lucide-react";
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

import { focusableSelector, getFocusable } from "../lib/focus";
import { cx } from "../lib/cx";
import { IconButton } from "./Button";

export type ModalSize = "sm" | "md" | "lg" | "xl";

export interface ModalProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  children?: ReactNode;
  closeOnBackdropClick?: boolean;
  closeOnEscape?: boolean;
  description?: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  open: boolean;
  portal?: boolean;
  showCloseButton?: boolean;
  size?: ModalSize;
  title?: ReactNode;
}

const sizeClass: Record<ModalSize, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-2xl",
};

/**
 * Accessible modal dialog with focus trap, scroll lock, Escape/backdrop close,
 * and focus restoration. Use ConfirmDialog for confirm/cancel prompts.
 */
export function Modal({
  children,
  className,
  closeOnBackdropClick = true,
  closeOnEscape = true,
  description,
  footer,
  onClose,
  open,
  portal = true,
  role,
  showCloseButton = true,
  size = "md",
  title,
  ...props
}: ModalProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    window.setTimeout(() => {
      const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(focusableSelector);
      (firstFocusable ?? dialogRef.current)?.focus();
    }, 0);

    return () => {
      document.body.style.overflow = originalOverflow;
      previousFocusRef.current?.focus?.();
    };
  }, [open]);

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
      onClose();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusable = getFocusable(dialogRef.current);
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
      onClose();
    }
  };

  const content = (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[var(--color-overlay)] p-4"
      onMouseDown={handleBackdropMouseDown}
    >
      <div
        ref={dialogRef}
        aria-describedby={description ? descriptionId : undefined}
        aria-labelledby={title ? titleId : undefined}
        aria-modal="true"
        className={cx(
          "flex max-h-[calc(100vh-2rem)] w-full flex-col rounded-lg border border-border bg-card shadow-[var(--shadow-dialog)]",
          sizeClass[size],
          className
        )}
        role={role ?? "dialog"}
        tabIndex={-1}
        {...props}
        onKeyDown={handleKeyDown}
      >
        {title || showCloseButton ? (
          <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-4 py-3">
            <div className="min-w-0">
              {title ? (
                <h2 className="text-base font-semibold text-foreground" id={titleId}>
                  {title}
                </h2>
              ) : null}
              {description ? (
                <div className="mt-1 text-sm leading-6 text-muted" id={descriptionId}>
                  {description}
                </div>
              ) : null}
            </div>
            {showCloseButton ? (
              <IconButton
                aria-label="Close dialog"
                className="size-7 shrink-0 border-transparent bg-transparent"
                icon={<X className="size-4" aria-hidden="true" />}
                onClick={onClose}
                size="sm"
                variant="ghost"
              />
            ) : null}
          </div>
        ) : null}
        {children ? <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">{children}</div> : null}
        {footer ? (
          <div className="flex shrink-0 flex-col-reverse gap-2 border-t border-border px-4 py-3 sm:flex-row sm:justify-end">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );

  if (portal && typeof document !== "undefined") {
    return createPortal(content, document.body);
  }

  return content;
}
