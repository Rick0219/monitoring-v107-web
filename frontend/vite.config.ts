import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  build: {
    outDir: "../backend/app/frontend",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ["recharts"],
          routing: ["@tanstack/react-router", "@tanstack/react-query"],
        },
      },
    },
  },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8007" } },
});
