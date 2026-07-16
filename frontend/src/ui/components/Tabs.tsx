import {
  createContext,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  useContext,
  useId,
  useMemo,
  useState,
} from "react";

import { cx } from "../lib/cx";

interface TabsContextValue {
  activationMode: "automatic" | "manual";
  baseId: string;
  onValueChange: (value: string) => void;
  value: string;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabsContext(component: string) {
  const context = useContext(TabsContext);
  if (!context) {
    throw new Error(`${component} must be used inside Tabs`);
  }
  return context;
}

export interface TabsProps extends Omit<HTMLAttributes<HTMLDivElement>, "defaultValue" | "onChange"> {
  activationMode?: "automatic" | "manual";
  children: ReactNode;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  value?: string;
}

export function Tabs({
  activationMode = "automatic",
  children,
  className,
  defaultValue,
  id,
  onValueChange,
  value,
  ...props
}: TabsProps) {
  const generatedId = useId();
  const baseId = id ?? generatedId;
  const [internalValue, setInternalValue] = useState(defaultValue ?? "");
  const currentValue = value ?? internalValue;

  const context = useMemo<TabsContextValue>(
    () => ({
      activationMode,
      baseId,
      onValueChange: (nextValue) => {
        setInternalValue(nextValue);
        onValueChange?.(nextValue);
      },
      value: currentValue,
    }),
    [activationMode, baseId, currentValue, onValueChange]
  );

  return (
    <TabsContext.Provider value={context}>
      <div className={cx("min-w-0", className)} id={id} {...props}>
        {children}
      </div>
    </TabsContext.Provider>
  );
}

export interface TabListProps extends HTMLAttributes<HTMLDivElement> {}

function getEnabledTabs(tabList: HTMLElement) {
  return Array.from(tabList.querySelectorAll<HTMLButtonElement>('[role="tab"]')).filter(
    (tab) => !tab.disabled && tab.getAttribute("aria-disabled") !== "true"
  );
}

export function TabList({ children, className, onKeyDown, ...props }: TabListProps) {
  const { activationMode, onValueChange } = useTabsContext("TabList");

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented) {
      return;
    }

    const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
    if (!keys.includes(event.key)) {
      return;
    }

    const tabs = getEnabledTabs(event.currentTarget);
    if (tabs.length === 0) {
      return;
    }

    const active = document.activeElement;
    const currentIndex = Math.max(0, tabs.findIndex((tab) => tab === active));
    let nextIndex = currentIndex;

    if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = currentIndex <= 0 ? tabs.length - 1 : currentIndex - 1;
    } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = currentIndex >= tabs.length - 1 ? 0 : currentIndex + 1;
    }

    event.preventDefault();
    const nextTab = tabs[nextIndex];
    nextTab.focus();
    if (activationMode === "automatic") {
      const value = nextTab.dataset.value;
      if (value) {
        onValueChange(value);
      }
    }
  };

  return (
    <div
      className={cx("flex items-center gap-1 border-b border-border", className)}
      onKeyDown={handleKeyDown}
      role="tablist"
      {...props}
    >
      {children}
    </div>
  );
}

export interface TabProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  disabled?: boolean;
  value: string;
}

export function Tab({ children, className, disabled = false, value, ...props }: TabProps) {
  const { baseId, onValueChange, value: activeValue } = useTabsContext("Tab");
  const selected = value === activeValue;

  return (
    <button
      aria-controls={`${baseId}-panel-${value}`}
      aria-disabled={disabled || undefined}
      aria-selected={selected}
      className={cx(
        "inline-flex min-h-9 items-center justify-center border-b-2 px-3 text-sm font-semibold transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2",
        selected
          ? "border-accent text-accent"
          : "border-transparent text-muted hover:border-border hover:text-foreground",
        disabled && "cursor-not-allowed opacity-50 hover:border-transparent hover:text-muted",
        className
      )}
      data-value={value}
      disabled={disabled}
      id={`${baseId}-tab-${value}`}
      role="tab"
      tabIndex={selected ? 0 : -1}
      type="button"
      {...props}
      onClick={(event) => {
        props.onClick?.(event);
        if (!event.defaultPrevented && !disabled) {
          onValueChange(value);
        }
      }}
    >
      {children}
    </button>
  );
}

export interface TabPanelProps extends HTMLAttributes<HTMLDivElement> {
  value: string;
}

export function TabPanel({ children, className, value, ...props }: TabPanelProps) {
  const { baseId, value: activeValue } = useTabsContext("TabPanel");
  const selected = value === activeValue;

  return (
    <div
      aria-labelledby={`${baseId}-tab-${value}`}
      className={cx("min-w-0 pt-4", !selected && "hidden", className)}
      hidden={!selected}
      id={`${baseId}-panel-${value}`}
      role="tabpanel"
      tabIndex={0}
      {...props}
    >
      {children}
    </div>
  );
}
