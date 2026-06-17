import { beforeAll, beforeEach, afterEach, describe, it, expect } from "vitest";
import worker from "../src/index.js";
import { _resetJwksCache } from "../src/auth.js";
import { makeKeypairAndJwks, mintJwt } from "./helpers.js";

// El handler corre directo en node (Request/Response/URL/WebCrypto/fetch globales).
// KV = stub in-memory (mismo contrato get/put que Workers KV). JWKS de Access =
// mockeado vía global.fetch con un keypair RSA self-signed. El runtime real
// (workerd/Miniflare) se valida con el smoke de wrangler dev, aparte.

// Valores públicos reales (deben matchear wrangler.toml [vars]).
const AUD = "679296d30558e396a95df499a0674d2d6aabe52186ead3466139db83fe7bbd71";
const TEAM = "finanzasbo.cloudflareaccess.com";
const ISS = `https://${TEAM}`;
const ADMIN = "admin@finanzasbo.com"; // ∈ ALLOWED_EMAILS
const NOTADMIN = "intruso@gmail.com"; // ∉ ALLOWED_EMAILS
const ID_A = "0123456789abcdef";
const ID_B = "fedcba9876543210";
const BASE = "https://api.finanzasbo.com";

function memKv() {
  const m = new Map();
  return {
    async get(k) {
      return m.has(k) ? m.get(k) : null;
    },
    async put(k, v) {
      m.set(k, v);
    },
  };
}

function makeEnv() {
  return {
    HIDDEN_KV: memKv(),
    AUD,
    ACCESS_TEAM_DOMAIN: TEAM,
    ALLOWED_EMAILS: "admin@finanzasbo.com,otra@finanzasbo.com",
    ALLOW_DEV_ORIGINS: "1", // dev/test: permite reflejar localhost en CORS
  };
}

let kp; // keypair "bueno" (su pubkey va al JWKS mockeado)
let kpEvil; // keypair atacante (mismo kid, NO está en el JWKS) → bad_signature
let env;
const realFetch = globalThis.fetch;

beforeAll(async () => {
  kp = await makeKeypairAndJwks("kid-1");
  kpEvil = await makeKeypairAndJwks("kid-1");
});

