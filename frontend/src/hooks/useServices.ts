import { useQuery, useMutation } from "@tanstack/react-query";
import {
  getServices,
  serviceAction,
  batchAction,
  enableService,
  disableService,
  removeService,
  showService,
  createService,
  getServers,
} from "@/api";
import { useDelayedInvalidation } from "./useDelayedInvalidation";
import type { ServicesResponse, ShowResponse, BatchOperation, Server } from "@/types";

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

export function useEnableService() {
  const invalidateServices = useDelayedInvalidation(["services"], 1000);

  return useMutation({
    mutationFn: (match: string) => enableService(match),
    onSuccess: invalidateServices,
  });
}

export function useDisableService() {
  const invalidateServices = useDelayedInvalidation(["services"], 1000);

  return useMutation({
    mutationFn: (match: string) => disableService(match),
    onSuccess: invalidateServices,
  });
}

export function useRemoveService() {
  const invalidateServices = useDelayedInvalidation(["services"], 1000);

  return useMutation({
    mutationFn: (match: string) => removeService(match),
    onSuccess: invalidateServices,
  });
}

export function useCreateService() {
  const invalidateServices = useDelayedInvalidation(["services"], 1000);

  return useMutation({
    mutationFn: ({ file, host, include, exclude }: { file: File; host?: string; include?: string; exclude?: string }) =>
      createService(file, host, include, exclude),
    onSuccess: invalidateServices,
  });
}

export function useShowService(match: string) {
  return useQuery<ShowResponse>({
    queryKey: ["show", match],
    queryFn: () => showService(match),
    enabled: !!match,
  });
}

export function useServers() {
  return useQuery<Server[]>({
    queryKey: ["servers"],
    queryFn: getServers,
  });
}
