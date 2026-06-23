# Sync Contract — Noticias Inspector

Qué se mantiene solo y qué hay que tocar a mano cuando el criterio de prod cambia.

## Auto-sync (NO requiere tocar la tool)

Todo esto se **importa vivo** de los módulos reales — cambiarlo en prod se refleja en el
inspector sin tocar nada. (Verificable en la tab **Constantes / Sync** → `/api/constants`.)

| Qué | De dónde se importa |
|-----|---------------------|
| Corte editorial `UMBRAL_PUNTAJE` (6.7) | `ingest_noticias` |
| Budgets `TOP_N` (14) / `LATAM_TOP_N` (8) | `ingest_noticias` → `config` |
| Dedupe `UMBRAL_DEDUP_DB`, `DEDUPE_DIAS`, eventos `UMBRAL_EVENTO_TIT/ENT` | `ingest_noticias` |
| Umbral modelo `UMBRAL_MODELO` (0.33), `UMBRAL_DEDUP`, `HORAS_ATRAS`, `CACHE_DIAS` | `noticias_ingest.scraper` |
| `KEYWORDS_EXCLUIR`, `SECCIONES_PATROCINADAS`, geo-gate, `FUENTES` | `noticias_ingest.scraper` |
| `TEMA_CATEGORIA`, `build_nota` (contrato de la nota) | `noticias_ingest.transform` |
| `gallery_slug_v2` / `GALLERY_KEYWORD_PRIORITY` / `GALLERY_TEMA_SLUGS` / `VALID_GALLERY_SLUGS` | `dashboard` |
| Flags de capacidad `TIENE_RAPIDFUZZ/GNEWS_DECODER/TRAFILATURA/...` | `noticias_ingest.scraper` |

El inspector **llama** las funciones de criterio (`evaluar` ya corrió dentro de
`correr_scraper`; `build_nota`, `agrupar_eventos`, `es_repetida`, `insertar_notas`,
`gallery_slug_v2`); nunca reimplementa un gate.

## Sync-MANUAL (actualizar la tool si cambia en prod)

1. **Agregar / quitar / reordenar una etapa del pipeline.**
   → Actualizar `pipeline_map.py` (`BOLIVIA_STAGES` / `LATAM_STAGES`) **y** el mirror en
   `inspector_core.py` (`mirror_bolivia` / `mirror_latam`).
   **Alarma automática:** `parity_test.py` falla si el mirror se desincroniza del
   `lane_bolivia` real. Corré el test después de cualquier cambio de pipeline.
   *Anchors* en el código real: `# ⓘ pipeline-anchor` al lado de `correr_scraper`
   (`noticias_ingest/scraper.py`) y `lane_bolivia` (`ingest_noticias.py`).

2. **Una constante de umbral/budget se vuelve inimportable o se mueve.**
   → Hoy **todas son importables**. La única excepción: las **bandas de impacto** (`>=8 alto`,
   `>=7 medio`) son **literales inline** en `transform.impact_de_puntaje` (sin constante
   nombrada). El inspector **llama** `impact_de_puntaje`, no las re-deriva — así que no hay
   nada que sincronizar salvo que esa función cambie de firma. Si aparece un literal nuevo
   inline, referenciarlo al módulo o listarlo acá.

3. **`PROD_IMG_UNAVAILABLE`** (`insp_config.py`) — qué fuentes NO dan og:image en prod.
   Hoy `{eldeber, bloomberg}`. Actualizar si:
   - FASE 2b habilita imágenes de Bloomberg, o
   - El Deber se desbloquea (su HTML empieza a bajar al VPS).

4. **El contrato del objeto nota cambia** (campos de `build_nota`).
   → `inspector_core._final_row` / `prod_image` / `_gallery_slug` leen campos de la nota
   (`source`, `image_url`, `tema`, `category`, `carril`, `title`, `summary`, `detail`,
   `tambien_en`). Si se renombra/quita un campo, ajustar ahí.

5. **Firma de `gallery_slug_v2` / `gallery_slug`** (no es un threshold, es un contrato).
   Hoy: `gallery_slug_v2(title, summary, detail, tema, category, carril)` y
   `gallery_slug(tema, category, carril)`. Si cambia, ajustar `inspector_core._gallery_slug`.

## Cómo se detecta el drift

- **Estructural (etapas):** `parity_test.py` — set X del inspector vs `lane_bolivia` real.
- **Constantes:** la tab Constantes/Sync muestra los valores vivos; si una desaparece, sale
  en la sección "no importables" (`live_constants().errors`).
- **Galería:** la tab Galería marca `orphans` (webp sin slug válido) y `missing_webp` (slug
  sin imagen).
