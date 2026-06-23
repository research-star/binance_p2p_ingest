// KV = fuente de verdad de los ids ocultos (la tabla noticias_hidden del build
// es solo un mirror de esto).
//
// Schema: UNA sola key materializa todo (lectura de 1 key sirve a las 3 rutas):
//   key "index" → { ids: string[] (orden asc), v: string, meta: { [id]: {by, at} } }
//     - ids  : lista materializada de ids ocultos (16-hex), ordenada.
//     - v    : versión del set = hash del set ordenado (ver computeV). Alimenta
//              el hidden_v del skip-fast del build.
//     - meta : por id, quién (email) y cuándo (ISO8601) se ocultó. Para /admin.
//
// v = hash(set ordenado) ⇒ MISMO set → MISMO v. Esto evita republish espurio:
// re-ocultar un id ya oculto (idempotente) no cambia v, y des-ocultar y volver a
// ocultar el mismo set restaura el mismo v. Un contador, en cambio, cambiaría v
// en cada write aunque el set no cambie. Por eso: hash, no contador.

const INDEX_KEY = "index";

export async function computeV(ids) {
  if (!ids.length) return "";
  const data = new TextEncoder().encode([...ids].sort().join(","));
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 16);
}

export async function readIndex(kv) {
  const raw = await kv.get(INDEX_KEY);
  if (!raw) return { ids: [], v: "", meta: {} };
  try {
    const o = JSON.parse(raw);
    return { ids: o.ids || [], v: o.v || "", meta: o.meta || {} };
  } catch {
    return { ids: [], v: "", meta: {} };
  }
}

async function persist(kv, meta) {
  const ids = Object.keys(meta).sort();
  const v = await computeV(ids);
  const value = { ids, v, meta };
  await kv.put(INDEX_KEY, JSON.stringify(value));
  return value;
}

// Idempotente: re-ocultar un id ya oculto preserva el by/at original (set
// inalterado → v inalterado → sin republish espurio).
// NOTA: read-modify-write sobre una sola key. KV no tiene transacciones; con
// writes concurrentes gana el último (last-write-wins). Aceptable: los hides son
// raros y de un admin a la vez. Si en el futuro hiciera falta, se puede agregar
// concurrencia optimista o un Durable Object.
export async function hide(kv, id, by, at) {
  const { meta } = await readIndex(kv);
  if (!meta[id]) meta[id] = { by, at };
  return persist(kv, meta);
}

export async function unhide(kv, id) {
  const { meta } = await readIndex(kv);
  delete meta[id];
  return persist(kv, meta);
}

// ── Curación editorial del riel "Lo más relevante" (presentacional, runtime) ──
// Vive en el MISMO KV (HIDDEN_KV) pero en claves aparte, por día:
//   key "curation:<YYYY-MM-DD>" → { order: string[] (ids 16-hex), treatment }
//     - order     : orden explícito de las notas del riel (las no listadas el
//                   frontend las pone detrás, en su orden por impacto).
//     - treatment : "none" | "striped" | "full" — tratamiento visual del BLOQUE.
// DIVERGE de hide a propósito: la curación es PRESENTACIONAL (no toca el set de
// ocultos ni el cómputo de `v` ni el build), así que se escribe con PUT directo
// (last-write-wins) — un solo admin a la vez, sin read-modify-write. La validación
// de inputs vive en el router (index.js); getCuration es defensivo en lectura.

export const TREATMENTS = new Set(["none", "striped", "full"]);

export function curationKey(day) {
  return "curation:" + day;
}

export async function getCuration(kv, day) {
  const raw = await kv.get(curationKey(day));
  if (!raw) return { order: [], treatment: "none" };
  try {
    const o = JSON.parse(raw);
    const order = Array.isArray(o.order) ? o.order.filter((x) => typeof x === "string") : [];
    const treatment = TREATMENTS.has(o.treatment) ? o.treatment : "none";
    return { order, treatment };
  } catch {
    return { order: [], treatment: "none" };
  }
}

export async function putCuration(kv, day, order, treatment) {
  const value = { order, treatment };
  await kv.put(curationKey(day), JSON.stringify(value));
  return value;
}
