import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { resolve } from "path"
import { createHash } from "node:crypto"
import { readFile, writeFile } from "node:fs/promises"

export default defineConfig({
  define: { __FRONTEND_RELEASE__: JSON.stringify(process.env.RELEASE_VERSION || null) },
  plugins: [vue(), {
    name: "day-forge-release",
    async writeBundle(options) {
      const directory = resolve(options.dir!)
      const manifest = await readFile(resolve(directory, ".vite/manifest.json"), "utf8")
      const entry = JSON.parse(manifest)["src/app.ts"]
      const digest = createHash("sha256").update(manifest).digest("hex").slice(0, 20)
      await writeFile(resolve(directory, ".vite/release.json"), JSON.stringify({
        version: process.env.RELEASE_VERSION || `build:${digest}`,
        script: entry.file,
        styles: entry.css ?? [],
      }))
    },
  }],
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
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
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
