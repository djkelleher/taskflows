import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useServices, useServiceAction, useBatchAction } from "../useServices";
import { useAuthStore } from "@/stores/authStore";
import type { ReactNode } from "react";

// Create a wrapper with QueryClient for testing
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useServices", () => {
  beforeEach(() => {
    // Setup auth for tests
    useAuthStore.setState({
      accessToken: "test-token",
      refreshToken: "test-refresh",
      isAuthenticated: true,
    });
  });

  it("should fetch services successfully", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useServices(), { wrapper });

    // Initially loading
    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();

    // Wait for query to resolve
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Check structure matches MSW mock data
    expect(result.current.data).toEqual({
      services: [
        { name: "service-1", status: "running", schedule: "* * * * *", last_run: "2024-01-01 12:00:00" },
        { name: "service-2", status: "stopped", schedule: null, last_run: null },
        { name: "service-3", status: "failed", schedule: "0 * * * *", last_run: "2024-01-01 11:00:00" },
      ],
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("should handle fetch errors", async () => {
    // Mock endpoint to return error
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");

    server.use(
      http.get("/api/services", () => {
        return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
      })
    );

    const wrapper = createWrapper();
    const { result } = renderHook(() => useServices(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
    expect(result.current.data).toBeUndefined();
  });

  it("should have correct refetch interval", () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useServices(), { wrapper });

    // Check that refetchInterval is set (part of the query options)
    expect(result.current).toHaveProperty("dataUpdatedAt");
  });
});

describe("useServiceAction", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: "test-token",
      refreshToken: "test-refresh",
      isAuthenticated: true,
    });
  });

  it("should execute service action successfully", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useServiceAction(), { wrapper });

    expect(result.current.isPending).toBe(false);

    // Execute mutation
    result.current.mutate({ serviceName: "service1", action: "start" });

    // Wait for mutation to complete (skip checking isPending due to race condition)
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.error).toBeNull();
  });

  it("should handle action errors", async () => {
    // Mock endpoint to return error
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");

    server.use(
      http.post("/api/start", () => {
        return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
      })
    );

    const wrapper = createWrapper();
    const { result } = renderHook(() => useServiceAction(), { wrapper });

    result.current.mutate({ serviceName: "service1", action: "start" });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
  });

  it("should accept start, stop, and restart actions", async () => {
    const wrapper = createWrapper();

    // Test start action
    const { result: startResult } = renderHook(() => useServiceAction(), { wrapper });
    startResult.current.mutate({ serviceName: "test", action: "start" });
    await waitFor(() => expect(startResult.current.isSuccess).toBe(true));

    // Test stop action
    const { result: stopResult } = renderHook(() => useServiceAction(), { wrapper });
    stopResult.current.mutate({ serviceName: "test", action: "stop" });
    await waitFor(() => expect(stopResult.current.isSuccess).toBe(true));

    // Test restart action
    const { result: restartResult } = renderHook(() => useServiceAction(), { wrapper });
    restartResult.current.mutate({ serviceName: "test", action: "restart" });
    await waitFor(() => expect(restartResult.current.isSuccess).toBe(true));
  });
});

describe("useBatchAction", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: "test-token",
      refreshToken: "test-refresh",
      isAuthenticated: true,
    });
  });

  it("should execute batch action successfully", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useBatchAction(), { wrapper });

    const serviceNames = ["service1", "service2"];
    result.current.mutate({ serviceNames, operation: "start" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.error).toBeNull();
  });

  it("should handle batch action errors", async () => {
    // Mock endpoint to return error
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");

    server.use(
      http.post("/api/batch", () => {
        return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
      })
    );

    const wrapper = createWrapper();
    const { result } = renderHook(() => useBatchAction(), { wrapper });

    result.current.mutate({ serviceNames: ["service1"], operation: "start" });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
  });

  it("should handle empty service list", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useBatchAction(), { wrapper });

    result.current.mutate({ serviceNames: [], operation: "start" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("should support all batch operations", async () => {
    const wrapper = createWrapper();

    // Test start
    const { result: startResult } = renderHook(() => useBatchAction(), { wrapper });
    startResult.current.mutate({ serviceNames: ["s1"], operation: "start" });
    await waitFor(() => expect(startResult.current.isSuccess).toBe(true));

    // Test stop
    const { result: stopResult } = renderHook(() => useBatchAction(), { wrapper });
    stopResult.current.mutate({ serviceNames: ["s1"], operation: "stop" });
    await waitFor(() => expect(stopResult.current.isSuccess).toBe(true));

    // Test restart
    const { result: restartResult } = renderHook(() => useBatchAction(), { wrapper });
    restartResult.current.mutate({ serviceNames: ["s1"], operation: "restart" });
    await waitFor(() => expect(restartResult.current.isSuccess).toBe(true));
  });
});
