import { createContext } from "react";

export interface ToastContextValue {
  showSuccess: (message: string) => void;
  showError: (message: string) => void;
  showWarning: (message: string) => void;
  showInfo: (message: string) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);
