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

  it("sin sesión → 302 al login de Access con kid=AUD y redirect_url RELATIVO (con marker del loop guard) de vuelta a /v1/login", async () => {
    const r = await call("/v1/login?return=" + enc("https://finanzasbo.com/"));
    expect(r.status).toBe(302);
    const loc = new URL(r.headers.get("Location"));
    expect(loc.origin + loc.pathname).toBe(`https://${TEAM}/cdn-cgi/access/login/api.finanzasbo.com`);
    expect(loc.searchParams.get("kid")).toBe(AUD);
    const rd = loc.searchParams.get("redirect_url"); // ya decodeado por URLSearchParams
    expect(rd.startsWith("/v1/login")).toBe(true); // relativo (Access rechaza cross-domain/absoluto)
    // el marker one-shot del loop guard viaja en el redirect_url → al volver de
    // Access lo vemos y, si seguimos sin sesión, cortamos (no re-botamos).
    expect(rd).toBe("/v1/login?_cf_login_retry=1&return=" + enc("https://finanzasbo.com/"));
  });

  it("sin sesión + return inválido → el redirect_url lleva el DEFAULT, nunca el evil", async () => {
    const r = await call("/v1/login?return=" + enc("https://evil.com/"));
    const rd = new URL(r.headers.get("Location")).searchParams.get("redirect_url");
    expect(rd).toBe("/v1/login?_cf_login_retry=1&return=" + enc("https://finanzasbo.com/"));
    expect(rd).not.toContain("evil.com");
  });

  // ── LOOP GUARD ── (vuelta de Access con el marker _cf_login_retry puesto) ──
  describe("loop guard (anti ERR_TOO_MANY_REDIRECTS)", () => {
    it("vuelve de Access con marker y SIN sesión → 403 terminal, NO re-botea a Access", async () => {
      const r = await call("/v1/login?_cf_login_retry=1&return=" + enc("https://finanzasbo.com/"));
      expect(r.status).toBe(403);
      expect(r.headers.get("Location")).toBeNull(); // no es redirect → loop cortado
      const html = await r.text();
      expect(html).toContain("No pudimos completar el inicio de sesión");
      expect(html).toContain("https://finanzasbo.com/"); // link de retorno
    });

    it("marker + token inválido (firma forjada) → 403 terminal (tampoco re-loopea)", async () => {
      const forged = await mintJwt(kpEvil.privateKey, { kid: "kid-1", aud: AUD, iss: ISS, email: ADMIN });
      const r = await call("/v1/login?_cf_login_retry=1&return=" + enc("https://finanzasbo.com/"), { token: forged });
      expect(r.status).toBe(403);
      expect(r.headers.get("Location")).toBeNull();
    });

    it("marker + sesión VÁLIDA (header) → 302 al return (el guard no bloquea un login OK)", async () => {
      const r = await call("/v1/login?_cf_login_retry=1&return=" + enc("https://finanzasbo.com/"), { token: await jwt() });
      expect(r.status).toBe(302);
      expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
    });

    it("marker + sesión VÁLIDA (cookie CF_Authorization) → 302 al return", async () => {
      const r = await call("/v1/login?_cf_login_retry=1&return=" + enc("https://finanzasbo.com/"), { cookie: `CF_Authorization=${await jwt()}` });
      expect(r.status).toBe(302);
      expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
    });

    it("error del guard con return inválido → link de retorno cae al default (anti open-redirect)", async () => {
      const r = await call("/v1/login?_cf_login_retry=1&return=" + enc("https://evil.com/"));
      expect(r.status).toBe(403);
      const html = await r.text();
      expect(html).toContain("https://finanzasbo.com/");
      expect(html).not.toContain("evil.com");
    });

    it("el dest se escapa en el HTML (sin inyección aunque el path traiga < > \")", async () => {
      const r = await call("/v1/login?_cf_login_retry=1&return=" + enc('https://finanzasbo.com/x"><script>alert(1)</script>'));
      expect(r.status).toBe(403);
      const html = await r.text();
      expect(html).not.toContain("<script>alert(1)</script>");
    });
  });
});

