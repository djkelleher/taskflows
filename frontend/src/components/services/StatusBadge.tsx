import { Badge } from "@/components/ui";
import type { ServiceStatus } from "@/types";

interface StatusBadgeProps {
  status: ServiceStatus;
}

type BadgeVariant = "success" | "muted" | "danger";

const statusConfig: Record<string, { label: string; variant: BadgeVariant }> = {
  running: { label: "Running", variant: "success" },
  active: { label: "Running", variant: "success" },
  stopped: { label: "Stopped", variant: "muted" },
  inactive: { label: "Stopped", variant: "muted" },
  failed: { label: "Failed", variant: "danger" },
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status];

  if (config) {
    return <Badge variant={config.variant}>{config.label}</Badge>;
  }

  return <Badge variant="muted">{status || "Unknown"}</Badge>;
}
