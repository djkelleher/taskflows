import { useState, useRef, useEffect, useMemo } from "react";
import { useDebounce } from "use-debounce";
import { Button, Input, Select, Card, CardHeader, CardContent, LoadingSpinner } from "@/components/ui";
import { useLogs } from "@/hooks/useLogs";
import { Search, Download, RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

interface LogViewerProps {
  serviceName: string;
}

const LINE_COUNT_OPTIONS = [
  { value: "100", label: "100 lines" },
  { value: "500", label: "500 lines" },
  { value: "1000", label: "1000 lines" },
  { value: "5000", label: "5000 lines" },
];

export function LogViewer({ serviceName }: LogViewerProps) {
  const [lineCount, setLineCount] = useState(1000);
  const [searchQuery, setSearchQuery] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const logContainerRef = useRef<HTMLPreElement>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, isFetching } = useLogs(serviceName, lineCount);
  const [debouncedSearch] = useDebounce(searchQuery, 300);

  const logs = data?.logs || "";

  // Memoize line splitting separately from filtering for better performance
  const logLines = useMemo(() => logs.split("\n"), [logs]);

  const filteredLogs = useMemo(() => {
    if (!debouncedSearch) return logs;
    const searchLower = debouncedSearch.toLowerCase();
    return logLines
      .filter((line) => line.toLowerCase().includes(searchLower))
      .join("\n");
  }, [logs, logLines, debouncedSearch]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [filteredLogs, autoScroll]);

  // Detect manual scrolling and disable auto-scroll if user scrolls up
  useEffect(() => {
    const container = logContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const isAtBottom =
        container.scrollHeight - container.scrollTop <= container.clientHeight + 10; // 10px threshold

      // If user scrolls away from bottom, disable auto-scroll
      if (!isAtBottom && autoScroll) {
        setAutoScroll(false);
      }
      // If user scrolls back to bottom, re-enable auto-scroll
      else if (isAtBottom && !autoScroll) {
        setAutoScroll(true);
      }
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, [autoScroll]);

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["logs", serviceName, lineCount] });
  };

  const handleDownload = () => {
    const blob = new Blob([logs], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${serviceName}-logs.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="flex-shrink-0">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
              <Input
                type="text"
                placeholder="Search logs..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 w-64"
              />
            </div>
            <Select
              options={LINE_COUNT_OPTIONS}
              value={String(lineCount)}
              onChange={(e) => setLineCount(Number(e.target.value))}
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
                className="rounded"
              />
              Auto-scroll
            </label>
            <Button variant="secondary" size="sm" onClick={handleRefresh} disabled={isFetching}>
              <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button variant="secondary" size="sm" onClick={handleDownload}>
              <Download className="w-4 h-4" />
              Download
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-0">
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-muted">
            <LoadingSpinner label="Loading logs..." />
          </div>
        ) : (
          <pre
            ref={logContainerRef}
            className="h-full overflow-auto p-4 bg-gray-900 text-gray-100 text-xs font-mono whitespace-pre-wrap"
          >
            {filteredLogs || "No logs available"}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}
