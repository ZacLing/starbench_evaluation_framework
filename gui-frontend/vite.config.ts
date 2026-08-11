import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// The console is served by the Python stdlib server in src/starbench/gui/server.py.
// base "/static/" matches its static route; the build output is committed into the
// Python package so pip users never need Node.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/",
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "../src/starbench/gui/static",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8321" },
  },
})