beforeEach(() => {
  env = makeEnv();
  _resetJwksCache();
  globalThis.fetch = async (url) => {
    if (String(url).endsWith("/cdn-cgi/access/certs")) {
      return new Response(JSON.stringify(kp.jwks), {
        headers: { "content-type": "application/json" },
      });
    }
    throw new Error("unexpected fetch: " + url);
  };
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

async function jwt(opts = {}) {
  return mintJwt(kp.privateKey, { kid: "kid-1", aud: AUD, iss: ISS, email: ADMIN, ...opts });
}

function call(path, { method = "GET", token, cookie, origin, body } = {}, e = env) {
  const headers = {};
  if (token) headers["Cf-Access-Jwt-Assertion"] = token;
  if (cookie) headers["Cookie"] = cookie;
  if (origin) headers["Origin"] = origin;
  if (body !== undefined) headers["Content-Type"] = "text/plain";
  const req = new Request(`${BASE}${path}`, { method, headers, body });
  return worker.fetch(req, e);
}

describe("GET /v1/hidden (público)", () => {
  it("sin auth → 200 {ids:[], v:''} y CORS abierto", async () => {
    const r = await call("/v1/hidden");
    expect(r.status).toBe(200);
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(await r.json()).toEqual({ ids: [], v: "" });
  });
});

describe("rutas auth — rechazo", () => {
  it("/v1/me sin token → 401", async () => {
    expect((await call("/v1/me")).status).toBe(401);
  });

  it("/v1/me token expirado → 401", async () => {
    expect((await call("/v1/me", { token: await jwt({ exp: 1 }) })).status).toBe(401);
  });

  it("/v1/me aud equivocado → 401", async () => {
    expect((await call("/v1/me", { token: await jwt({ aud: "otro_aud" }) })).status).toBe(401);
  });

  it("/v1/me token malformado → 401", async () => {
    expect((await call("/v1/me", { token: "no.es.jwt" })).status).toBe(401);
  });

  it("/v1/me JWT válido pero email no permitido → 403", async () => {
    const r = await call("/v1/me", { token: await jwt({ email: NOTADMIN }) });
    expect(r.status).toBe(403);
    expect((await r.json()).error).toBe("email_not_allowed");
  });

  it("/v1/me firma forjada (otra clave, mismo kid) → 401 (no en JWKS)", async () => {
    // kpEvil firma con kid-1, pero el JWKS solo tiene la pubkey de kp → la
    // verificación de firma falla. Es la defensa real anti-forgery.
    const forged = await mintJwt(kpEvil.privateKey, { kid: "kid-1", aud: AUD, iss: ISS, email: ADMIN });
    expect((await call("/v1/me", { token: forged })).status).toBe(401);
  });

  it("/v1/me iss de otro team → 401", async () => {
    const r = await call("/v1/me", { token: await jwt({ iss: "https://evil.cloudflareaccess.com" }) });
    expect(r.status).toBe(401);
  });

  it("/v1/me sin claim exp → 401 (no se trata como no-expirante)", async () => {
    const r = await call("/v1/me", { token: await jwt({ exp: null }) });
    expect(r.status).toBe(401);
  });

  it("/v1/hide sin token → 401 y no escribe", async () => {
    expect((await call("/v1/hide", { method: "POST", body: ID_A })).status).toBe(401);
    expect((await (await call("/v1/hidden")).json()).ids).toEqual([]);
  });
});

describe("rutas auth — happy path + CORS", () => {
  it("/v1/me válido+permitido → 200 {email, admin:true}, CORS refleja origin + credentials", async () => {
    const r = await call("/v1/me", { token: await jwt(), origin: "http://localhost:8788" });
    expect(r.status).toBe(200);
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("http://localhost:8788");
    expect(r.headers.get("Access-Control-Allow-Credentials")).toBe("true");
    expect(await r.json()).toEqual({ email: ADMIN, admin: true });
  });

  it("auth vía cookie CF_Authorization (fallback) funciona", async () => {
    const r = await call("/v1/me", { cookie: `CF_Authorization=${await jwt()}` });
    expect(r.status).toBe(200);
    expect((await r.json()).email).toBe(ADMIN);
  });

  it("CORS prod-safe: sin ALLOW_DEV_ORIGINS, un origin localhost NO se refleja (cae a finanzasbo.com)", async () => {
    const prodEnv = { ...makeEnv(), ALLOW_DEV_ORIGINS: undefined };
    const r = await call(
      "/v1/me",
      { token: await jwt(), origin: "http://localhost:8788" },
      prodEnv
    );
    expect(r.status).toBe(200);
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("https://finanzasbo.com");
  });
});

describe("hide / unhide + v + mirror público", () => {
  it("hide (text/plain, sin OPTIONS) refleja id en /v1/hidden y cambia v", async () => {
    const r = await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_A });
    expect(r.status).toBe(200);
    const hb = await r.json();
    expect(hb).toMatchObject({ ok: true, id: ID_A });
    expect(hb.v).not.toBe("");

    const h = await (await call("/v1/hidden")).json();
    expect(h.ids).toEqual([ID_A]);
    expect(h.v).toBe(hb.v);
  });

  it("unhide quita el id y vuelve v a ''", async () => {
    await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_A });
    expect((await call("/v1/unhide", { method: "POST", token: await jwt(), body: ID_A })).status).toBe(200);
    expect(await (await call("/v1/hidden")).json()).toEqual({ ids: [], v: "" });
  });

  it("id inválido (no 16-hex) → 422", async () => {
    expect((await call("/v1/hide", { method: "POST", token: await jwt(), body: "xyz" })).status).toBe(422);
  });

  it("v determinístico: mismo set → mismo v (orden de inserción irrelevante)", async () => {
    await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_A });
    const v_AB = (await (await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_B })).json()).v;

    await call("/v1/unhide", { method: "POST", token: await jwt(), body: ID_A });
    await call("/v1/unhide", { method: "POST", token: await jwt(), body: ID_B });
    await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_B });
    const v_BA = (await (await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_A })).json()).v;

    expect(v_BA).toBe(v_AB);
    expect(v_AB).not.toBe("");
  });

  it("re-hide idempotente: v no cambia y preserva by/at original", async () => {
    const v1 = (await (await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_A })).json()).v;
    const a1 = await (await call("/v1/hidden/admin", { token: await jwt() })).json();

    const v2 = (await (await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_A })).json()).v;
    const a2 = await (await call("/v1/hidden/admin", { token: await jwt() })).json();

    expect(v2).toBe(v1);
    expect(a2.items[0].at).toBe(a1.items[0].at);
  });
});

describe("GET /v1/hidden/admin (auth) — metadata", () => {
  it("devuelve items con by/at; rechaza sin auth", async () => {
    expect((await call("/v1/hidden/admin")).status).toBe(401);

    await call("/v1/hide", { method: "POST", token: await jwt(), body: ID_A });
    const b = await (await call("/v1/hidden/admin", { token: await jwt() })).json();
    expect(b.ids).toEqual([ID_A]);
    expect(b.items).toHaveLength(1);
    expect(b.items[0]).toMatchObject({ id: ID_A, by: ADMIN });
    expect(typeof b.items[0].at).toBe("string");
  });
});

const enc = encodeURIComponent;

