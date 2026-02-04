import { useQuery } from "@tanstack/react-query";
import { getLogs } from "@/api";

interface LogsResponse {
  logs: string;
  service_name: string;
  n_lines: number;
}

export function useLogs(serviceName: string, nLines: number = 1000) {
  return useQuery<LogsResponse>({
    queryKey: ["logs", serviceName, nLines],
    queryFn: () => getLogs(serviceName, nLines),
    refetchInterval: 3000, // Poll every 3 seconds
    refetchIntervalInBackground: false, // Pause polling when window/tab is in background
    enabled: !!serviceName,
  });
}