describe("GET /v1/logout (bounce cross-domain, dos pasos)", () => {
  it("paso 1 → 302 al team-logout de Access con returnTo a api.finanzasbo.com (app domain, no a la UI directo)", async () => {
    const r = await call("/v1/logout?return=" + enc("https://finanzasbo.com/"));
    expect(r.status).toBe(302);
    const loc = new URL(r.headers.get("Location"));
    expect(loc.origin + loc.pathname).toBe(`https://${TEAM}/cdn-cgi/access/logout`);
    // returnTo a ESTE Worker (app domain) — Access lo acepta; NUNCA a finanzasbo.com directo.
    const returnTo = new URL(loc.searchParams.get("returnTo"));
    expect(returnTo.origin).toBe("https://api.finanzasbo.com");
    expect(returnTo.pathname).toBe("/v1/logout");
    expect(returnTo.searchParams.get("done")).toBe("1");
    // el destino final viaja threadeado y allowlisteado.
    expect(returnTo.searchParams.get("return")).toBe("https://finanzasbo.com/");
  });

  it("paso 2 (done=1) → 302 final al return validado por safeReturn", async () => {
    const r = await call("/v1/logout?done=1&return=" + enc("https://finanzasbo.com/noticias"));
    expect(r.status).toBe(302);
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/noticias");
  });

  it("paso 2 con return inválido → 302 final default finanzasbo.com (no evil)", async () => {
    const r = await call("/v1/logout?done=1&return=" + enc("https://evil.com/"));
    expect(r.headers.get("Location")).toBe("https://finanzasbo.com/");
    expect(r.headers.get("Location")).not.toContain("evil.com");
  });

  it("paso 1 con return inválido → returnTo a api.finanzasbo.com con return default (no evil)", async () => {
    const r = await call("/v1/logout?return=" + enc("https://evil.com/"));
    const returnTo = new URL(new URL(r.headers.get("Location")).searchParams.get("returnTo"));
    expect(returnTo.origin).toBe("https://api.finanzasbo.com");
    expect(returnTo.searchParams.get("return")).toBe("https://finanzasbo.com/");
    expect(r.headers.get("Location")).not.toContain("evil.com");
  });

  it("paso 1 sin return → returnTo a api.finanzasbo.com con return default finanzasbo.com", async () => {
    const r = await call("/v1/logout");
    const returnTo = new URL(new URL(r.headers.get("Location")).searchParams.get("returnTo"));
    expect(returnTo.origin).toBe("https://api.finanzasbo.com");
    expect(returnTo.pathname).toBe("/v1/logout");
    expect(returnTo.searchParams.get("done")).toBe("1");
    expect(returnTo.searchParams.get("return")).toBe("https://finanzasbo.com/");
  });
});

const DAY = "2026-06-23";

describe("GET /v1/curation (público)", () => {
  it("día sin curación → 200 {order:[], treatment:'none'} y CORS abierto", async () => {
    const r = await call("/v1/curation?day=" + DAY);
    expect(r.status).toBe(200);
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(await r.json()).toEqual({ order: [], treatment: "none" });
  });

  it("día inválido (formato) → 422", async () => {
    expect((await call("/v1/curation?day=23-06-2026")).status).toBe(422);
  });

  it("día inexistente en calendario (2026-13-40) → 422", async () => {
    expect((await call("/v1/curation?day=2026-13-40")).status).toBe(422);
  });

  it("sin day → 422", async () => {
    expect((await call("/v1/curation")).status).toBe(422);
  });
});

describe("POST /v1/curate (auth + gate)", () => {
  function curate(body, opts = {}) {
    return call("/v1/curate", { method: "POST", token: opts.token, body: JSON.stringify(body), ...opts });
  }

  it("sin token → 401 y no escribe", async () => {
    expect((await call("/v1/curate", { method: "POST", body: JSON.stringify({ day: DAY, order: [ID_A], treatment: "full" }) })).status).toBe(401);
    expect(await (await call("/v1/curation?day=" + DAY)).json()).toEqual({ order: [], treatment: "none" });
  });

  it("email no admin → 403 y NO escribe", async () => {
    const r = await curate({ day: DAY, order: [ID_A], treatment: "full" }, { token: await jwt({ email: NOTADMIN }) });
    expect(r.status).toBe(403);
    expect((await r.json()).error).toBe("email_not_allowed");
    // efecto: la curación no se escribió (gate antes del put)
    expect(await (await call("/v1/curation?day=" + DAY)).json()).toEqual({ order: [], treatment: "none" });
  });

  it("válido → 200 y se refleja en GET /v1/curation", async () => {
    const r = await curate({ day: DAY, order: [ID_A, ID_B], treatment: "striped" }, { token: await jwt() });
    expect(r.status).toBe(200);
    expect(await r.json()).toMatchObject({ ok: true, day: DAY, order: [ID_A, ID_B], treatment: "striped" });
    const g = await (await call("/v1/curation?day=" + DAY)).json();
    expect(g).toEqual({ order: [ID_A, ID_B], treatment: "striped" });
  });

  it("curación es por día (otro día no la ve)", async () => {
    await curate({ day: DAY, order: [ID_A], treatment: "full" }, { token: await jwt() });
    expect(await (await call("/v1/curation?day=2026-06-24")).json()).toEqual({ order: [], treatment: "none" });
  });

  it("LWW: un segundo PUT reemplaza (no read-modify-write)", async () => {
    await curate({ day: DAY, order: [ID_A, ID_B], treatment: "striped" }, { token: await jwt() });
    await curate({ day: DAY, order: [ID_B], treatment: "none" }, { token: await jwt() });
    expect(await (await call("/v1/curation?day=" + DAY)).json()).toEqual({ order: [ID_B], treatment: "none" });
  });

  it("order con duplicados → dedupe preservando orden", async () => {
    const r = await curate({ day: DAY, order: [ID_A, ID_B, ID_A], treatment: "none" }, { token: await jwt() });
    expect((await r.json()).order).toEqual([ID_A, ID_B]);
  });

  it("treatment inválido → 422", async () => {
    expect((await curate({ day: DAY, order: [], treatment: "rainbow" }, { token: await jwt() })).status).toBe(422);
  });

  it("order con id no-16hex → 422", async () => {
    expect((await curate({ day: DAY, order: ["xyz"], treatment: "none" }, { token: await jwt() })).status).toBe(422);
  });

  it("order no-array (string) → 422", async () => {
    expect((await curate({ day: DAY, order: "abc", treatment: "none" }, { token: await jwt() })).status).toBe(422);
  });

  it("order ausente → 422", async () => {
    expect((await curate({ day: DAY, treatment: "none" }, { token: await jwt() })).status).toBe(422);
  });

  it("treatment ausente → 422", async () => {
    expect((await curate({ day: DAY, order: [] }, { token: await jwt() })).status).toBe(422);
  });

  it("order que excede MAX_ORDER (>20) → 422", async () => {
    const many = Array.from({ length: 21 }, (_, i) => i.toString(16).padStart(16, "0"));
    expect((await curate({ day: DAY, order: many, treatment: "none" }, { token: await jwt() })).status).toBe(422);
  });

  it("order = MAX_ORDER (20 únicos) → 200 (borde positivo)", async () => {
    const ids = Array.from({ length: 20 }, (_, i) => i.toString(16).padStart(16, "0"));
    const r = await curate({ day: DAY, order: ids, treatment: "none" }, { token: await jwt() });
    expect(r.status).toBe(200);
    expect((await r.json()).order).toHaveLength(20);
  });

  it("payload JSON null (parse ok, no objeto) → 422", async () => {
    expect((await call("/v1/curate", { method: "POST", token: await jwt(), body: "null" })).status).toBe(422);
  });

  it("día inválido → 422", async () => {
    expect((await curate({ day: "nope", order: [], treatment: "none" }, { token: await jwt() })).status).toBe(422);
  });

  it("body no-JSON → 422", async () => {
    expect((await call("/v1/curate", { method: "POST", token: await jwt(), body: "no es json {" })).status).toBe(422);
  });

  it("order vacío + treatment válido → 200 (tratamiento sin reorden)", async () => {
    const r = await curate({ day: DAY, order: [], treatment: "full" }, { token: await jwt() });
    expect(r.status).toBe(200);
    expect(await (await call("/v1/curation?day=" + DAY)).json()).toEqual({ order: [], treatment: "full" });
  });

  it("happy path + CORS refleja origin + credentials", async () => {
    const r = await curate({ day: DAY, order: [ID_A], treatment: "full" }, { token: await jwt(), origin: "http://localhost:8788" });
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("http://localhost:8788");
    expect(r.headers.get("Access-Control-Allow-Credentials")).toBe("true");
  });
});