describe("GET /v1/login (bounce cross-domain)", () => {
  it("con sesión + return válido → 302 al return", async () => {
    const r = await call("/v1/login?return=" + enc("https://finanzasbo.com/"), { token: await jwt() });
    expect(r.status).toBe(302);
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
  });

  it("con sesión + return con path de finanzasbo.com → preserva el path", async () => {
    const r = await call("/v1/login?return=" + enc("https://finanzasbo.com/noticias"), { token: await jwt() });
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/noticias");
  });

  it("con sesión + return cross-origin (evil) → default finanzasbo.com (anti open-redirect)", async () => {
    const r = await call("/v1/login?return=" + enc("https://evil.com/"), { token: await jwt() });
    expect(r.status).toBe(302);
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
  });

  it("con sesión + return subdominio-trampa (finanzasbo.com.evil.com) → default", async () => {
    const r = await call("/v1/login?return=" + enc("https://finanzasbo.com.evil.com/"), { token: await jwt() });
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
  });

  it("con sesión + return http (scheme equivocado) → default https finanzasbo.com", async () => {
    const r = await call("/v1/login?return=" + enc("http://finanzasbo.com/"), { token: await jwt() });
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
  });

  it("con sesión sin return → default finanzasbo.com", async () => {
    const r = await call("/v1/login", { token: await jwt() });
    expect(r.status).toBe(302);
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
  });

  it("con sesión vía cookie CF_Authorization también bouncea", async () => {
    const r = await call("/v1/login?return=" + enc("https://finanzasbo.com/"), { cookie: `CF_Authorization=${await jwt()}` });
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
  });

  it("email NO admin pero sesión Access válida → igual bouncea (admin lo decide /v1/me)", async () => {
    const r = await call("/v1/login?return=" + enc("https://finanzasbo.com/"), { token: await jwt({ email: NOTADMIN }) });
    expect(r.status).toBe(302);
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
  });

  it("token inválido (firma forjada) → trata como sin sesión → 302 al login de Access", async () => {
    const forged = await mintJwt(kpEvil.privateKey, { kid: "kid-1", aud: AUD, iss: ISS, email: ADMIN });
    const r = await call("/v1/login?return=" + enc("https://finanzasbo.com/"), { token: forged });
    expect(r.status).toBe(302);
    expect(r.headers.get("Location")).toContain("/cdn-cgi/access/login/api.finanzasbo.com");
  });

  it("sin sesión → 302 al login de Access con kid=AUD y redirect_url RELATIVO de vuelta a /v1/login", async () => {
    const r = await call("/v1/login?return=" + enc("https://finanzasbo.com/"));
    expect(r.status).toBe(302);
    const loc = new URL(r.headers.get("Location"));
    expect(loc.origin + loc.pathname).toBe(`https://${TEAM}/cdn-cgi/access/login/api.finanzasbo.com`);
    expect(loc.searchParams.get("kid")).toBe(AUD);
    const rd = loc.searchParams.get("redirect_url"); // ya decodeado por URLSearchParams
    expect(rd.startsWith("/v1/login")).toBe(true); // relativo (Access rechaza cross-domain/absoluto)
    expect(rd).toBe("/v1/login?return=" + enc("https://finanzasbo.com/"));
  });

  it("sin sesión + return inválido → el redirect_url lleva el DEFAULT, nunca el evil", async () => {
    const r = await call("/v1/login?return=" + enc("https://evil.com/"));
    const rd = new URL(r.headers.get("Location")).searchParams.get("redirect_url");
    expect(rd).toBe("/v1/login?return=" + enc("https://finanzasbo.com/"));
    expect(rd).not.toContain("evil.com");
  });
});

describe("GET /v1/logout (bounce)", () => {
  it("→ 302 al logout de Access del team con returnTo allowlisteado", async () => {
    const r = await call("/v1/logout?return=" + enc("https://finanzasbo.com/"));
    expect(r.status).toBe(302);
    const loc = new URL(r.headers.get("Location"));
    expect(loc.origin + loc.pathname).toBe(`https://${TEAM}/cdn-cgi/access/logout`);
    expect(loc.searchParams.get("returnTo")).toBe("https://finanzasbo.com/");
  });

  it("return inválido → returnTo default finanzasbo.com (no evil)", async () => {
    const r = await call("/v1/logout?return=" + enc("https://evil.com/"));
    const loc = new URL(r.headers.get("Location"));
    expect(loc.searchParams.get("returnTo")).toBe("https://finanzasbo.com/");
    expect(r.headers.get("Location")).not.toContain("evil.com");
  });

  it("sin return → returnTo default finanzasbo.com", async () => {
    const r = await call("/v1/logout");
    const loc = new URL(r.headers.get("Location"));
    expect(loc.searchParams.get("returnTo")).toBe("https://finanzasbo.com/");
  });
});
