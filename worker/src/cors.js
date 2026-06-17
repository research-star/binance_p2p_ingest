// CORS — el Worker es dueño del CORS (no se delega en Access).
// - /v1/hidden (público, sin credenciales) → CORS abierto ("*").
// - Rutas autenticadas → refleja el Origin permitido + credenciales.
//   Origin de prod = https://finanzasbo.com SIEMPRE. localhost/127.0.0.1 se
//   permite SOLO si env.ALLOW_DEV_ORIGINS está seteado — esa var NO existe en el
//   wrangler.toml de prod, así que el Worker productivo nunca refleja un origin
//   de dev con credenciales (evita que JS en localhost use la cookie de Access
//   de un admin). En `wrangler dev`/tests se setea para habilitar dev.
//   Nunca "*" en rutas con credenciales.

const PROD_ORIGIN = "https://finanzasbo.com";

export function isAllowedOrigin(origin, env) {
  if (!origin) return false;
  if (origin === PROD_ORIGIN) return true;
  if (!env || !env.ALLOW_DEV_ORIGINS) return false;
  try {
    const u = new URL(origin);
    return u.hostname === "localhost" || u.hostname === "127.0.0.1";
  } catch {
    return false;
  }
}

// CORS para la ruta pública /v1/hidden: abierto, sin credenciales.
export function publicCors() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Vary": "Origin",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
  };
}

// CORS para rutas autenticadas: refleja el Origin permitido + credenciales.
// Si el Origin no está permitido, cae al de prod (no filtra acceso — eso lo hace
// el gate de Access/email; solo evita reflejar un Origin arbitrario).
export function authCors(origin, env) {
  const allowed = isAllowedOrigin(origin, env) ? origin : PROD_ORIGIN;
  return {
    "Access-Control-Allow-Origin": allowed,
    "Vary": "Origin",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}
