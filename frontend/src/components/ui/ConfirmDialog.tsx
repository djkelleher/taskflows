import { useState, useCallback, type ReactNode } from "react";
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

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        handleCancel();
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
        >
          <div
            className="bg-card rounded-lg shadow-xl p-6 max-w-md mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-foreground mb-6 text-lg">{dialog.options.message}</p>
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

