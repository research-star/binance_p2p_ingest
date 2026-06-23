# Noticias Inspector

Dev-tool **local** que corre el pipeline real de noticias de FinanzasBo **etapa por etapa**,
para entender y mejorar el mecanismo de **criterio**. No es prod, **no se deploya** (un dir
`tools/` nunca llega a `gh-pages`). Se commitea a `main` solo para tener historial y quedar
en sync con el criterio productivo.

## Regla dura (define la arquitectura)

El inspector **importa las funciones de criterio reales y NO las reimplementa**. Solo es
dueño del *loop que las secuencia* y captura sobrevivientes entre etapas. Así, cambios de
criterio en prod (umbrales, keywords, gates, slug de galería) **se reflejan solos**. El único
sync manual es estructural — ver [`SYNC.md`](SYNC.md).

El seam de replay es el `return` de `scraper.correr_scraper` (igual que
`scripts/test_noticias_budget_cache.py`): se captura el snapshot de candidatos **una vez** y
se reproduce offline por ambos caminos (pipeline real + inspector).

## Correr

```bash
pip install apscheduler          # única dep que faltaba; el resto ya está en el entorno
python tools/noticias-inspector/server.py        # http://127.0.0.1:5057
```

Desde un **git worktree** (los DBs productivos son gitignored y viven en el checkout
principal) apuntá ahí con `FB_DATA_ROOT`:

```bash
FB_DATA_ROOT=/c/Dev/binance_p2p_ingest python server.py
```

La tool **chequea las dependencias al arrancar** y avisa qué falta (no crashea): sin
`trafilatura` no hay cuerpos ni og:image; sin `sklearn`/modelo, el scoring cae a
keywords/degradado — igual que prod. El banner aparece en la barra de estado.

## Tabs

1. **Pasos (funnel)** — las 18 etapas Bolivia / 6 Latam en una tab, estilo terminal, solo
   títulos, contador de sobrevivientes por etapa y **razón de caída por ítem**. Toggle de
   carril. Label dinámico del modo de scoring (refleja el real).
2. **Cómo se vería en prod** — el set X renderizado como la sección Noticias (a grandes
   rasgos), con el cascade de imágenes real (`og:image → galería → placeholder`) y **paridad
   prod**: para El Deber / Bloomberg se anula el og:image (prod no puede servirlo) y cae a la
   galería. Marcador de en qué sección caería cada nota (hero/ranking/feed/latam).
3. **Galería** — vista inversa de `gallery_slug_v2`: por cada slug/webp, qué keywords y temas
   la enrutan. Leída **viva** de `dashboard.py`.
4. **Constantes / Sync** — constantes importadas vivas (auto-sync) vs literales inline
   (sync-manual).

## Cron (en la laptop, no el VPS)

- **⏱ Cron 1h: ON** programa una corrida `live` cada hora (dispara una al toque).
- **■ OFF** la pausa. **▶ Correr ahora** dispara ya. El frontend pollea `/api/last-run`.

## Sandbox hermético

Cada corrida **nunca escribe los DBs reales**. Siembra un `sandbox/noticias.db` (vía el
`init_schema` real, que agrega la columna `tambien_en` que `p2p_normalized.db` todavía no
tiene), copiando las filas de `noticias` desde el `p2p_normalized.db` real abierto **read-only**;
copia `cache_urls.db` al sandbox. Todo lo escrito vive en `sandbox/` (gitignored).

## Tests (acceptance)

```bash
FB_DATA_ROOT=/c/Dev/binance_p2p_ingest python parity_test.py     # set X inspector == lane real
FB_DATA_ROOT=/c/Dev/binance_p2p_ingest python hermetic_test.py   # DBs reales byte-idénticas (sha256)
```

- **`parity_test.py`** (acceptance #1) — replaya un snapshot por el `lane_bolivia` real y por
  el mirror del inspector; asegura **mismos IDs**. Es la alarma de drift: si el mirror se
  desincroniza del pipeline real, falla.
- **`hermetic_test.py`** (acceptance #2) — corre N veces y prueba que `p2p_normalized.db` y
  `cache_urls.db` quedan byte-idénticos.

## Limitaciones honestas

- **Latam** corre solo en modo `live` (su seam de replay es `latam.fetch_entries_latam`, no
  capturado). Bolivia es el target de paridad.
- **`resumen_ia.aplicar`** se stubea a no-op (sin costo de API, determinista): el inspector
  muestra el resumen extractivo, no el reescrito por IA.
- El `p2p_normalized.db` local es un **mirror posiblemente desactualizado** (el ingest de la
  laptop está apagado; la data reciente vive en el VPS — fuera de scope). El dedupe inter-día
  y el budget se calculan contra lo que el mirror tenga.
