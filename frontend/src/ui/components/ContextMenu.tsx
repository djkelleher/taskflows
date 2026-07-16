import {
  cloneElement,
  createContext,
  forwardRef,
  isValidElement,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { cx } from "../lib/cx";

type ContextMenuInitialFocus = "first" | "last";

interface ContextMenuCloseOptions {
  restoreFocus?: boolean;
}

interface ContextMenuRootValue {
  close: (options?: ContextMenuCloseOptions) => void;
  contentId: string;
  initialFocus: ContextMenuInitialFocus;
  open: boolean;
  setInitialFocus: (focus: ContextMenuInitialFocus) => void;
  setOpen: (open: boolean, initialFocus?: ContextMenuInitialFocus) => void;
  setTrigger: (element: HTMLElement | null) => void;
  trigger: HTMLElement | null;
}

const ContextMenuRootContext = createContext<ContextMenuRootValue | null>(null);

function useContextMenuRoot(component: string) {
  const context = useContext(ContextMenuRootContext);
  if (!context) {
    throw new Error(`${component} must be used inside ContextMenuRoot`);
  }
  return context;
}

export interface ContextMenuRootProps {
  children: ReactNode;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  open?: boolean;
}

export function ContextMenuRoot({ children, defaultOpen = false, onOpenChange, open }: ContextMenuRootProps) {
  const contentId = useId();
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const [initialFocus, setInitialFocus] = useState<ContextMenuInitialFocus>("first");
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const currentOpen = open ?? internalOpen;

  const setOpen = (nextOpen: boolean, nextInitialFocus: ContextMenuInitialFocus = "first") => {
    if (nextOpen) {
      setInitialFocus(nextInitialFocus);
    }
    setInternalOpen(nextOpen);
    onOpenChange?.(nextOpen);
  };

  const close = ({ restoreFocus = false }: ContextMenuCloseOptions = {}) => {
    setOpen(false);
    if (restoreFocus) {
      window.setTimeout(() => trigger?.focus(), 0);
    }
  };

  return (
    <ContextMenuRootContext.Provider
      value={{
        close,
        contentId,
        initialFocus,
        open: currentOpen,
        setInitialFocus,
        setOpen,
        setTrigger,
        trigger,
      }}
    >
      {children}
    </ContextMenuRootContext.Provider>
  );
}

export interface ContextMenuTriggerProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
  children?: ReactNode;
}

export const ContextMenuTrigger = forwardRef<HTMLButtonElement, ContextMenuTriggerProps>(
  function ContextMenuTrigger({ asChild = false, children, onClick, onKeyDown, ...props }, ref) {
    const { contentId, open, setOpen, setTrigger } = useContextMenuRoot("ContextMenuTrigger");

    const triggerProps = {
      "aria-controls": open ? contentId : undefined,
      "aria-expanded": open,
      "aria-haspopup": "menu" as const,
      onClick: (event: MouseEvent<HTMLElement>) => {
        onClick?.(event as MouseEvent<HTMLButtonElement>);
        if (!event.defaultPrevented) {
          setOpen(!open, "first");
        }
      },
      onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
        onKeyDown?.(event as KeyboardEvent<HTMLButtonElement>);
        if (event.defaultPrevented) {
          return;
        }

        if (event.key === "ArrowDown") {
          event.preventDefault();
          setOpen(true, "first");
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          setOpen(true, "last");
        } else if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setOpen(true, "first");
        }
      },
      ref: (node: HTMLElement | null) => {
        setTrigger(node);
        if (typeof ref === "function") {
          ref(node as HTMLButtonElement | null);
        } else if (ref) {
          ref.current = node as HTMLButtonElement | null;
        }
      },
    };

    if (asChild && isValidElement(children)) {
      return cloneElement(children as ReactElement<Record<string, unknown>>, {
        ...props,
        ...triggerProps,
      });
    }

    return (
      <button type="button" {...props} {...triggerProps}>
        {children}
      </button>
    );
  }
);

export interface ContextMenuProps extends HTMLAttributes<HTMLDivElement> {
  align?: "start" | "end";
  portal?: boolean;
}

