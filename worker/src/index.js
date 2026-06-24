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
import { readIndex, hide, unhide, getCuration, putCuration, TREATMENTS } from "./store.js";

const ID_RE = /^[0-9a-f]{16}$/;
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;
// Tope defensivo del array `order` (el riel son 5 notas; damos holgura sin abrir
// la puerta a inflar el valor de KV con writes admin maliciosos/buggeados).
const MAX_ORDER = 20;

// Día válido = ISO YYYY-MM-DD Y fecha real (rechaza 2026-13-40): el round-trip por
// Date descarta días/meses fuera de rango que el regex solo no atrapa.
function isValidDay(day) {
  if (typeof day !== "string" || !DAY_RE.test(day)) return false;
  const d = new Date(day + "T00:00:00Z");
  return !isNaN(d.getTime()) && d.toISOString().slice(0, 10) === day;
}

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

// Allowlist anti open-redirect del bounce login/logout: el `return` SOLO puede
// apuntar al origin exacto de la UI (mismo valor que PROD_ORIGIN en cors.js).
// Cualquier otro host/scheme/puerto → default. Preserva el path dentro del origin.
const RETURN_ORIGIN = "https://finanzasbo.com";
function safeReturn(reqUrl) {
  const raw = new URL(reqUrl).searchParams.get("return");
  if (!raw) return RETURN_ORIGIN + "/";
  try {
    const u = new URL(raw);
    return u.origin === RETURN_ORIGIN ? u.href : RETURN_ORIGIN + "/";
  } catch {
    return RETURN_ORIGIN + "/";
  }
}

function redirect(location) {
  return new Response(null, { status: 302, headers: { Location: location } });
}

// Loop guard de /v1/login. Marker one-shot que adjuntamos al redirect_url que
// mandamos a Access. Si volvemos del login con el marker puesto y TODAVÍA sin
// sesión válida acá, cortamos con un error limpio en vez de re-botar a Access
// (eso sería el ERR_TOO_MANY_REDIRECTS que reportó el smoke).
const LOGIN_RETRY = "_cf_login_retry";

