import { Monitor, Moon, Sun } from "lucide-react";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { cx } from "../lib/cx";
import { IconButton, type IconButtonProps } from "../components/Button";

export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export interface ThemeContextValue {
  /** Resolved concrete theme actually applied to the document. */
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: Theme) => void;
  /** Cycles light -> dark -> system -> light. */
  toggleTheme: () => void;
  /** The user's selected preference (may be "system"). */
  theme: Theme;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside a ThemeProvider");
  }
  return context;
}

const SYSTEM_QUERY = "(prefers-color-scheme: dark)";

function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || !window.matchMedia) {
    return "light";
  }
  return window.matchMedia(SYSTEM_QUERY).matches ? "dark" : "light";
}

function resolveTheme(theme: Theme): ResolvedTheme {
  return theme === "system" ? getSystemTheme() : theme;
}

/** Reflect the resolved theme onto <html> via the chosen attribute strategy. */
function applyThemeToDocument(resolved: ResolvedTheme, attribute: "class" | "data-theme"): void {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  if (attribute === "class") {
    root.classList.toggle("dark", resolved === "dark");
  } else {
    root.setAttribute("data-theme", resolved);
  }
}

export interface ThemeProviderProps {
  /** Class applied to the documentElement when resolved theme is dark. */
  attribute?: "class" | "data-theme";
  children: ReactNode;
  defaultTheme?: Theme;
  /** Disable persistence by passing null. */
  storageKey?: string | null;
}

/**
 * Applies the resolved theme to <html> (via `data-theme="dark"` or `.dark`),
 * persists the preference, and tracks the system preference when theme="system".
 */
export function ThemeProvider({
  attribute = "data-theme",
  children,
  defaultTheme = "system",
  storageKey = "danklab-theme",
}: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === "undefined" || !storageKey) {
      return defaultTheme;
    }
    const stored = window.localStorage.getItem(storageKey);
    return stored === "light" || stored === "dark" || stored === "system" ? stored : defaultTheme;
  });

  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() => resolveTheme(theme));

  // Apply the resolved theme to the document element.
  useEffect(() => {
    const resolved = resolveTheme(theme);
    setResolvedTheme(resolved);
    applyThemeToDocument(resolved, attribute);
  }, [attribute, theme]);

  // Track system preference changes while theme === "system".
  useEffect(() => {
    if (theme !== "system" || typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    const media = window.matchMedia(SYSTEM_QUERY);
    const handleChange = () => {
      const resolved = getSystemTheme();
      setResolvedTheme(resolved);
      applyThemeToDocument(resolved, attribute);
    };
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, [attribute, theme]);

  const setTheme = useCallback(
    (next: Theme) => {
      setThemeState(next);
      if (typeof window !== "undefined" && storageKey) {
        window.localStorage.setItem(storageKey, next);
      }
    },
    [storageKey]
  );

  const toggleTheme = useCallback(() => {
    setTheme(theme === "light" ? "dark" : theme === "dark" ? "system" : "light");
  }, [setTheme, theme]);

  const value = useMemo<ThemeContextValue>(
    () => ({ resolvedTheme, setTheme, theme, toggleTheme }),
    [resolvedTheme, setTheme, theme, toggleTheme]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

const themeIcon: Record<Theme, ReactNode> = {
  light: <Sun className="size-4" aria-hidden="true" />,
  dark: <Moon className="size-4" aria-hidden="true" />,
  system: <Monitor className="size-4" aria-hidden="true" />,
};

const themeLabel: Record<Theme, string> = {
  light: "Light theme",
  dark: "Dark theme",
  system: "System theme",
};

export interface ThemeToggleProps extends Omit<IconButtonProps, "aria-label" | "icon"> {
  "aria-label"?: string;
}

/** Icon button that cycles light -> dark -> system. Requires a ThemeProvider ancestor. */
export function ThemeToggle({ className, ...props }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  return (
    <IconButton
      aria-label={`${themeLabel[theme]} (click to change)`}
      className={cx(className)}
      icon={themeIcon[theme]}
      onClick={toggleTheme}
      variant="ghost"
      {...props}
    />
  );
}
