import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter } from "react-router-dom";
import { LoginPage } from "../LoginPage";
import { useAuthStore } from "@/stores/authStore";
import { ToastProvider } from "@/components/ui/Toast";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

// Mock useNavigate
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

function renderLoginPage() {
  return render(
    <BrowserRouter>
      <ToastProvider>
        <LoginPage />
      </ToastProvider>
    </BrowserRouter>
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
    });
    mockNavigate.mockClear();
  });

  it("should render login form", () => {
    renderLoginPage();

    expect(screen.getByText("Taskflows")).toBeInTheDocument();
    expect(screen.getByText("Sign in to your account")).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("should handle successful login", async () => {
    const user = userEvent.setup();
    renderLoginPage();

    // Fill in form
    await user.type(screen.getByLabelText(/username/i), "admin");
    await user.type(screen.getByLabelText(/password/i), "password");

    // Submit form
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    // Wait for login to complete
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/");
    });

    // Check auth store was updated
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.accessToken).toBe("mock-access-token");
    expect(state.refreshToken).toBe("mock-refresh-token");
  });

  it("should display error on failed login", async () => {
    const user = userEvent.setup();

    // Mock failed login
    server.use(
      http.post("/auth/login", () => {
        return HttpResponse.text("Invalid credentials", { status: 401 });
      })
    );

    renderLoginPage();

    // Fill in form with invalid credentials
    await user.type(screen.getByLabelText(/username/i), "invalid");
    await user.type(screen.getByLabelText(/password/i), "invalid");

    // Submit form
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    // Wait a bit for the request to complete
    await new Promise(resolve => setTimeout(resolve, 100));

    // Should not navigate
    expect(mockNavigate).not.toHaveBeenCalled();

    // Should not be authenticated
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it("should disable button while loading", async () => {
    const user = userEvent.setup();
    renderLoginPage();

    const submitButton = screen.getByRole("button", { name: /sign in/i });

    // Initially not disabled
    expect(submitButton).not.toBeDisabled();

    // Fill in form
    await user.type(screen.getByLabelText(/username/i), "admin");
    await user.type(screen.getByLabelText(/password/i), "password");

    // Submit form - this will eventually navigate
    await user.click(submitButton);

    // Wait for navigation to complete
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/");
    });
  });

  it("should redirect if already authenticated", () => {
    // Set user as authenticated
    useAuthStore.setState({
      accessToken: "token",
      refreshToken: "refresh",
      isAuthenticated: true,
    });

    renderLoginPage();

    // Should immediately navigate away
    expect(mockNavigate).toHaveBeenCalledWith("/");
  });

  it("should handle multiple login attempts", async () => {
    const user = userEvent.setup();

    // Mock first request to fail, second to succeed
    let requestCount = 0;
    server.use(
      http.post("/auth/login", () => {
        requestCount++;
        if (requestCount === 1) {
          return HttpResponse.text("First error", { status: 401 });
        }
        return HttpResponse.json({
          access_token: "token",
          refresh_token: "refresh",
          expires_in: 3600,
        });
      })
    );

    renderLoginPage();

    // First submission - fails
    await user.type(screen.getByLabelText(/username/i), "admin");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    // Wait for first request to complete
    await new Promise(resolve => setTimeout(resolve, 100));

    // Should not navigate yet
    expect(mockNavigate).not.toHaveBeenCalled();

    // Second submission - succeeds
    await user.clear(screen.getByLabelText(/password/i));
    await user.type(screen.getByLabelText(/password/i), "correct");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    // Navigation should occur
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/");
    });
  });

  it("should require username and password", () => {
    renderLoginPage();

    const usernameInput = screen.getByLabelText(/username/i);
    const passwordInput = screen.getByLabelText(/password/i);

    expect(usernameInput).toBeRequired();
    expect(passwordInput).toBeRequired();
  });
});
