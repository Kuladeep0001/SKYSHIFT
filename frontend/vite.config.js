import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the site on http://localhost:5173 and forwards /api to the Python backend.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
});
