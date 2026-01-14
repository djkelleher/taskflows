import { useState } from "react";
import { Button, useToast, useConfirm } from "@/components/ui";
import { useBatchAction } from "@/hooks/useServices";
import { useServiceStore } from "@/stores/serviceStore";
import type { BatchOperation } from "@/types";

export function BatchActions() {
  const { showSuccess, showError } = useToast();
  const confirm = useConfirm();
  const batchActionMutation = useBatchAction();
  const { selectedServices, clearSelection } = useServiceStore();
  const [actionInProgress, setActionInProgress] = useState<BatchOperation | null>(null);

  const selectedCount = selectedServices.size;
  const hasSelection = selectedCount > 0;

  const handleBatchAction = async (operation: BatchOperation) => {
    if (!hasSelection) return;

    const serviceNames = Array.from(selectedServices);

    // Confirm for destructive actions
    if (operation === "stop" || operation === "restart") {
      const confirmed = await confirm({
        message: `Are you sure you want to ${operation} ${selectedCount} service(s)?`,
        confirmText: operation.charAt(0).toUpperCase() + operation.slice(1),
        cancelText: "Cancel",
        variant: operation === "stop" ? "danger" : "primary",
      });
      if (!confirmed) return;
    }

    setActionInProgress(operation);
    try {
      await batchActionMutation.mutateAsync({ serviceNames, operation });
      showSuccess(`Batch ${operation} initiated for ${selectedCount} service(s)`);
      clearSelection();
    } catch (error) {
      console.error(`Failed to ${operation} services:`, error);
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      showError(`Failed to ${operation} selected services: ${errorMessage}`);
    } finally {
      setActionInProgress(null);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-muted">
        {selectedCount} selected
      </span>
      <Button
        variant="success"
        size="sm"
        disabled={!hasSelection || actionInProgress !== null}
        loading={actionInProgress === "start"}
        onClick={() => handleBatchAction("start")}
      >
        Start
      </Button>
      <Button
        variant="danger"
        size="sm"
        disabled={!hasSelection || actionInProgress !== null}
        loading={actionInProgress === "stop"}
        onClick={() => handleBatchAction("stop")}
      >
        Stop
      </Button>
      <Button
        variant="primary"
        size="sm"
        disabled={!hasSelection || actionInProgress !== null}
        loading={actionInProgress === "restart"}
        onClick={() => handleBatchAction("restart")}
      >
        Restart
      </Button>
    </div>
  );
}
