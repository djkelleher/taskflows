import {
  cloneElement,
  isValidElement,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
  useEffect,
  useId,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { focusableSelector } from "../lib/focus";
import { cx } from "../lib/cx";

interface PopoverCoords {
  left?: number;
  maxHeight?: number;
  right?: number;
  top: number;
}

/** Gap between trigger and panel, and minimum distance from the viewport edge. */
const POPOVER_GAP = 6;
const POPOVER_VIEWPORT_MARGIN = 8;

export interface PopoverProps {
  align?: "start" | "end";
  children: ReactNode;
  className?: string;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Controlled open state. */
  open?: boolean;
  portal?: boolean;
  /** Trigger element; receives click/aria props and a ref. */
  trigger: ReactElement;
}

/**
 * Click-triggered floating panel for arbitrary content (forms, filters, info).
 * Closes on Escape and outside pointer-down, restoring focus to the trigger.
 */
export function Popover({
  align = "start",
  children,
  className,
  defaultOpen = false,
  onOpenChange,
  open: controlledOpen,
  portal = true,
  trigger,
}: PopoverProps) {
  const contentId = useId();
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;
  const triggerRef = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  // Bumped on scroll/resize so the fixed-positioned panel re-reads the trigger
  // rect and stays anchored instead of floating away.
  const [tick, reposition] = useReducer((value: number) => value + 1, 0);
  // Resolved, collision-adjusted coordinates measured after the panel renders.
  const [coords, setCoords] = useState<PopoverCoords | null>(null);

  const setOpen = (next: boolean) => {
    if (!isControlled) {
      setInternalOpen(next);
    }
    onOpenChange?.(next);
  };

  const close = (restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) {
      window.setTimeout(() => triggerRef.current?.focus(), 0);
    }
  };

  useEffect(() => {
    if (!open) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (contentRef.current?.contains(target) || triggerRef.current?.contains(target)) {
        return;
      }
      setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    window.setTimeout(() => {
      const first = contentRef.current?.querySelector<HTMLElement>(focusableSelector);
      (first ?? contentRef.current)?.focus();
    }, 0);
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleReposition = () => reposition();
    // Capture phase catches scrolls in any ancestor scroll container.
    window.addEventListener("scroll", handleReposition, true);
    window.addEventListener("resize", handleReposition);
    return () => {
      window.removeEventListener("scroll", handleReposition, true);
      window.removeEventListener("resize", handleReposition);
    };
  }, [open]);

  // Measure the panel against the viewport and resolve collision-adjusted
  // coordinates: flip above the trigger when there is not enough room below,
  // clamp horizontal overflow, and bound the height so a tall panel scrolls
  // instead of running off-screen. Runs in a layout effect (before paint) so
  // the corrected position is applied without a visible flicker, and re-runs on
  // scroll/resize (via `tick`) to stay anchored.
  useLayoutEffect(() => {
    if (!open) {
      setCoords(null);
      return;
    }
    const trigger = triggerRef.current;
    const content = contentRef.current;
    if (!trigger) {
      return;
    }
    const tr = trigger.getBoundingClientRect();
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;
    const contentH = content?.offsetHeight ?? 0;
    const contentW = content?.offsetWidth ?? 0;

    const spaceBelow = viewportH - tr.bottom;
    const spaceAbove = tr.top;
    // Flip up only when the panel measurably won't fit below but fits better above.
    const flipUp =
      contentH > 0 &&
      spaceBelow < contentH + POPOVER_GAP + POPOVER_VIEWPORT_MARGIN &&
      spaceAbove > spaceBelow;
    const top = flipUp
      ? Math.max(POPOVER_VIEWPORT_MARGIN, tr.top - POPOVER_GAP - contentH)
      : tr.bottom + POPOVER_GAP;
    const maxHeight =
      (flipUp ? spaceAbove : spaceBelow) - POPOVER_GAP - POPOVER_VIEWPORT_MARGIN;

    let left: number | undefined;
    let right: number | undefined;
    if (align === "end") {
      right = Math.max(POPOVER_VIEWPORT_MARGIN, viewportW - tr.right);
      if (contentW > 0 && viewportW - right - contentW < POPOVER_VIEWPORT_MARGIN) {
        right = Math.max(POPOVER_VIEWPORT_MARGIN, viewportW - contentW - POPOVER_VIEWPORT_MARGIN);
      }
    } else {
      left = tr.left;
      if (contentW > 0 && left + contentW > viewportW - POPOVER_VIEWPORT_MARGIN) {
        left = Math.max(POPOVER_VIEWPORT_MARGIN, viewportW - contentW - POPOVER_VIEWPORT_MARGIN);
      }
    }

    setCoords({
      left,
      maxHeight: maxHeight > 0 ? maxHeight : undefined,
      right,
      top,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, align, tick]);

  const triggerEl = isValidElement(trigger)
    ? cloneElement(trigger as ReactElement<Record<string, unknown>>, {
        "aria-controls": open ? contentId : undefined,
        "aria-expanded": open,
        "aria-haspopup": "dialog",
        onClick: (event: MouseEvent<HTMLElement>) => {
          (trigger.props as { onClick?: (e: MouseEvent<HTMLElement>) => void }).onClick?.(event);
          if (!event.defaultPrevented) {
            setOpen(!open);
          }
        },
        ref: (node: HTMLElement | null) => {
          triggerRef.current = node;
        },
      })
    : trigger;

  const rect = open ? triggerRef.current?.getBoundingClientRect() : undefined;
  // Fallback (downward) position used for the first measurement pass; the layout
  // effect immediately replaces it with collision-adjusted coords before paint.
  const fallback: PopoverCoords | undefined = rect
    ? {
        left: align === "end" ? undefined : rect.left,
        right: align === "end" ? Math.max(POPOVER_VIEWPORT_MARGIN, window.innerWidth - rect.right) : undefined,
        top: rect.bottom + POPOVER_GAP,
      }
    : undefined;
  const positionStyle = coords ?? fallback;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    }
  };

  const content =
    open && rect ? (
      <div
        ref={contentRef}
        className={cx(
          "fixed z-50 min-w-48 overflow-y-auto rounded-md border border-border bg-card p-3 text-sm text-foreground shadow-[var(--shadow-popover)]",
          className
        )}
        id={contentId}
        onKeyDown={handleKeyDown}
        role="dialog"
        style={positionStyle}
        tabIndex={-1}
      >
        {children}
      </div>
    ) : null;

  return (
    <>
      {triggerEl}
      {content && portal && typeof document !== "undefined"
        ? createPortal(content, document.body)
        : content}
    </>
  );
}
