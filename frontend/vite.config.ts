import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const apiTarget = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("recharts")) return "charts";
          if (id.includes("lucide-react")) return "icons";
          if (
            id.includes("@tanstack/react-query") ||
            id.includes("react-dom") ||
            id.includes("react")
          ) {
            return "react";
          }
          return undefined;
        },
      },
    },
  },
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
