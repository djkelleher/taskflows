import { Badge } from "@/components/ui";
import type { ServiceStatus } from "@/types";

interface StatusBadgeProps {
  status: ServiceStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  if (status === "running" || status === "active") {
    return <Badge variant="success">Running</Badge>;
  }

  if (status === "stopped" || status === "inactive") {
    return <Badge variant="muted">Stopped</Badge>;
  }

  if (status === "failed") {
    return <Badge variant="danger">Failed</Badge>;
  }

  return <Badge variant="muted">{status || "Unknown"}</Badge>;
}
