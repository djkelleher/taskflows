import { useState, useCallback, useRef, useEffect, type ReactNode } from "react";
import { Button } from "./Button";
import { ConfirmContext } from "@/contexts/ConfirmContext";
import type { ConfirmDialogOptions } from "@/contexts/ConfirmContext";

interface ConfirmProviderProps {
  children: ReactNode;
}

export function ConfirmProvider({ children }: ConfirmProviderProps) {
  const [dialog, setDialog] = useState<{
    options: ConfirmDialogOptions;
    resolve: (value: boolean) => void;
  } | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousActiveElement = useRef<Element | null>(null);

  const confirm = useCallback((options: ConfirmDialogOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      setDialog({ options, resolve });
    });
  }, []);

  const handleConfirm = useCallback(() => {
    dialog?.resolve(true);
    setDialog(null);
  }, [dialog]);

  const handleCancel = useCallback(() => {
    dialog?.resolve(false);
    setDialog(null);
  }, [dialog]);

  // Focus trap and restore focus on close
  useEffect(() => {
    if (dialog) {
      // Store current active element to restore later
      previousActiveElement.current = document.activeElement;
      // Focus the dialog container
      dialogRef.current?.focus();
    } else if (previousActiveElement.current instanceof HTMLElement) {
      // Restore focus when dialog closes
      previousActiveElement.current.focus();
    }
  }, [dialog]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        handleCancel();
        return;
      }

      // Focus trap: cycle focus within the dialog
      if (e.key === "Tab" && dialogRef.current) {
        const focusableElements = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey && document.activeElement === firstElement) {
          e.preventDefault();
          lastElement?.focus();
        } else if (!e.shiftKey && document.activeElement === lastElement) {
          e.preventDefault();
          firstElement?.focus();
        }
      }
    },
    [handleCancel]
  );

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}
      {dialog && (
        <div
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center"
          onClick={handleCancel}
          onKeyDown={handleKeyDown}
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-dialog-message"
        >
          <div
            ref={dialogRef}
            className="bg-card rounded-lg shadow-xl p-6 max-w-md mx-4"
            onClick={(e) => e.stopPropagation()}
            tabIndex={-1}
          >
            <p id="confirm-dialog-message" className="text-foreground mb-6 text-lg">
              {dialog.options.message}
            </p>
            <div className="flex gap-3 justify-end">
              <Button variant="secondary" onClick={handleCancel}>
                {dialog.options.cancelText || "Cancel"}
              </Button>
              <Button
                variant={dialog.options.variant || "danger"}
                onClick={handleConfirm}
                autoFocus
              >
                {dialog.options.confirmText || "Confirm"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

