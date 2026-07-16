import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ToastStack, type ToastMessage, type ToastStackProps } from "../components/Toast";

export interface ToastOptions {
  action?: ReactNode;
  description?: ReactNode;
  /** Auto-dismiss after N ms. Pass 0 or null to keep until dismissed. */
  duration?: number | null;
  /** Provide to control/replace an existing toast. */
  id?: string;
  title: ReactNode;
  tone?: ToastMessage["tone"];
}

export interface ToastContextValue {
  /** Dismiss every visible toast. */
  dismissAll: () => void;
  /** Dismiss a toast by id. */
  dismiss: (id: string) => void;
  /** Show a toast; returns its id. */
  toast: (options: ToastOptions) => string;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used inside a ToastProvider");
  }
  return context;
}

let toastCounter = 0;

export interface ToastProviderProps {
  children: ReactNode;
  /** Default auto-dismiss in ms (0/null = sticky). Defaults to 5000. */
  defaultDuration?: number | null;
  /** Maximum simultaneously visible toasts (oldest dropped). Defaults to 4. */
  max?: number;
  position?: ToastStackProps["position"];
}

/**
 * Provides an imperative toast API and renders the ToastStack. Auto-dismiss
 * timers are cleared on unmount and when toasts are dismissed manually.
 */
export function ToastProvider({
  children,
  defaultDuration = 5000,
  max = 4,
  position = "top-right",
}: ToastProviderProps) {
  const [messages, setMessages] = useState<ToastMessage[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const clearTimer = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const dismiss = useCallback(
    (id: string) => {
      clearTimer(id);
      setMessages((current) => current.filter((message) => message.id !== id));
    },
    [clearTimer]
  );

  const dismissAll = useCallback(() => {
    timers.current.forEach((timer) => clearTimeout(timer));
    timers.current.clear();
    setMessages([]);
  }, []);

  const toast = useCallback(
    ({ duration, id, ...rest }: ToastOptions) => {
      const toastId = id ?? `toast-${++toastCounter}`;
      const message: ToastMessage = { id: toastId, ...rest };

      setMessages((current) => {
        const without = current.filter((existing) => existing.id !== toastId);
        const next = [...without, message];
        return next.length > max ? next.slice(next.length - max) : next;
      });

      clearTimer(toastId);
      const ttl = duration === undefined ? defaultDuration : duration;
      if (ttl) {
        timers.current.set(
          toastId,
          setTimeout(() => dismiss(toastId), ttl)
        );
      }

      return toastId;
    },
    [clearTimer, defaultDuration, dismiss, max]
  );

  useEffect(() => {
    const pending = timers.current;
    return () => {
      pending.forEach((timer) => clearTimeout(timer));
      pending.clear();
    };
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({ dismiss, dismissAll, toast }),
    [dismiss, dismissAll, toast]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastStack messages={messages} onClose={dismiss} position={position} />
    </ToastContext.Provider>
  );
}
