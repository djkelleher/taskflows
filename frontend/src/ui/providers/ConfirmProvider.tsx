import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";

import { ConfirmDialog, type ConfirmDialogProps } from "../components/ConfirmDialog";

export interface ConfirmOptions
  extends Pick<
    ConfirmDialogProps,
    | "cancelLabel"
    | "closeOnBackdropClick"
    | "closeOnEscape"
    | "confirmLabel"
    | "description"
    | "initialFocus"
    | "title"
    | "tone"
  > {
  /** Optional rich body rendered below the description. */
  body?: ReactNode;
}

export type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function useConfirm(): ConfirmFn {
  const context = useContext(ConfirmContext);
  if (!context) {
    throw new Error("useConfirm must be used inside a ConfirmProvider");
  }
  return context;
}

interface ConfirmState extends ConfirmOptions {
  open: boolean;
}

export interface ConfirmProviderProps {
  children: ReactNode;
}

/**
 * Provides a promise-based `confirm(options)` API backed by a single
 * ConfirmDialog instance. Resolves true on confirm, false on cancel/dismiss.
 */
export function ConfirmProvider({ children }: ConfirmProviderProps) {
  const [state, setState] = useState<ConfirmState>({ open: false, title: "" });
  const resolveRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((options) => {
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
      setState({ ...options, open: true });
    });
  }, []);

  const settle = useCallback((result: boolean) => {
    setState((current) => ({ ...current, open: false }));
    resolveRef.current?.(result);
    resolveRef.current = null;
  }, []);

  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <ConfirmDialog
        cancelLabel={state.cancelLabel}
        closeOnBackdropClick={state.closeOnBackdropClick}
        closeOnEscape={state.closeOnEscape}
        confirmLabel={state.confirmLabel}
        description={state.description}
        initialFocus={state.initialFocus}
        onCancel={() => settle(false)}
        onConfirm={() => settle(true)}
        open={state.open}
        title={state.title}
        tone={state.tone}
      >
        {state.body}
      </ConfirmDialog>
    </ConfirmContext.Provider>
  );
}
