import { Checkbox } from "@/components/ui";
import { StatusBadge } from "./StatusBadge";
import { Badge } from "@/components/ui";
import { useServiceStore } from "@/stores/serviceStore";
import type { Service } from "@/types";
import type { ColumnDefinition } from "./columns";

interface ServiceRowProps {
  service: Service;
  isSelected: boolean;
  onToggleSelect: (name: string) => void;
  columns: ColumnDefinition[];
}

const TIME_COLUMNS = ["last_run", "last_finish", "next_start"];

function formatTime(value: string, timezone: string): string {
  if (!value || value === "-") return "-";

  try {
    const date = new Date(value);
    if (isNaN(date.getTime())) return value;

    return date.toLocaleString("en-US", {
      timeZone: timezone,
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return value;
  }
}

function RenderCell({ service, col }: { service: Service; col: ColumnDefinition }) {
  const timezone = useServiceStore((state) => state.timezone);

  if (col.id === "status") {
    return <StatusBadge status={service.status} />;
  }
  if (col.id === "name") {
    return <span className="font-medium text-electric-blue">{service.name}</span>;
  }

  const value = col.accessor(service);

  // Format time columns with timezone
  if (TIME_COLUMNS.includes(col.id)) {
    const formatted = formatTime(value, timezone);
    return <span className="text-electric-blue">{formatted}</span>;
  }

  if (col.colorMap && value !== "-") {
    const variant = col.colorMap[value] ?? "muted";
    return <Badge variant={variant}>{value}</Badge>;
  }

  return <span className="text-electric-blue">{value}</span>;
}

export function ServiceRow({ service, isSelected, onToggleSelect, columns }: ServiceRowProps) {
  return (
    <tr className="hover:bg-muted/30">
      <td className="px-4 py-3">
        <Checkbox
          checked={isSelected}
          onChange={() => onToggleSelect(service.name)}
        />
      </td>
      {columns.map((col) => (
        <td key={col.id} className="px-4 py-3 text-sm">
          <RenderCell service={service} col={col} />
        </td>
      ))}
    </tr>
  );
}
