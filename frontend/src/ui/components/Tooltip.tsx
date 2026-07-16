import {
  cloneElement,
  isValidElement,
  type FocusEvent,
  type HTMLAttributes,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { cx } from "../lib/cx";

export type TooltipSide = "top" | "bottom" | "left" | "right";

export interface TooltipProps extends Omit<HTMLAttributes<HTMLSpanElement>, "content"> {
  /** The element that triggers the tooltip. Must accept a ref/aria props. */
  children: ReactElement;
  content: ReactNode;
  /** Delay before showing on hover, in ms. Defaults to 150. */
  openDelay?: number;
  side?: TooltipSide;
}

const sideClass: Record<TooltipSide, string> = {
  top: "bottom-full left-1/2 mb-1.5 -translate-x-1/2",
  bottom: "top-full left-1/2 mt-1.5 -translate-x-1/2",
  left: "right-full top-1/2 mr-1.5 -translate-y-1/2",
  right: "left-full top-1/2 ml-1.5 -translate-y-1/2",
};

/**
 * Lightweight hover/focus tooltip. The trigger child is described by the
 * tooltip via aria-describedby; the bubble itself is aria-hidden.
 */
export function Tooltip({
  children,
  className,
  content,
  openDelay = 150,
  side = "top",
  ...props
}: TooltipProps) {
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const show = () => {
    clearTimer();
    timerRef.current = setTimeout(() => setOpen(true), openDelay);
  };

  const hide = () => {
    clearTimer();
    setOpen(false);
  };

  // Clear any pending show-timer if the trigger unmounts mid-delay.
  useEffect(() => clearTimer, []);

  if (!isValidElement(children)) {
    return children;
  }

  const child = children as ReactElement<{
    "aria-describedby"?: string;
    onBlur?: (event: FocusEvent) => void;
    onFocus?: (event: FocusEvent) => void;
    onKeyDown?: (event: KeyboardEvent) => void;
    onMouseEnter?: (event: MouseEvent) => void;
    onMouseLeave?: (event: MouseEvent) => void;
  }>;
  const childProps = child.props;

  const trigger = cloneElement(child, {
    "aria-describedby": open ? tooltipId : childProps["aria-describedby"],
    onBlur: (event: FocusEvent) => {
      childProps.onBlur?.(event);
      hide();
    },
    onFocus: (event: FocusEvent) => {
      childProps.onFocus?.(event);
      show();
    },
    onKeyDown: (event: KeyboardEvent) => {
      childProps.onKeyDown?.(event);
      if (event.key === "Escape") {
        hide();
      }
    },
    onMouseEnter: (event: MouseEvent) => {
      childProps.onMouseEnter?.(event);
      show();
    },
    onMouseLeave: (event: MouseEvent) => {
      childProps.onMouseLeave?.(event);
      hide();
    },
  });

  return (
    <span className={cx("relative inline-flex", className)} {...props}>
      {trigger}
      {open ? (
        <span
          className={cx(
            "pointer-events-none absolute z-50 w-max max-w-xs rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground shadow-[var(--shadow-popover)]",
            sideClass[side]
          )}
          id={tooltipId}
          role="tooltip"
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}