function getEnabledMenuItems(menu: HTMLElement) {
  return Array.from(menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')).filter(
    (item) => !item.disabled && item.getAttribute("aria-disabled") !== "true"
  );
}

export const ContextMenu = forwardRef<HTMLDivElement, ContextMenuProps>(function ContextMenu(
  { align = "start", className, portal = true, style, ...props },
  ref
) {
  const root = useContext(ContextMenuRootContext);
  const localRef = useRef<HTMLDivElement | null>(null);

  const setRefs = (node: HTMLDivElement | null) => {
    localRef.current = node;
    if (typeof ref === "function") {
      ref(node);
    } else if (ref) {
      ref.current = node;
    }
  };

  useEffect(() => {
    if (!root?.open) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (localRef.current?.contains(target) || root.trigger?.contains(target)) {
        return;
      }
      root.close();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [root]);

  useEffect(() => {
    if (!root?.open) {
      return;
    }

    window.setTimeout(() => {
      const items = localRef.current ? getEnabledMenuItems(localRef.current) : [];
      if (items.length === 0) {
        localRef.current?.focus();
        return;
      }
      const item = root.initialFocus === "last" ? items[items.length - 1] : items[0];
      item.focus();
    }, 0);
  }, [root?.initialFocus, root?.open]);

  if (root && !root.open) {
    return null;
  }

  const rect = root?.trigger?.getBoundingClientRect();
  const positionStyle = rect
    ? {
        left: align === "end" ? undefined : rect.left,
        right: align === "end" ? Math.max(8, window.innerWidth - rect.right) : undefined,
        top: rect.bottom + 6,
      }
    : undefined;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    props.onKeyDown?.(event);
    if (event.defaultPrevented) {
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      root?.close({ restoreFocus: true });
      return;
    }

    const items = getEnabledMenuItems(event.currentTarget);
    if (items.length === 0) {
      return;
    }

    const currentIndex = Math.max(0, items.findIndex((item) => item === document.activeElement));
    let nextIndex = currentIndex;

    if (event.key === "ArrowDown") {
      nextIndex = currentIndex >= items.length - 1 ? 0 : currentIndex + 1;
    } else if (event.key === "ArrowUp") {
      nextIndex = currentIndex <= 0 ? items.length - 1 : currentIndex - 1;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = items.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    items[nextIndex].focus();
  };

  const content = (
    <div
      ref={setRefs}
      className={cx(
        "z-50 min-w-48 rounded-md border border-border bg-card p-2 text-sm shadow-[var(--shadow-popover)]",
        rect && "fixed",
        className
      )}
      id={root?.contentId}
      role="menu"
      style={{ ...positionStyle, ...style }}
      tabIndex={-1}
      {...props}
      onKeyDown={handleKeyDown}
    />
  );

  if (portal && root && typeof document !== "undefined") {
    return createPortal(content, document.body);
  }

  return content;
});

export interface ContextMenuItemProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  leftIcon?: ReactNode;
  onSelect?: () => void;
  tone?: "default" | "danger";
}

export const ContextMenuItem = forwardRef<HTMLButtonElement, ContextMenuItemProps>(
  function ContextMenuItem(
    { children, className, leftIcon, onClick, onSelect, tone = "default", type = "button", ...props },
    ref
  ) {
    const root = useContext(ContextMenuRootContext);

    return (
      <button
        ref={ref}
        className={cx(
          "flex min-h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          "disabled:cursor-not-allowed disabled:opacity-50",
          tone === "danger"
            ? "text-negative hover:bg-negative/10"
            : "text-foreground hover:bg-background",
          className
        )}
        role="menuitem"
        tabIndex={-1}
        type={type}
        {...props}
        onClick={(event) => {
          onClick?.(event);
          if (!event.defaultPrevented) {
            onSelect?.();
            root?.close({ restoreFocus: true });
          }
        }}
      >
        {leftIcon}
        <span className="min-w-0 flex-1 truncate">{children}</span>
      </button>
    );
  }
);

export interface ContextMenuSeparatorProps extends HTMLAttributes<HTMLDivElement> {}

export function ContextMenuSeparator({ className, ...props }: ContextMenuSeparatorProps) {
  return <div className={cx("my-1 h-px bg-border", className)} role="separator" {...props} />;
}
