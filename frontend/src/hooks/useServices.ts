import { useQuery, useMutation } from "@tanstack/react-query";
import { getServices, serviceAction, batchAction } from "@/api";
import { useDelayedInvalidation } from "./useDelayedInvalidation";
import type { ServicesResponse, BatchOperation } from "@/types";

export function useServices() {
  return useQuery<ServicesResponse>({
    queryKey: ["services"],
    queryFn: getServices,
    refetchInterval: 5000, // Poll every 5 seconds
    refetchIntervalInBackground: false, // Pause polling when window/tab is in background
  });
}

export function useServiceAction() {
  const invalidateServices = useDelayedInvalidation(["services"], 1000);

  return useMutation({
    mutationFn: ({ serviceName, action }: { serviceName: string; action: "start" | "stop" | "restart" }) =>
      serviceAction(serviceName, action),
    onSuccess: invalidateServices,
  });
}

export function useBatchAction() {
  const invalidateServices = useDelayedInvalidation(["services"], 1000);

  return useMutation({
    mutationFn: ({ serviceNames, operation }: { serviceNames: string[]; operation: BatchOperation }) =>
      batchAction(serviceNames, operation),
    onSuccess: invalidateServices,
  });
}
