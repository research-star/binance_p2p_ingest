# worker/ — API "ocultar noticias" (FinanzasBo)

Worker de Cloudflare que es **fuente de verdad de los ids de noticias ocultas**.
El build del dashboard lee `/v1/hidden` y materializa la tabla `noticias_hidden`
(mirror) para filtrar el feed. La admin UI (PR-C) consume `/v1/me`, `/v1/hide`,
`/v1/unhide`, `/v1/hidden/admin`.

> Construcción local. **No se deploya desde acá** — deploy, KV remoto, Access y
> emails se configuran en un brief posterior (gate de Diego). `worker-spike/` (en
> la raíz, untracked) fue el spike de auth/CORS; este dir es el Worker real.

## Rutas

| Método | Ruta | Auth | Respuesta |
|---|---|---|---|
| GET  | `/v1/hidden`       | público | `{ ids, v }` |
| GET  | `/v1/me`           | sí | `{ email, admin: true }` |
| GET  | `/v1/hidden/admin` | sí | `{ ids, v, items: [{id, by, at}] }` |
| POST | `/v1/hide`         | sí | id en `text/plain` → `{ ok, id, v }` |
| POST | `/v1/unhide`       | sí | id en `text/plain` → `{ ok, id, v }` |

- **Writes en `text/plain`** → request CORS "simple", **sin preflight OPTIONS**.
- **CORS**: el Worker es dueño. `/v1/hidden` abierto (`*`, sin credenciales);
  rutas auth reflejan el Origin permitido con `credentials`. En prod el único
  Origin permitido es `https://finanzasbo.com`. `localhost`/`127.0.0.1` se permite
  **solo si `ALLOW_DEV_ORIGINS` está seteado** (dev/tests), var que NO va al
  `wrangler.toml` de prod — así el Worker productivo nunca refleja un origin de
  dev con la cookie de Access. En dev: `wrangler dev --var ALLOW_DEV_ORIGINS:1`.

## Auth (gate doble)

Rutas protegidas exigen **JWT de Access válido AND `email ∈ ALLOWED_EMAILS`**.
- Token: header `Cf-Access-Jwt-Assertion` (lo inyecta Access) o cookie
  `CF_Authorization` (fallback).
- Validación (`src/auth.js`): `alg=RS256`, `exp`/`nbf`, `iss=https://<team>`,
  `aud` incluye `AUD`, y firma contra el JWKS `https://<team>/cdn-cgi/access/certs`.
- `AUD` y `ACCESS_TEAM_DOMAIN` son públicos (en `wrangler.toml [vars]`).
  `ALLOWED_EMAILS` entra **al deploy** (no en el toml). Sin él → rutas auth
  fallan **cerrado** (403) aun con JWT válido (fail-safe).

## KV — schema

Una sola key materializa todo (1 read sirve a las 3 rutas):

```
key "index" → {
  ids:  string[]                 // ids ocultos (16-hex), orden asc
  v:    string                   // versión del set (ver abajo)
  meta: { [id]: { by, at } }     // by = email; at = ISO8601
}
```

`/v1/hidden` devuelve `{ ids, v }`; `/v1/hidden/admin` agrega `meta` como `items`.

### Cómputo de `v`

`v = SHA-256(ids ordenados, join ",")[:16hex]`; **set vacío → `v = ""`**.

Es un **hash del set ordenado**, no un contador, a propósito:
- **Mismo set → mismo `v`.** Re-ocultar un id ya oculto (idempotente) no cambia
  `v`; des-ocultar y re-ocultar el mismo set restaura el mismo `v`.
- Esto evita **republish espurio** del build: el `hidden_v` del skip-fast solo
  avanza cuando el set realmente cambia. Un contador avanzaría en cada write.

## Asimetría hide/unhide

`hide` es **instantáneo** (KV write inmediato → `/v1/hidden` lo refleja ya).
`unhide` se ve en el dashboard **al próximo rebuild** (≤12 min, cron del build).

## Dev / tests (local, sin deploy)

```
npm install
npm test            # Vitest (node): corre el handler con KV in-memory + JWKS mockeado
npm run dev         # wrangler dev (Miniflare/workerd) en localhost
bash scripts/smoke.sh   # smoke del runtime real (Miniflare): ruta pública + rechazos auth
```

Dos capas de prueba:
- **`npm test`** — el handler `worker.fetch(req, env)` corre en node (Request/
  Response/URL/WebCrypto/fetch globales). KV = stub in-memory (mismo contrato
  get/put); el JWKS del team se mockea vía `global.fetch` con un keypair RSA
  self-signed (`test/helpers.js`), así el verificador valida JWTs minteados
  localmente sin tocar Access real. Cubre el happy-path auth, los rechazos, las
  transiciones de KV, el determinismo de `v` y la metadata.
- **`scripts/smoke.sh`** — levanta `wrangler dev` (workerd/Miniflare real) y
  verifica que el Worker bootea, `/v1/hidden` responde y las rutas auth rechazan
  sin token. Fidelidad de runtime; el JWT real lo valida Diego contra la app
  Access viva al deploy.
