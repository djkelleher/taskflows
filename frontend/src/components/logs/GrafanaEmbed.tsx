import { useMemo, useState } from "react";
import { LoadingSpinner } from "@/components/ui";

interface GrafanaEmbedProps {
  serviceName: string;
  level: string;
  from: string;
  to: string;
  theme: "dark" | "light";
}

export function GrafanaEmbed({ serviceName, level, from, to, theme }: GrafanaEmbedProps) {
  const [loading, setLoading] = useState(true);

  const src = useMemo(() => {
    const params = new URLSearchParams({
      orgId: "1",
      panelId: "1",
      "var-service_name": serviceName,
      "var-level": level,
      from,
      to,
      theme,
    });
    return `/grafana/d-solo/taskflows-service-logs/taskflows-service-logs?${params.toString()}`;
  }, [serviceName, level, from, to, theme]);

  return (
    <div className="relative w-full h-full">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-card rounded-lg z-10">
          <LoadingSpinner label="Loading Grafana panel..." />
        </div>
      )}
      <iframe
        key={src}
        src={src}
        className="w-full h-full border-0 rounded-lg"
        onLoad={() => setLoading(false)}
      />
    </div>
  );
}
