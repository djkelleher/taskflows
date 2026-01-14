import createClient, { type Middleware } from "openapi-fetch";
import { useAuthStore } from "@/stores/authStore";
import type { LoginRequest, LoginResponse, RefreshResponse, NamedEnvironment } from "@/types";

// Base API client without auth (for login endpoint)
const baseClient = createClient({ baseUrl: "" });

// Mutex to prevent concurrent token refreshes
let refreshPromise: Promise<string | null> | null = null;

// Refresh token and return new access token
// Uses mutex to ensure only one refresh happens at a time
async function refreshAccessToken(): Promise<string | null> {
  // If a refresh is already in progress, return that promise
  if (refreshPromise) {
    return refreshPromise;
  }

  const refreshToken = useAuthStore.getState().refreshToken;
  if (!refreshToken) return null;

  // Create and store the refresh promise
  refreshPromise = (async () => {
    try {
      const response = await fetch("/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (response.ok) {
        const data = (await response.json()) as RefreshResponse;
        useAuthStore.getState().refreshAccessToken(data.access_token);
        return data.access_token;
      }
    } catch (err) {
      console.error("Token refresh failed:", err);
    }

    return null;
  })();

  try {
    return await refreshPromise;
  } finally {
    // Clear the promise after completion (success or failure)
    refreshPromise = null;
  }
}

// Standardized fetch with 401 retry logic
// Automatically refreshes token and retries once on 401, or logs out if refresh fails
async function fetchWithAuth(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = useAuthStore.getState().accessToken;

  // Add Authorization header to init
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  // Make initial request
  const response = await fetch(input, { ...init, headers });

  // Handle 401 - refresh token and retry once
  if (response.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      // Retry with new token
      const retryHeaders = new Headers(init?.headers);
      retryHeaders.set("Authorization", `Bearer ${newToken}`);
      return fetch(input, { ...init, headers: retryHeaders });
    } else {
      // Refresh failed - logout and redirect
      useAuthStore.getState().logout();
      throw new Error("Unauthorized - session expired");
    }
  }

  return response;
}

// Auth middleware - adds Authorization header and handles 401s
const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = useAuthStore.getState().accessToken;
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },

  async onResponse({ response, request }) {
    if (response.status === 401) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        // Retry the request with the new token
        const newRequest = request.clone();
        newRequest.headers.set("Authorization", `Bearer ${newToken}`);
        return fetch(newRequest);
      } else {
        // Refresh failed, logout
        // Auth store logout will trigger redirect to /login via protected routes
        useAuthStore.getState().logout();
      }
    }
    return response;
  },
};

// Create authenticated API client
const api = createClient({ baseUrl: "" });
api.use(authMiddleware);

// Auth functions (don't use the auth middleware)
export async function login(username: string, password: string): Promise<LoginResponse> {
  const response = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password } as LoginRequest),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || "Login failed");
  }

  return response.json();
}

export async function logout(): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  try {
    await fetch("/auth/logout", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  } finally {
    useAuthStore.getState().logout();
  }
}

// Service API functions
export async function getServices() {
  const response = await fetchWithAuth("/api/services?as_json=true");

  if (!response.ok) throw new Error("Failed to fetch services");
  return response.json();
}

export async function serviceAction(serviceName: string, action: "start" | "stop" | "restart") {
  const response = await fetchWithAuth(
    `/api/${action}?match=${encodeURIComponent(serviceName)}&as_json=true`,
    { method: "POST" }
  );

  if (!response.ok) throw new Error(`Failed to ${action} service`);
  return response.json();
}

export async function batchAction(serviceNames: string[], operation: "start" | "stop" | "restart") {
  const response = await fetchWithAuth("/api/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ service_names: serviceNames, operation }),
  });

  if (!response.ok) throw new Error(`Failed to ${operation} services`);
  return response.json();
}

export async function getLogs(serviceName: string, nLines: number = 1000) {
  const response = await fetchWithAuth(
    `/api/logs?service_name=${encodeURIComponent(serviceName)}&n_lines=${nLines}`
  );

  if (!response.ok) throw new Error("Failed to fetch logs");
  return response.json();
}

// Environment API functions
export async function getEnvironments() {
  const response = await fetchWithAuth("/api/environments");

  if (!response.ok) throw new Error("Failed to fetch environments");
  return response.json();
}

export async function getEnvironment(name: string) {
  const response = await fetchWithAuth(`/api/environments/${encodeURIComponent(name)}`);

  if (!response.ok) throw new Error("Failed to fetch environment");
  return response.json();
}

export async function createEnvironment(environment: NamedEnvironment) {
  const response = await fetchWithAuth("/api/environments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(environment),
  });

  if (!response.ok) throw new Error("Failed to create environment");
  return response.json();
}

export async function updateEnvironment(name: string, environment: NamedEnvironment) {
  const response = await fetchWithAuth(`/api/environments/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(environment),
  });

  if (!response.ok) throw new Error("Failed to update environment");
  return response.json();
}

export async function deleteEnvironment(name: string) {
  const response = await fetchWithAuth(`/api/environments/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });

  if (!response.ok) throw new Error("Failed to delete environment");
  return response.ok;
}

export { api, baseClient };
