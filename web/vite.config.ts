import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    host: "127.0.0.1",
    port: 7860,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:7861",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
