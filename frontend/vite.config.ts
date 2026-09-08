import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { resolve } from "path"

export default defineConfig({
  plugins: [vue()],
  root: resolve(__dirname),
  test: {
    environment: "jsdom",
    globals: true,
  },
  base: process.env.NODE_ENV === "production" ? "/static/" : "/",
  build: {
    outDir: resolve(__dirname, "dist"),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: resolve(__dirname, "src/app.ts"),
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/accounts": "http://localhost:8006",
      "/api": "http://localhost:8006",
      "/schedule": "http://localhost:8006",
      "/settings": "http://localhost:8006",
      "/analytics": "http://localhost:8006",
      "/admin": "http://localhost:8006",
      // Public legal pages — Django-rendered, no Vue page to resolve, so
      // without these entries the dev server 404s the Login footer links.
      // Anchored regexes (a key starting with ^ is treated as one) rather
      // than the prefix matching the keys above use: a future /terms-of-sale
      // or /privacy-settings route must not be swallowed by these.
      "^/privacy(/.*)?$": "http://localhost:8006",
      "^/terms(/.*)?$": "http://localhost:8006",
      "^/$": "http://localhost:8006",
    },
  },
})
