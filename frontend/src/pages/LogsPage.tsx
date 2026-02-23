import { useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { Header } from "@/components/layout";
import { GrafanaEmbed, DateRangePicker, LogLevelFilter } from "@/components/logs";
import type { TimeRange } from "@/components/logs";
import { useTheme } from "@/hooks/useTheme";
import { ArrowLeft, ExternalLink } from "lucide-react";

const DEFAULT_TIME_RANGE: TimeRange = {
  from: "now-1h",
  to: "now",
  label: "Last 1 hour",
};

export function LogsPage() {
  const { serviceName } = useParams<{ serviceName: string }>();
  const { theme } = useTheme();
  const [timeRange, setTimeRange] = useState<TimeRange>(DEFAULT_TIME_RANGE);
  const [level, setLevel] = useState(".*");

  const handleTimeRangeChange = useCallback((range: TimeRange) => {
    setTimeRange(range);
  }, []);

  const handleLevelChange = useCallback((newLevel: string) => {
    setLevel(newLevel);
  }, []);

  if (!serviceName) {
    return (
      <>
        <Header title="Logs" />
        <div className="flex-1 p-6 flex items-center justify-center text-muted">
          No service specified
        </div>
      </>
    );
  }

  const grafanaUrl = `/grafana/d/taskflows-service-logs/taskflows-service-logs?orgId=1&var-service_name=${encodeURIComponent(serviceName)}&var-level=${encodeURIComponent(level)}&from=${timeRange.from}&to=${timeRange.to}`;

  return (
    <>
      <Header
        title={`Logs: ${serviceName}`}
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Logs" },
        ]}
        actions={
          <Link
            to="/"
            className="flex items-center gap-2 text-sm text-muted hover:text-foreground"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
        }
      />
      <div className="flex-1 p-6 overflow-hidden flex flex-col gap-4">
        {/* Query toolbar */}
        <div className="flex items-center gap-3 flex-shrink-0">
          <DateRangePicker value={timeRange} onChange={handleTimeRangeChange} />
          <LogLevelFilter value={level} onChange={handleLevelChange} />
          <div className="flex-1" />
          <a
            href={grafanaUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm text-muted hover:text-foreground transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Open in Grafana
          </a>
        </div>

        {/* Grafana embed */}
        <div className="flex-1 min-h-0">
          <GrafanaEmbed
            serviceName={serviceName}
            level={level}
            from={timeRange.from}
            to={timeRange.to}
            theme={theme}
          />
        </div>
      </div>
    </>
  );
}
