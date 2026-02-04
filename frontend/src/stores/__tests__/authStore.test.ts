import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { useAuthStore } from "../authStore";

describe("AuthStore", () => {
  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();
    // Reset store state
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe("Initial State", () => {
    it("should have null tokens and not be authenticated initially", () => {
      const state = useAuthStore.getState();
      expect(state.accessToken).toBeNull();
      expect(state.refreshToken).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe("initialize", () => {
    it("should initialize with tokens from localStorage", () => {
      // Setup localStorage with tokens
      localStorage.setItem("access_token", "test-access-token");
      localStorage.setItem("refresh_token", "test-refresh-token");

      // Call initialize
      useAuthStore.getState().initialize();

      // Check state was updated
      const state = useAuthStore.getState();
      expect(state.accessToken).toBe("test-access-token");
      expect(state.refreshToken).toBe("test-refresh-token");
      expect(state.isAuthenticated).toBe(true);
    });

    it("should not authenticate if tokens are missing", () => {
      // Call initialize without tokens in localStorage
      useAuthStore.getState().initialize();

      // Check state remains unauthenticated
      const state = useAuthStore.getState();
      expect(state.accessToken).toBeNull();
      expect(state.refreshToken).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });

    it("should not authenticate if only access token is present", () => {
      localStorage.setItem("access_token", "test-access-token");

      useAuthStore.getState().initialize();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
    });

    it("should not authenticate if only refresh token is present", () => {
      localStorage.setItem("refresh_token", "test-refresh-token");

      useAuthStore.getState().initialize();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe("login", () => {
    it("should store tokens in localStorage and update state", () => {
      const accessToken = "new-access-token";
      const refreshToken = "new-refresh-token";

      // Call login
      useAuthStore.getState().login(accessToken, refreshToken);

      // Check localStorage
      expect(localStorage.getItem("access_token")).toBe(accessToken);
      expect(localStorage.getItem("refresh_token")).toBe(refreshToken);

      // Check state
      const state = useAuthStore.getState();
      expect(state.accessToken).toBe(accessToken);
      expect(state.refreshToken).toBe(refreshToken);
      expect(state.isAuthenticated).toBe(true);
    });

    it("should overwrite existing tokens on new login", () => {
      // First login
      useAuthStore.getState().login("old-access", "old-refresh");

      // Second login
      useAuthStore.getState().login("new-access", "new-refresh");

      // Check only new tokens are stored
      expect(localStorage.getItem("access_token")).toBe("new-access");
      expect(localStorage.getItem("refresh_token")).toBe("new-refresh");

      const state = useAuthStore.getState();
      expect(state.accessToken).toBe("new-access");
      expect(state.refreshToken).toBe("new-refresh");
      expect(state.isAuthenticated).toBe(true);
    });
  });

  describe("logout", () => {
    it("should remove tokens from localStorage and clear state", () => {
      // Setup: login first
      useAuthStore.getState().login("access-token", "refresh-token");

      // Call logout
      useAuthStore.getState().logout();

      // Check localStorage is cleared
      expect(localStorage.getItem("access_token")).toBeNull();
      expect(localStorage.getItem("refresh_token")).toBeNull();

      // Check state is cleared
      const state = useAuthStore.getState();
      expect(state.accessToken).toBeNull();
      expect(state.refreshToken).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });

    it("should work when already logged out", () => {
      // Call logout when not logged in
      useAuthStore.getState().logout();

      // Should not throw and state should remain cleared
      const state = useAuthStore.getState();
      expect(state.accessToken).toBeNull();
      expect(state.refreshToken).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe("refreshAccessToken", () => {
    it("should update access token in localStorage and state", () => {
      // Setup: login first
      useAuthStore.getState().login("old-access", "refresh-token");

      // Refresh access token
      const newAccessToken = "new-access-token";
      useAuthStore.getState().refreshAccessToken(newAccessToken);

      // Check localStorage has new access token
      expect(localStorage.getItem("access_token")).toBe(newAccessToken);
      // Refresh token should remain unchanged
      expect(localStorage.getItem("refresh_token")).toBe("refresh-token");

      // Check state
      const state = useAuthStore.getState();
      expect(state.accessToken).toBe(newAccessToken);
      expect(state.refreshToken).toBe("refresh-token");
      expect(state.isAuthenticated).toBe(true);
    });

    it("should not affect refresh token", () => {
      useAuthStore.getState().login("access-token", "refresh-token");

      useAuthStore.getState().refreshAccessToken("new-access-token");

      const state = useAuthStore.getState();
      expect(state.refreshToken).toBe("refresh-token");
      expect(localStorage.getItem("refresh_token")).toBe("refresh-token");
    });
  });

  describe("Integration scenarios", () => {
    it("should handle complete auth flow: login -> refresh -> logout", () => {
      // Login
      useAuthStore.getState().login("access-1", "refresh-1");
      expect(useAuthStore.getState().isAuthenticated).toBe(true);

      // Refresh token
      useAuthStore.getState().refreshAccessToken("access-2");
      expect(useAuthStore.getState().accessToken).toBe("access-2");
      expect(useAuthStore.getState().refreshToken).toBe("refresh-1");

      // Logout
      useAuthStore.getState().logout();
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
      expect(localStorage.getItem("access_token")).toBeNull();
    });

    it("should maintain persistence across store resets (via initialize)", () => {
      // Login and store tokens
      useAuthStore.getState().login("persisted-access", "persisted-refresh");

      // Simulate app restart by resetting state
      useAuthStore.setState({
        accessToken: null,
        refreshToken: null,
        isAuthenticated: false,
      });

      // Initialize should restore from localStorage
      useAuthStore.getState().initialize();

      const state = useAuthStore.getState();
      expect(state.accessToken).toBe("persisted-access");
      expect(state.refreshToken).toBe("persisted-refresh");
      expect(state.isAuthenticated).toBe(true);
    });
  });
});
