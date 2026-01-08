import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getServices, serviceAction, batchAction } from "@/api";
import type { ServicesResponse, BatchOperation } from "@/types";

export function useServices() {
  return useQuery<ServicesResponse>({
    queryKey: ["services"],
    queryFn: getServices,
    refetchInterval: 5000, // Poll every 5 seconds
  });
}

export function useServiceAction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ serviceName, action }: { serviceName: string; action: "start" | "stop" | "restart" }) =>
      serviceAction(serviceName, action),
    onSuccess: () => {
      // Refetch services after 1 second to see updated status
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["services"] });
      }, 1000);
    },
  });
}

export function useBatchAction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ serviceNames, operation }: { serviceNames: string[]; operation: BatchOperation }) =>
      batchAction(serviceNames, operation),
    onSuccess: () => {
      // Refetch services after 1 second to see updated status
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["services"] });
      }, 1000);
    },
  });
}
