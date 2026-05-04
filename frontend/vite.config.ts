import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const apiTarget = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/subscriptions": apiTarget,
      "/jobs": apiTarget,
      "/settings": apiTarget,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./vitest.setup.ts",
  },
});
