import { describe, it, expect, beforeEach } from "vitest";
import { login, logout, getServices } from "../client";
import { useAuthStore } from "@/stores/authStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

describe("API Client", () => {
  beforeEach(() => {
    // Clear localStorage and reset auth store before each test
    localStorage.clear();
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
    });
  });

  describe("login", () => {
    it("should successfully login with valid credentials", async () => {
      const result = await login("admin", "password");

      expect(result).toEqual({
        access_token: "mock-access-token",
        refresh_token: "mock-refresh-token",
        expires_in: 3600,
      });
    });

    it("should throw error on invalid credentials", async () => {
      // Mock failed login
      server.use(
        http.post("/auth/login", () => {
          return HttpResponse.text("Invalid credentials", { status: 401 });
        })
      );

      await expect(login("invalid", "invalid")).rejects.toThrow("Invalid credentials");
    });

    it("should throw error when response is not ok", async () => {
      server.use(
        http.post("/auth/login", () => {
          return HttpResponse.text("Server error", { status: 500 });
        })
      );

      await expect(login("admin", "password")).rejects.toThrow();
    });

    it("should handle network errors", async () => {
      server.use(
        http.post("/auth/login", () => {
          return HttpResponse.error();
        })
      );

      await expect(login("admin", "password")).rejects.toThrow();
    });
  });

  describe("logout", () => {
    it("should call logout endpoint and clear auth store", async () => {
      // Setup: user is logged in
      useAuthStore.getState().login("access-token", "refresh-token");

      await logout();

      // Check auth store was cleared
      const state = useAuthStore.getState();
      expect(state.accessToken).toBeNull();
      expect(state.refreshToken).toBeNull();
      expect(state.isAuthenticated).toBe(false);
      expect(localStorage.getItem("access_token")).toBeNull();
      expect(localStorage.getItem("refresh_token")).toBeNull();
    });

    it("should clear auth store even if API call fails", async () => {
      // Setup: user is logged in
      useAuthStore.getState().login("access-token", "refresh-token");

      // Mock logout endpoint failure
      server.use(
        http.post("/auth/logout", () => {
          return HttpResponse.text("Server error", { status: 500 });
        })
      );

      // Should not throw
      await logout();

      // Check auth store was cleared despite API failure
      const state = useAuthStore.getState();
      expect(state.accessToken).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });

    it("should work when not logged in", async () => {
      // Call logout without being logged in
      await expect(logout()).resolves.not.toThrow();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe("getServices", () => {
    beforeEach(() => {
      // Login before each test
      useAuthStore.getState().login("valid-token", "valid-refresh");
    });

    it("should fetch services successfully", async () => {
      const result = await getServices();

      expect(result.services).toBeDefined();
      expect(result.services.length).toBeGreaterThan(0);
      expect(result.services[0]).toHaveProperty("name");
      expect(result.services[0]).toHaveProperty("status");
    });

    it("should handle 401 and retry with refreshed token", async () => {
      let callCount = 0;

      // Mock: first call returns 401, second call succeeds
      server.use(
        http.get("/api/services", () => {
          callCount++;
          if (callCount === 1) {
            return HttpResponse.json({}, { status: 401 });
          }
          return HttpResponse.json({
            services: [{ name: "service1", status: "running" }],
          });
        })
      );

      const result = await getServices();

      expect(callCount).toBe(2);
      expect(result.services).toBeDefined();
      // Token should be refreshed
      expect(useAuthStore.getState().accessToken).toBe("new-mock-access-token");
    });

    it("should throw error if token refresh fails", async () => {
      // Mock: services endpoint returns 401
      server.use(
        http.get("/api/services", () => {
          return HttpResponse.json({}, { status: 401 });
        }),
        http.post("/auth/refresh", () => {
          return HttpResponse.json({}, { status: 401 });
        })
      );

      await expect(getServices()).rejects.toThrow("Unauthorized");
    });

    it("should throw error on non-401 failures", async () => {
      server.use(
        http.get("/api/services", () => {
          return HttpResponse.text("Server error", { status: 500 });
        })
      );

      await expect(getServices()).rejects.toThrow("Failed to fetch services");
    });

    it("should include access token in Authorization header", async () => {
      let receivedHeaders: Headers | null = null;

      server.use(
        http.get("/api/services", ({ request }) => {
          receivedHeaders = request.headers;
          return HttpResponse.json({ services: [] });
        })
      );

      await getServices();

      expect(receivedHeaders).not.toBeNull();
      expect(receivedHeaders!.get("Authorization")).toBe("Bearer valid-token");
    });
  });

  describe("Token Refresh Flow", () => {
    it("should refresh expired token and retry request", async () => {
      // Setup: user is logged in with a token
      useAuthStore.getState().login("expired-token", "valid-refresh");

      let servicesCallCount = 0;

      // Mock: first services call fails with 401, second succeeds
      server.use(
        http.get("/api/services", () => {
          servicesCallCount++;
          if (servicesCallCount === 1) {
            return HttpResponse.json({}, { status: 401 });
          }
          return HttpResponse.json({ services: [] });
        })
      );

      // This should trigger refresh and retry
      await getServices();

      expect(servicesCallCount).toBe(2);
      // Token should be updated
      expect(useAuthStore.getState().accessToken).toBe("new-mock-access-token");
      expect(useAuthStore.getState().refreshToken).toBe("valid-refresh");
    });

    it("should logout if refresh token is also invalid", async () => {
      // Setup
      useAuthStore.getState().login("expired-token", "expired-refresh");

      // Mock both endpoints failing
      server.use(
        http.get("/api/services", () => {
          return HttpResponse.json({}, { status: 401 });
        }),
        http.post("/auth/refresh", () => {
          return HttpResponse.json({ error: "Invalid refresh token" }, { status: 401 });
        })
      );

      await expect(getServices()).rejects.toThrow();
    });
  });

  describe("Error Handling", () => {
    beforeEach(() => {
      useAuthStore.getState().login("valid-token", "valid-refresh");
    });

    it("should handle network errors gracefully", async () => {
      server.use(
        http.get("/api/services", () => {
          return HttpResponse.error();
        })
      );

      await expect(getServices()).rejects.toThrow();
    });

    it("should handle malformed JSON responses", async () => {
      server.use(
        http.get("/api/services", () => {
          return HttpResponse.text("Not JSON");
        })
      );

      await expect(getServices()).rejects.toThrow();
    });
  });
});
