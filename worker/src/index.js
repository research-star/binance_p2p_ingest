// Worker "ocultar noticias" — API de ids ocultos para FinanzasBo.
// Rutas:
//   GET  /v1/hidden        público  → { ids, v }   (lo consume el build)
//   GET  /v1/me            auth     → { email, admin } (lo usa la admin UI)
//   GET  /v1/hidden/admin  auth     → { ids, v, items[{id,by,at}] }
//   POST /v1/hide          auth     → id en text/plain → agrega a KV, recomputa v
//   POST /v1/unhide        auth     → id en text/plain → quita de KV, recomputa v
//
// Gate de las rutas auth (doble): JWT de Access válido AND email ∈ ALLOWED_EMAILS.
// Writes en text/plain (request CORS "simple" → sin preflight). El Worker es
// dueño del CORS (ver cors.js).
//
// Env (wrangler.toml [vars] / secrets al deploy):
//   AUD                — Application Audience tag del Access App (público).
//   ACCESS_TEAM_DOMAIN — ej. "finanzasbo.cloudflareaccess.com".
//   ALLOWED_EMAILS     — CSV de emails admin. Se setea AL DEPLOY. Si está vacío,
//                        las rutas auth fallan cerrado (403) aun con JWT válido.

import { publicCors, authCors } from "./cors.js";
import { verifyAccessJwt, getAccessToken } from "./auth.js";
import { readIndex, hide, unhide } from "./store.js";

const ID_RE = /^[0-9a-f]{16}$/;

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status: status || 200,
    headers: { "Content-Type": "application/json", ...(headers || {}) },
  });
}

function allowedEmails(env) {
  return new Set(
    (env.ALLOWED_EMAILS || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean)
  );
}

// Gate doble. Devuelve { ok:true, email } o { ok:false, status, reason }.
async function gate(req, env) {
  const { token } = getAccessToken(req);
  if (!token) return { ok: false, status: 401, reason: "no_auth" };
  const v = await verifyAccessJwt(token, {
    aud: env.AUD,
    teamDomain: env.ACCESS_TEAM_DOMAIN,
  });
  if (!v.ok) return { ok: false, status: 401, reason: v.reason };
  if (!allowedEmails(env).has(v.email.toLowerCase()))
    return { ok: false, status: 403, reason: "email_not_allowed" };
  return { ok: true, email: v.email };
}

export default {
  async fetch(req, env) {
    const path = new URL(req.url).pathname;
    const origin = req.headers.get("Origin");
    const aCors = authCors(origin, env);

    // Preflight: no debería dispararse para text/plain sin headers custom, pero
    // si llega, respondemos OK con el CORS que corresponde al path.
    if (req.method === "OPTIONS") {
      const headers = path === "/v1/hidden" ? publicCors() : aCors;
      return new Response(null, { status: 204, headers });
    }

    // ── GET /v1/hidden — PÚBLICO ──
    if (path === "/v1/hidden" && req.method === "GET") {
      const { ids, v } = await readIndex(env.HIDDEN_KV);
      return json({ ids, v }, 200, publicCors());
    }

    // ── GET /v1/me — auth ──
    if (path === "/v1/me" && req.method === "GET") {
      const g = await gate(req, env);
      if (!g.ok) return json({ admin: false, error: g.reason }, g.status, aCors);
      return json({ email: g.email, admin: true }, 200, aCors);
    }

    // ── GET /v1/hidden/admin — auth (ids + metadata) ──
    if (path === "/v1/hidden/admin" && req.method === "GET") {
      const g = await gate(req, env);
      if (!g.ok) return json({ error: g.reason }, g.status, aCors);
      const { ids, v, meta } = await readIndex(env.HIDDEN_KV);
      const items = ids.map((id) => ({
        id,
        by: meta[id]?.by ?? null,
        at: meta[id]?.at ?? null,
      }));
      return json({ ids, v, items }, 200, aCors);
    }

    // ── POST /v1/hide — auth + gate ──
    if (path === "/v1/hide" && req.method === "POST") {
      const g = await gate(req, env);
      if (!g.ok) return json({ ok: false, error: g.reason }, g.status, aCors);
      const id = (await req.text()).trim();
      if (!ID_RE.test(id)) return json({ ok: false, error: "bad_id" }, 422, aCors);
      const { v } = await hide(env.HIDDEN_KV, id, g.email, new Date().toISOString());
      return json({ ok: true, id, v }, 200, aCors);
    }

    // ── POST /v1/unhide — auth + gate ──
    if (path === "/v1/unhide" && req.method === "POST") {
      const g = await gate(req, env);
      if (!g.ok) return json({ ok: false, error: g.reason }, g.status, aCors);
      const id = (await req.text()).trim();
      if (!ID_RE.test(id)) return json({ ok: false, error: "bad_id" }, 422, aCors);
      const { v } = await unhide(env.HIDDEN_KV, id);
      return json({ ok: true, id, v }, 200, aCors);
    }

    return json({ error: "not_found", path }, 404, publicCors());
  },
};
