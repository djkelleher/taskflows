import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    // @danklab/shared-ui is linked via `file:` and ships its own nested
    // node_modules/react. Dedupe so the app loads a single React copy and
    // shared components don't throw the "invalid hook call" (useId) error.
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:7777",
        changeOrigin: true,
      },
      "/auth": {
        target: "http://localhost:7777",
        changeOrigin: true,
      },
      "/grafana": {
        target: "http://localhost:7777",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
