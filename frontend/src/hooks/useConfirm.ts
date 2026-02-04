import { useContext } from "react";
import { ConfirmContext, type ConfirmDialogOptions } from "@/contexts/ConfirmContext";

export function useConfirm(): (options: ConfirmDialogOptions) => Promise<boolean> {
  const context = useContext(ConfirmContext);
  if (!context) {
    throw new Error("useConfirm must be used within a ConfirmProvider");
  }
  return context.confirm;
}
