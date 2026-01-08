import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Checkbox } from "@/components/ui";
import { StatusBadge } from "./StatusBadge";
import { useServiceAction } from "@/hooks/useServices";
import { useToast } from "@/components/ui";
import type { Service } from "@/types";

interface ServiceRowProps {
  service: Service;
  isSelected: boolean;
  onToggleSelect: (name: string) => void;
}

export function ServiceRow({ service, isSelected, onToggleSelect }: ServiceRowProps) {
  const navigate = useNavigate();
  const { showSuccess, showError } = useToast();
  const serviceActionMutation = useServiceAction();
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  const isRunning = service.status === "running" || service.status === "active";

  const handleAction = async (action: "start" | "stop" | "restart") => {
    setActionInProgress(action);
    try {
      await serviceActionMutation.mutateAsync({ serviceName: service.name, action });
      showSuccess(`Service ${service.name} ${action} initiated`);
    } catch {
      showError(`Failed to ${action} service ${service.name}`);
    } finally {
      setActionInProgress(null);
    }
  };

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3">
        <Checkbox
          checked={isSelected}
          onChange={() => onToggleSelect(service.name)}
        />
      </td>
      <td className="px-4 py-3 text-sm font-medium text-foreground">
        {service.name}
      </td>
      <td className="px-4 py-3 text-sm">
        <StatusBadge status={service.status} />
      </td>
      <td className="px-4 py-3 text-sm text-muted">
        {service.schedule || "-"}
      </td>
      <td className="px-4 py-3 text-sm text-muted">
        {service.last_run || "-"}
      </td>
      <td className="px-4 py-3 text-sm">
        <div className="flex gap-2">
          {isRunning ? (
            <>
              <Button
                variant="danger"
                size="sm"
                loading={actionInProgress === "stop"}
                disabled={actionInProgress !== null}
                onClick={() => handleAction("stop")}
              >
                Stop
              </Button>
              <Button
                variant="primary"
                size="sm"
                loading={actionInProgress === "restart"}
                disabled={actionInProgress !== null}
                onClick={() => handleAction("restart")}
              >
                Restart
              </Button>
            </>
          ) : (
            <Button
              variant="success"
              size="sm"
              loading={actionInProgress === "start"}
              disabled={actionInProgress !== null}
              onClick={() => handleAction("start")}
            >
              Start
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate(`/logs/${service.name}`)}
          >
            Logs
          </Button>
        </div>
      </td>
    </tr>
  );
}
