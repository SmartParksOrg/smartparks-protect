/// <reference types="vitest/config" />
import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import svgr from "vite-plugin-svgr";
import { defineConfig, loadEnv } from "vite";

// The frontend reads the repository root .env so there is one env file for the whole stack.
const envDir = path.resolve(import.meta.dirname, "../..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, "VITE_");
  const proxyTarget = env.VITE_PROXY_TARGET || "http://localhost:8000";
  return {
    envDir,
    plugins: [react(), tailwindcss(), svgr()],
    worker: { format: "es" },
    resolve: {
      alias: { "@": path.resolve(import.meta.dirname, "./src") },
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": { target: proxyTarget, changeOrigin: true },
        "/ws": { target: proxyTarget.replace(/^http/, "ws"), ws: true },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});
