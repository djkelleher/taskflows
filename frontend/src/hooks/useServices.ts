import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { getServices, serviceAction, batchAction } from "@/api";
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
  const queryClient = useQueryClient();
  const timeoutRef = useRef<number>();

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return useMutation({
    mutationFn: ({ serviceName, action }: { serviceName: string; action: "start" | "stop" | "restart" }) =>
      serviceAction(serviceName, action),
    onSuccess: () => {
      // Clear any existing timeout
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      // Refetch services after 1 second to see updated status
      timeoutRef.current = setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["services"] });
      }, 1000) as unknown as number;
    },
  });
}

export function useBatchAction() {
  const queryClient = useQueryClient();
  const timeoutRef = useRef<number>();

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return useMutation({
    mutationFn: ({ serviceNames, operation }: { serviceNames: string[]; operation: BatchOperation }) =>
      batchAction(serviceNames, operation),
    onSuccess: () => {
      // Clear any existing timeout
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      // Refetch services after 1 second to see updated status
      timeoutRef.current = setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["services"] });
      }, 1000) as unknown as number;
    },
  });
}
