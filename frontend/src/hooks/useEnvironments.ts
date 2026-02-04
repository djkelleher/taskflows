import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getEnvironments, getEnvironment, createEnvironment, updateEnvironment, deleteEnvironment } from "@/api";
import type { EnvironmentsResponse, NamedEnvironment } from "@/types";

export function useEnvironments() {
  return useQuery<EnvironmentsResponse>({
    queryKey: ["environments"],
    queryFn: getEnvironments,
  });
}

export function useEnvironment(name: string) {
  return useQuery<NamedEnvironment>({
    queryKey: ["environment", name],
    queryFn: () => getEnvironment(name),
    enabled: !!name,
  });
}

export function useCreateEnvironment() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (environment: NamedEnvironment) => createEnvironment(environment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environments"] });
    },
  });
}

export function useUpdateEnvironment() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ name, environment }: { name: string; environment: NamedEnvironment }) =>
      updateEnvironment(name, environment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environments"] });
    },
  });
}

export function useDeleteEnvironment() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (name: string) => deleteEnvironment(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environments"] });
    },
  });
}
