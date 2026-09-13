import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    proxy: {
      "/docs": {
        target: "http://localhost:3000",
        changeOrigin: true,
      },
      "/_next": {
        target: "http://localhost:3000",
        changeOrigin: true,
      }
    }
  }
});
