import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: ["./src/test/setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov", "json"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        "src/test/**",
        "src/**/*.test.{ts,tsx}",
        "src/**/__tests__/**",
        "src/main.tsx",
        "src/vite-env.d.ts",
        // Vendored shared UI is maintained and tested in its source project.
        "src/ui/**",
      ],
      thresholds: {
        // Keep these at the measured application baseline and ratchet upward
        // as coverage is added. Vendored UI code is excluded above.
        lines: 27,
        branches: 21,
        functions: 24,
        statements: 26,
      },
    },
  },
});