// Flag one-shot del bounce de logout: marca el segundo salto (post team-logout de
// Access, cookie ya borrada) para hacer el 302 final a la UI en vez de re-botar.
const LOGOUT_DONE = "done";

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Respuesta TERMINAL del loop guard: HTML estático sin auto-redirect → rompe el
// loop de forma definitiva. 403 porque, post-login, seguimos sin sesión legible
// acá (típicamente la cookie de Access no llega a /v1/login; ver root-cause). El
// `dest` ya pasó por safeReturn (origin finanzasbo.com), pero igual lo escapamos
// antes de meterlo en el HTML (defensa en profundidad anti-XSS).
function loginLoopError(dest) {
  const href = escapeHtml(dest);
  const body =
    '<!doctype html><html lang="es"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    "<title>No pudimos iniciar sesión</title></head>" +
    '<body style="font-family:system-ui,-apple-system,sans-serif;max-width:34rem;' +
    'margin:4rem auto;padding:0 1.25rem;line-height:1.55;color:#1f2933">' +
    '<h1 style="font-size:1.4rem">No pudimos completar el inicio de sesión</h1>' +
    "<p>Tu sesión de Cloudflare Access no llegó a la app después del login. " +
    "Suele ser un tema de configuración del Access, no de tu cuenta.</p>" +
    '<p><a href="' + href + '">Volver a FinanzasBo</a> e intentá de nuevo. ' +
    "Si el problema persiste, avisá al equipo.</p></body></html>";
  return new Response(body, {
    status: 403,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
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
      const isPublic = path === "/v1/hidden" || path === "/v1/curation";
      const headers = isPublic ? publicCors() : aCors;
      return new Response(null, { status: 204, headers });
    }

    // ── GET /v1/hidden — PÚBLICO ──
    if (path === "/v1/hidden" && req.method === "GET") {
      const { ids, v } = await readIndex(env.HIDDEN_KV);
      return json({ ids, v }, 200, publicCors());
    }

    // ── GET /v1/curation?day=<YYYY-MM-DD> — PÚBLICO (molde de /v1/hidden) ──
    // Devuelve la curación del riel de ese día: { order, treatment }. Si no hay
    // curación (clave ausente) → { order:[], treatment:"none" } = el default que
    // ya renderiza el frontend. El público lo lee en runtime (no por build).
    if (path === "/v1/curation" && req.method === "GET") {
      const day = new URL(req.url).searchParams.get("day") || "";
      if (!isValidDay(day)) return json({ error: "bad_day" }, 422, publicCors());
      const { order, treatment } = await getCuration(env.HIDDEN_KV, day);
      return json({ order, treatment }, 200, publicCors());
    }

    // ── GET /v1/login — bounce de login cross-domain ──
    // La UI vive en finanzasbo.com; el Access app, en api.finanzasbo.com. Access
    // NO permite redirect cross-domain tras login (rechaza un redirect_url a otro
    // host con "Invalid redirect URL"; sólo acepta un path RELATIVO del propio app
    // — verificado contra Access real). Por eso el retorno a la UI lo hace ESTE
    // Worker, ya con sesión de Access:
    //   - Con sesión de Access válida (header Cf-Access-Jwt-Assertion inyectado en
    //     rutas protegidas, o cookie CF_Authorization como fallback; cualquier
    //     email — la autorización admin la decide /v1/me, no este bounce) → 302 al
    //     `return` allowlisteado.
    //   - Sin sesión → 302 al login de Access (kid=AUD + redirect_url RELATIVO de
    //     vuelta a /v1/login con el return). Tras el OTP, Access nos devuelve acá.
    // LOOP GUARD (no negociable): /v1/login NO es ruta protegida por Access → el
    // edge no inyecta Cf-Access-Jwt-Assertion acá; sólo podemos leer la cookie
    // CF_Authorization. Si tras el login esa cookie NO llega a /v1/login (ruta
    // no-protegida — la causa raíz del loop reportado), volveríamos sin sesión
    // legible y re-botaríamos a Access en bucle (ERR_TOO_MANY_REDIRECTS). El marker
    // one-shot LOGIN_RETRY lo corta: al volver del login con el marker puesto y aún
    // sin sesión válida, devolvemos un error limpio en vez de re-botar.
    if (path === "/v1/login" && req.method === "GET") {
      const dest = safeReturn(req.url);
      const { token } = getAccessToken(req);
      let authed = false;
      if (token) {
        const v = await verifyAccessJwt(token, {
          aud: env.AUD,
          teamDomain: env.ACCESS_TEAM_DOMAIN,
        });
        authed = v.ok;
      }
      // Sesión válida (header o cookie) → bounce, incluso con el marker puesto:
      // el guard nunca bloquea un login que SÍ funcionó (evita falso negativo).
      if (authed) return redirect(dest);
      // Ya volvimos del login de Access (marker puesto) y seguimos sin sesión →
      // NO re-botamos: error limpio. Peor caso = 403, nunca loop infinito.
      if (new URL(req.url).searchParams.get(LOGIN_RETRY) === "1") {
        return loginLoopError(dest);
      }
      const back =
        "/v1/login?" + LOGIN_RETRY + "=1&return=" + encodeURIComponent(dest);
      const loginUrl =
        "https://" + env.ACCESS_TEAM_DOMAIN +
        "/cdn-cgi/access/login/api.finanzasbo.com?kid=" + env.AUD +
        "&redirect_url=" + encodeURIComponent(back);
      return redirect(loginUrl);
    }

    // ── GET /v1/logout — bounce de logout cross-domain (dos pasos) ──
    // La UI vive en finanzasbo.com; el Access app, en api.finanzasbo.com. El
    // `returnTo` del /cdn-cgi/access/logout SÓLO acepta el authdomain del team, sus
    // subdominios, y hostnames que son apps de Access en la org (verificado).
    // finanzasbo.com NO es app de Access → un returnTo directo a la UI lo rechaza
    // con "Invalid redirect URL". api.finanzasbo.com SÍ es app → el retorno a la UI
    // lo hace ESTE Worker, en dos saltos (mismo patrón que el bounce de login):
    //   - Paso 1 (/v1/logout sin flag): 302 al team-logout de Access con
    //     returnTo = URL ABSOLUTA en api.finanzasbo.com (este Worker), de vuelta a
    //     /v1/logout?done=1, preservando el `return` final (URL-encoded). Access
    //     acepta ese returnTo por ser app domain, borra la cookie y nos devuelve.
    //   - Paso 2 (/v1/logout?done=1): ya sin sesión → 302 al destino final
    //     validado por safeReturn (default https://finanzasbo.com/).
    // /v1/logout NO está gateado por Access (alcanzable sin sesión).
    if (path === "/v1/logout" && req.method === "GET") {
      const reqUrl = new URL(req.url);
      const dest = safeReturn(req.url); // destino final, allowlisteado a finanzasbo.com
      // Paso 2: volvimos del team-logout (cookie borrada) → 302 final a la UI.
      if (reqUrl.searchParams.get(LOGOUT_DONE) === "1") {
        return redirect(dest);
      }
      // Paso 1: mandamos a Access a borrar la cookie. returnTo apunta a ESTE Worker
      // (api.finanzasbo.com = app domain → Access lo acepta), threading el `return`
      // final para resolverlo en el paso 2.
      const back =
        reqUrl.origin + "/v1/logout?" + LOGOUT_DONE + "=1&return=" +
        encodeURIComponent(dest);
      const logoutUrl =
        "https://" + env.ACCESS_TEAM_DOMAIN +
        "/cdn-cgi/access/logout?returnTo=" + encodeURIComponent(back);
      return redirect(logoutUrl);
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

    // ── POST /v1/curate — auth + gate (molde de /v1/hide) ──
    // Body JSON en text/plain (request CORS "simple", sin preflight; igual que el
    // hide). { day, order, treatment }. PUT directo a curation:<day> (LWW). El
    // `order` se dedupea preservando el orden; los ids deben ser 16-hex.
    if (path === "/v1/curate" && req.method === "POST") {
      const g = await gate(req, env);
      if (!g.ok) return json({ ok: false, error: g.reason }, g.status, aCors);
      let payload;
      try {
        payload = JSON.parse(await req.text());
      } catch {
        return json({ ok: false, error: "bad_json" }, 422, aCors);
      }
      const day = payload && payload.day;
      const treatment = payload && payload.treatment;
      const order = payload && payload.order;
      if (!isValidDay(day)) return json({ ok: false, error: "bad_day" }, 422, aCors);
      if (!TREATMENTS.has(treatment))
        return json({ ok: false, error: "bad_treatment" }, 422, aCors);
      if (
        !Array.isArray(order) ||
        order.length > MAX_ORDER ||
        !order.every((x) => typeof x === "string" && ID_RE.test(x))
      )
        return json({ ok: false, error: "bad_order" }, 422, aCors);
      // Dedupe preservando orden (defensa: el front no debería mandar duplicados).
      const seen = new Set();
      const clean = [];
      for (const id of order) {
        if (!seen.has(id)) {
          seen.add(id);
          clean.push(id);
        }
      }
      const value = await putCuration(env.HIDDEN_KV, day, clean, treatment);
      return json({ ok: true, day, ...value }, 200, aCors);
    }

    return json({ error: "not_found", path }, 404, publicCors());
  },
};