describe("GET /v1/hero (público) + POST /v1/hero (auth)", () => {
  function setHero(body, opts = {}) {
    return call("/v1/hero", { method: "POST", token: opts.token, body: JSON.stringify(body), ...opts });
  }

  it("sin flag → 200 {overlay:false} y CORS abierto", async () => {
    const r = await call("/v1/hero");
    expect(r.status).toBe(200);
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(await r.json()).toEqual({ overlay: false });
  });

  it("POST sin token → 401 y no escribe", async () => {
    expect((await call("/v1/hero", { method: "POST", body: JSON.stringify({ overlay: true }) })).status).toBe(401);
    expect(await (await call("/v1/hero")).json()).toEqual({ overlay: false });
  });

  it("POST email no admin → 403 y NO escribe", async () => {
    const r = await setHero({ overlay: true }, { token: await jwt({ email: NOTADMIN }) });
    expect(r.status).toBe(403);
    expect(await (await call("/v1/hero")).json()).toEqual({ overlay: false });
  });

  it("POST válido (true) → 200 y se refleja en GET", async () => {
    const r = await setHero({ overlay: true }, { token: await jwt() });
    expect(r.status).toBe(200);
    expect(await r.json()).toMatchObject({ ok: true, overlay: true });
    expect(await (await call("/v1/hero")).json()).toEqual({ overlay: true });
  });

  it("LWW: apagar reemplaza (overlay:false)", async () => {
    await setHero({ overlay: true }, { token: await jwt() });
    await setHero({ overlay: false }, { token: await jwt() });
    expect(await (await call("/v1/hero")).json()).toEqual({ overlay: false });
  });

  it("overlay no booleano → 422", async () => {
    expect((await setHero({ overlay: "yes" }, { token: await jwt() })).status).toBe(422);
    expect((await setHero({ overlay: 1 }, { token: await jwt() })).status).toBe(422);
  });

  it("overlay ausente → 422", async () => {
    expect((await setHero({}, { token: await jwt() })).status).toBe(422);
  });

  it("body no-JSON → 422", async () => {
    expect((await call("/v1/hero", { method: "POST", token: await jwt(), body: "no json {" })).status).toBe(422);
  });

  it("happy path + CORS refleja origin + credentials", async () => {
    const r = await setHero({ overlay: true }, { token: await jwt(), origin: "http://localhost:8788" });
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe("http://localhost:8788");
    expect(r.headers.get("Access-Control-Allow-Credentials")).toBe("true");
  });
});
