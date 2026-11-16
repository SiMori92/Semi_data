import type { NextConfig } from "next";

/**
 * Strangler phase: Next serves the UI; gunicorn keeps serving /health and every
 * /api/* route UNCHANGED (path, method, auth header, JSON, filenames, content
 * types), proxied here. backup_local.sh keeps working without edits.
 */
// NB: rewrites are resolved at BUILD time (baked into routes-manifest.json), so this
// value must equal the port startup.sh binds gunicorn to at RUNTIME. Both are pinned to
// 127.0.0.1:8051; startup.sh refuses to start the Next UI on any other internal port.
const classic = process.env.CLASSIC_ORIGIN ?? "http://127.0.0.1:8051";

const config: NextConfig = {
  output: "standalone",
  // Build runs inside web/; pin the trace root there so server.js lands at
  // .next/standalone/server.js (startup.sh's path) even if a parent dir has a lockfile.
  outputFileTracingRoot: process.cwd(),
  serverExternalPackages: ["better-sqlite3"],
  // better-sqlite3 picks its bundled prebuild by a runtime path, which the tracer resolves
  // only for the BUILD host. Force the Linux ones in so the standalone server can open the
  // DB on Railway whatever machine built it.
  outputFileTracingIncludes: {
    "/**": [
      "./node_modules/better-sqlite3/prebuilds/linux-x64.node",
      "./node_modules/better-sqlite3/prebuilds/linux-arm64.node",
    ],
  },
  poweredByHeader: false,
  async rewrites() {
    return {
      beforeFiles: [
        { source: "/health", destination: `${classic}/health` },
        { source: "/api/:path*", destination: `${classic}/api/:path*` },
      ],
    };
  },
};
export default config;
