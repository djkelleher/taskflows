import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  csrfToken: string | null;
  isAuthenticated: boolean;
  isInitialized: boolean;
}

interface AuthActions {
  login: (accessToken: string, refreshToken: string, csrfToken?: string | null) => void;
  logout: () => void;
  refreshAccessToken: (newToken: string, csrfToken?: string | null) => void;
  initialize: () => void;
}

export const useAuthStore = create<AuthState & AuthActions>()(
  devtools(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      csrfToken: null,
      isAuthenticated: false,
      isInitialized: false,

      initialize: () => {
        const accessToken = localStorage.getItem("access_token");
        const refreshToken = localStorage.getItem("refresh_token");
        const csrfToken = localStorage.getItem("csrf_token");
        if (accessToken && refreshToken) {
          set({
            accessToken,
            refreshToken,
            csrfToken,
            isAuthenticated: true,
            isInitialized: true,
          });
        } else {
          set({ isInitialized: true });
        }
      },

      login: (accessToken: string, refreshToken: string, csrfToken?: string | null) => {
        localStorage.setItem("access_token", accessToken);
        localStorage.setItem("refresh_token", refreshToken);
        if (csrfToken) {
          localStorage.setItem("csrf_token", csrfToken);
        } else {
          localStorage.removeItem("csrf_token");
        }
        set({
          accessToken,
          refreshToken,
          csrfToken: csrfToken ?? null,
          isAuthenticated: true,
        });
      },

      logout: () => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        localStorage.removeItem("csrf_token");
        set({
          accessToken: null,
          refreshToken: null,
          csrfToken: null,
          isAuthenticated: false,
        });
      },

      refreshAccessToken: (newToken: string, csrfToken?: string | null) => {
        localStorage.setItem("access_token", newToken);
        if (csrfToken) {
          localStorage.setItem("csrf_token", csrfToken);
        }
        set((state) => ({ accessToken: newToken, csrfToken: csrfToken ?? state.csrfToken }));
      },
    }),
    { name: "AuthStore", enabled: import.meta.env.DEV }
  )
);
