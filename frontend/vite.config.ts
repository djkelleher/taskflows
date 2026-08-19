import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      react: path.resolve(__dirname, "./node_modules/react"),
      "react-dom": path.resolve(__dirname, "./node_modules/react-dom"),
    },
    // Local file-linked UI packages have their own devDependencies; always
    // render through Taskflows' React instance to preserve hook identity.
    dedupe: ["react", "react-dom"],
    preserveSymlinks: true,
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
    // The release workflow copies this directory into the Python wheel. Avoid
    // shipping source maps unless a deployment explicitly requests them.
    sourcemap: process.env.VITE_SOURCEMAP === "true",
  },
});
