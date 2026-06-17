// Verificación del JWT de Cloudflare Access (RS256 vía WebCrypto).
// Portado de worker-spike/src/index.js, adaptado: team/AUD entran por parámetro
// (env vars), sin allowlist embebida (el gate de email vive en el router).
//
// El JWT lo emite Access tras el login OTP. Llega como header
// `Cf-Access-Jwt-Assertion` (lo inyecta Access en el edge) o, como fallback,
// en la cookie `CF_Authorization`. La validación contra el JWKS del team es la
// 2ª capa de defensa: Access ya gatea en el edge, pero el Worker re-verifica
// para no confiar ciegamente en el header.

function b64urlToBytes(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
const b64urlToString = (s) => new TextDecoder().decode(b64urlToBytes(s));

// Cache best-effort del JWKS por isolate (clave: team domain).
let _jwks = null;
let _jwksAt = 0;
let _jwksTeam = null;
async function getJwks(teamDomain) {
  if (_jwks && _jwksTeam === teamDomain && Date.now() - _jwksAt < 3_600_000) return _jwks;
  const res = await fetch(`https://${teamDomain}/cdn-cgi/access/certs`);
  if (!res.ok) throw new Error("jwks_fetch_" + res.status);
  const data = await res.json();
  _jwks = data.keys || [];
  _jwksAt = Date.now();
  _jwksTeam = teamDomain;
  return _jwks;
}

// Devuelve { ok, email, reason }.
// opts = { aud, teamDomain } — teamDomain ej. "finanzasbo.cloudflareaccess.com".
export async function verifyAccessJwt(token, { aud, teamDomain }) {
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, reason: "malformed" };

  let header, payload;
  try {
    header = JSON.parse(b64urlToString(parts[0]));
    payload = JSON.parse(b64urlToString(parts[1]));
  } catch {
    return { ok: false, reason: "unparseable" };
  }

  if (header.alg !== "RS256") return { ok: false, reason: "alg_" + header.alg };

  // exp es OBLIGATORIO (un token sin exp no debe tratarse como no-expirante).
  // SKEW de 60s tolera desfase de reloj sin abrir una ventana real.
  const now = Math.floor(Date.now() / 1000);
  const SKEW = 60;
  if (typeof payload.exp !== "number" || payload.exp < now - SKEW)
    return { ok: false, reason: "expired" };
  if (payload.nbf && payload.nbf > now + SKEW) return { ok: false, reason: "not_yet_valid" };

  if (payload.iss !== `https://${teamDomain}`) return { ok: false, reason: "iss_mismatch" };

  const auds = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!auds.includes(aud)) return { ok: false, reason: "aud_mismatch" };

  let jwks;
  try {
    jwks = await getJwks(teamDomain);
  } catch (e) {
    return { ok: false, reason: e.message };
  }
  const jwk = jwks.find((k) => k.kid === header.kid);
  if (!jwk) return { ok: false, reason: "kid_not_in_jwks" };

  const key = await crypto.subtle.importKey(
    "jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]
  );
  const signed = new TextEncoder().encode(parts[0] + "." + parts[1]);
  const valid = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5", key, b64urlToBytes(parts[2]), signed
  );
  if (!valid) return { ok: false, reason: "bad_signature" };

  const email = payload.email || (payload.identity && payload.identity.email) || null;
  if (!email) return { ok: false, reason: "no_email" };
  return { ok: true, email, reason: "ok" };
}

// Token desde header (preferido) o cookie. { token, src }.
export function getAccessToken(req) {
  const h = req.headers.get("Cf-Access-Jwt-Assertion");
  if (h) return { token: h, src: "header" };
  const m = (req.headers.get("Cookie") || "").match(/(?:^|;\s*)CF_Authorization=([^;]+)/);
  return m ? { token: m[1], src: "cookie" } : { token: null, src: "none" };
}

// Helper de test: resetea el cache del JWKS (no se usa en prod).
export function _resetJwksCache() {
  _jwks = null;
  _jwksAt = 0;
  _jwksTeam = null;
}
