import { defineConfig } from "vite";

// Plain JS + htm — htm uses tagged template literals (no JSX transpile needed),
// so no JSX plugin is configured (D-04: no TypeScript, no tsconfig, minimal config).
//
// base: "/ui/"        → assets are emitted/served under /ui/assets/ so the bundle
//                       works behind the FastAPI StaticFiles mount at /ui (Plan 03).
// server.proxy /api   → forwards /api/* to the running FastAPI backend on :8080 so
//                       the Vite dev loop is same-origin and never hits CORS (D-05).
//                       This intentionally OVERRIDES UI-SPEC's "proxy not needed" line.
// server.host 0.0.0.0 → binds all interfaces so the dev server is reachable from the
//                       containerized dev loop (Plan 04 publishes the port).
export default defineConfig({
  base: "/ui/",
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": "http://localhost:8080",
    },
  },
});
