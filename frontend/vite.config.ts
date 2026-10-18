import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, API calls go to the Python dashboard server (python dashboard.py).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
