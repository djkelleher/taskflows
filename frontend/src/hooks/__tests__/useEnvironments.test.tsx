import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  useEnvironments,
  useEnvironment,
  useCreateEnvironment,
  useUpdateEnvironment,
  useDeleteEnvironment,
} from "../useEnvironments";
import { useAuthStore } from "@/stores/authStore";
import type { ReactNode } from "react";
import type { NamedEnvironment } from "@/types";

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

describe("useEnvironments", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: "test-token",
      refreshToken: "test-refresh",
      isAuthenticated: true,
    });
  });

  it("should fetch environments successfully", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useEnvironments(), { wrapper });

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Match MSW mock data structure
    expect(result.current.data).toEqual({
      environments: [
        { name: "dev-env", type: "venv", venv: { name: "dev" } },
        {
          name: "prod-docker",
          type: "docker",
          docker: {
            image: "python:3.11",
            network_mode: "bridge",
            restart_policy: "always",
            shm_size: null,
            privileged: false,
            ports: [],
            volumes: [],
            environment: {},
          },
        },
      ],
    });
    expect(result.current.error).toBeNull();
  });

  it("should handle fetch errors", async () => {
    // Mock endpoint to return error
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");

    server.use(
      http.get("/api/environments", () => {
        return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
      })
    );

    const wrapper = createWrapper();
    const { result } = renderHook(() => useEnvironments(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
    expect(result.current.data).toBeUndefined();
  });
});

describe("useEnvironment", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: "test-token",
      refreshToken: "test-refresh",
      isAuthenticated: true,
    });
  });

  it("should fetch single environment successfully", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useEnvironment("dev-env"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Match MSW mock data for dev-env
    expect(result.current.data).toEqual({
      name: "dev-env",
      type: "venv",
      venv: { name: "dev" },
    });
  });

  it("should not fetch when name is empty", () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useEnvironment(""), { wrapper });

    // Query should be disabled when name is empty
    expect(result.current.isFetching).toBe(false);
    expect(result.current.isLoading).toBe(false);
  });

  it("should handle fetch errors", async () => {
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
    });

    const wrapper = createWrapper();
    const { result } = renderHook(() => useEnvironment("test-env"), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
  });
});

describe("useCreateEnvironment", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: "test-token",
      refreshToken: "test-refresh",
      isAuthenticated: true,
    });
  });

  it("should create environment successfully", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useCreateEnvironment(), { wrapper });

    const newEnvironment: NamedEnvironment = {
      name: "new-env",
      type: "docker",
      docker: {
        image: "python:3.11",
        network_mode: "bridge",
        restart_policy: "unless-stopped",
        privileged: false,
        shm_size: null,
        ports: [],
        volumes: [],
        environment: {},
      },
    };

    result.current.mutate(newEnvironment);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.error).toBeNull();
  });

  it("should handle creation errors", async () => {
    // Mock endpoint to return error
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");

    server.use(
      http.post("/api/environments", () => {
        return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
      })
    );

    const wrapper = createWrapper();
    const { result } = renderHook(() => useCreateEnvironment(), { wrapper });

    const newEnvironment: NamedEnvironment = {
      name: "new-env",
      type: "docker",
      docker: {
        image: "python:3.11",
        network_mode: "bridge",
        restart_policy: "unless-stopped",
        privileged: false,
        shm_size: null,
        ports: [],
        volumes: [],
        environment: {},
      },
    };

    result.current.mutate(newEnvironment);

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
  });
});

describe("useUpdateEnvironment", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: "test-token",
      refreshToken: "test-refresh",
      isAuthenticated: true,
    });
  });

  it("should update environment successfully", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useUpdateEnvironment(), { wrapper });

    const updatedEnvironment: NamedEnvironment = {
      name: "existing-env",
      type: "docker",
      docker: {
        image: "python:3.12",
        network_mode: "bridge",
        restart_policy: "unless-stopped",
        privileged: false,
        shm_size: null,
        ports: [],
        volumes: [],
        environment: {},
      },
    };

    result.current.mutate({ name: "existing-env", environment: updatedEnvironment });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.error).toBeNull();
  });

  it("should handle update errors", async () => {
    // Mock endpoint to return error
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");

    server.use(
      http.put("/api/environments/:name", () => {
        return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
      })
    );

    const wrapper = createWrapper();
    const { result } = renderHook(() => useUpdateEnvironment(), { wrapper });

    const updatedEnvironment: NamedEnvironment = {
      name: "existing-env",
      type: "docker",
      docker: {
        image: "python:3.12",
        network_mode: "bridge",
        restart_policy: "unless-stopped",
        privileged: false,
        shm_size: null,
        ports: [],
        volumes: [],
        environment: {},
      },
    };

    result.current.mutate({ name: "existing-env", environment: updatedEnvironment });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
  });
});

describe("useDeleteEnvironment", () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: "test-token",
      refreshToken: "test-refresh",
      isAuthenticated: true,
    });
  });

  it("should delete environment successfully", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(() => useDeleteEnvironment(), { wrapper });

    result.current.mutate("env-to-delete");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.error).toBeNull();
  });

  it("should handle delete errors", async () => {
    // Mock endpoint to return error
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");

    server.use(
      http.delete("/api/environments/:name", () => {
        return HttpResponse.json({ error: "Unauthorized" }, { status: 401 });
      })
    );

    const wrapper = createWrapper();
    const { result } = renderHook(() => useDeleteEnvironment(), { wrapper });

    result.current.mutate("env-to-delete");

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
  });
});
