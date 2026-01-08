import createClient, { type Middleware } from "openapi-fetch";
import { useAuthStore } from "@/stores/authStore";
import type { LoginRequest, LoginResponse, RefreshResponse } from "@/types";

// Base API client without auth (for login endpoint)
const baseClient = createClient({ baseUrl: "" });

// Refresh token and return new access token
async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = useAuthStore.getState().refreshToken;
  if (!refreshToken) return null;

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
        useAuthStore.getState().logout();
        window.location.href = "/login";
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
  const token = useAuthStore.getState().accessToken;
  const response = await fetch("/api/services?as_json=true", {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (response.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      const retryResponse = await fetch("/api/services?as_json=true", {
        headers: { Authorization: `Bearer ${newToken}` },
      });
      if (!retryResponse.ok) throw new Error("Failed to fetch services");
      return retryResponse.json();
    }
    throw new Error("Unauthorized");
  }

  if (!response.ok) throw new Error("Failed to fetch services");
  return response.json();
}

export async function serviceAction(serviceName: string, action: "start" | "stop" | "restart") {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch(`/api/${action}?match=${encodeURIComponent(serviceName)}&as_json=true`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) throw new Error(`Failed to ${action} service`);
  return response.json();
}

export async function batchAction(serviceNames: string[], operation: "start" | "stop" | "restart") {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch("/api/batch", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ service_names: serviceNames, operation }),
  });

  if (!response.ok) throw new Error(`Failed to ${operation} services`);
  return response.json();
}

export async function getLogs(serviceName: string, nLines: number = 1000) {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch(`/api/logs?service_name=${encodeURIComponent(serviceName)}&n_lines=${nLines}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) throw new Error("Failed to fetch logs");
  return response.json();
}

// Environment API functions
export async function getEnvironments() {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch("/api/environments", {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) throw new Error("Failed to fetch environments");
  return response.json();
}

export async function getEnvironment(name: string) {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch(`/api/environments/${encodeURIComponent(name)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) throw new Error("Failed to fetch environment");
  return response.json();
}

export async function createEnvironment(environment: unknown) {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch("/api/environments", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(environment),
  });

  if (!response.ok) throw new Error("Failed to create environment");
  return response.json();
}

export async function updateEnvironment(name: string, environment: unknown) {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch(`/api/environments/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(environment),
  });

  if (!response.ok) throw new Error("Failed to update environment");
  return response.json();
}

export async function deleteEnvironment(name: string) {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch(`/api/environments/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) throw new Error("Failed to delete environment");
  return response.ok;
}

export { api, baseClient };
