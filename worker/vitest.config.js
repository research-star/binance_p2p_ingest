import { defineConfig } from "vitest/config";

// Tests en node: el handler del Worker (`worker.fetch(req, env)`) corre directo
// sobre las APIs globales de node 24 (WebCrypto, fetch, Request/Response/URL).
// KV se stubea in-memory y el JWKS de Access se mockea vía global.fetch (ver
// test/worker.test.js). El runtime real (workerd/Miniflare) se cubre aparte con
// el smoke de `wrangler dev` (scripts/smoke.sh).
export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.js"],
  },
});
