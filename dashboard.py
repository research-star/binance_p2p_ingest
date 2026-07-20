#!/usr/bin/env python3
"""
dashboard.py — Genera dashboard HTML desde p2p_normalized.db.

Uso:
    python3 dashboard.py                           # defaults
    python3 dashboard.py --db mi_base.db           # DB custom
    python3 dashboard.py --output dashboard.html   # output custom
    python3 dashboard.py --output-en en.html       # output EN custom
    python3 dashboard.py --csv                     # también exporta CSV horario

Produce .html autocontenidos que se abren en cualquier navegador: uno en
español (--output) y uno en inglés (--output-en, default <dir>/en/index.html),
horneados desde el mismo template vía i18n_bake (doble bake, misma data).
"""

import argparse
import copy
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
except ImportError:
    pass  # graceful: sin dotenv, env vars deben venir del entorno (counter → "—")

from config import BCB_RATE, NORMALIZED_DB, DASHBOARD_HTML, BCB_REF_JSON, BCB_TCO_JSON, BCB_TRE_JSON, TEMPLATE_HTML, MODULOS_NO_BAKEADOS
from scripts.fetch_umami_stats import fetch_visits
import boletin
import i18n_bake

DEFAULT_DB = NORMALIZED_DB
DEFAULT_OUTPUT = DASHBOARD_HTML
BCB_REF_FILE = BCB_REF_JSON
BCB_TCO_FILE = BCB_TCO_JSON

# Mapeo canónico de nombres de bancos (raw → display).
BANK_CANONICAL = {
    'BancoDeBolivia':  'Banco de Bolivia',
    'BancoDeCredito':  'Banco de Crédito BCP',
    'BancoEconomico':  'Banco Económico',
    'BancoFIE':        'Banco FIE',
    'BancoFassil':     'Banco Fassil',
    'BancoGanadero':   'Banco Ganadero',
    'BancoSantaCruz':  'Banco SantaCruz',
    'BancoSolidario':  'Banco Solidario',
    'BancoUnion':      'Banco Unión',
    'SoliPagos':       'SoliPagos',
    'TigoMoney':       'Tigo Money',
}

# Labels legibles para los slugs del INE (divisiones COICOP del IPC y grandes
# grupos del IPP). El slug interno preserva el source del INE tal cual —
# incluido el typo 'agricolas' sin tilde — y el display se corrige acá.
# Orden de inserción = orden canónico COICOP / orden del cuadro IPP; el
# frontend lo respeta para leyendas y lo re-ordena solo donde la vista lo
# pide (ranking).
INE_IPC_DIVISIONES = {
    'alimentos_y_bebidas_no_alcoholicas':            'Alimentos y bebidas no alcohólicas',
    'bebidas_alcoholicas_y_tabaco':                  'Bebidas alcohólicas y tabaco',
    'prendas_de_vestir_y_calzado':                   'Prendas de vestir y calzado',
    'vivienda_y_servicios_basicos':                  'Vivienda y servicios básicos',
    'muebles_bienes_y_servicios_domesticos':         'Muebles y servicios domésticos',
    'salud':                                         'Salud',
    'transporte':                                    'Transporte',
    'comunicaciones':                                'Comunicaciones',
    'recreacion_y_cultura':                          'Recreación y cultura',
    'educacion':                                     'Educación',
    'alimentos_y_bebidas_consumidos_fuera_del_hogar': 'Alimentos fuera del hogar',
    'bienes_y_servicios_diversos':                   'Bienes y servicios diversos',
}
INE_IPP_GRUPOS = {
    'agricolas':                     'Agrícolas',
    'pecuaria':                      'Pecuaria',
    'pesca':                         'Pesca',
    'otros_minerales_y_gas_natural': 'Otros minerales y gas natural',
    'industria_manufacturera':       'Industria manufacturera',
    'servicios':                     'Servicios',
}


# ── Galería de imágenes temáticas (v1) ──────────────────────────────────────
# Matching por `tema` de la clasificación v1 (#86; taxonomía canónica en
# noticias_ingest/scraper.py:512-645). Cascada del slot de imagen del front
# (template.html npImg): og:image → GALERÍA → placeholder. Acá precomputamos el
# slug por nota; el front solo arma /gal-<slug>.webp (assets PLANOS en static/,
# servidos en raíz — publish_dashboard.py copia static/ sin recursar subdirs).
#
# Cascada (decisiones cerradas del ticket galería):
#   1. carril == 'latam'                       → 'internacional' (destacada deja de ser placeholder)
#   2. tema fino (≠ '' y ≠ 'General', mapeado) → slug fijo del tema
#   3. category genérica                       → 'economia' | 'politica'
#   4. sin señal                               → None (front cae al placeholder CSS)
# NO usa temaConfianza (NULL en histórico → mataría cobertura) ni entidades (v2).
#
# SLUGS FIJOS, no kebab del tema: 14 nombres cortos estables contra los que se
# curan las fotos reales en paralelo (swap-in drop-in, mismo naming). Mapa
# explícito tema canónico → slug; un tema sin entrada cae a la genérica por
# category — nunca sirve un /gal-*.webp inexistente.
GALLERY_TEMA_SLUGS = {
    'Combustibles / YPFB':             'combustibles',
    'Tipo de cambio / Dólar':          'tipo-cambio',
    'Litio / Minería':                 'litio',
    'Agropecuario / Soya':             'agro',
    'Deuda / Finanzas':                'deuda',
    'Inflación / Precios':             'inflacion',
    'Exportaciones / Comercio':        'exportaciones',
    'Inversión / Infraestructura':     'inversion',
    'Elecciones / Política económica': 'elecciones',
    'Bloqueos / Conflictos':           'bloqueos',
    'EMAPA / Alimentos':               'alimentos',
}


def gallery_slug(tema, category, carril):
    """Slug de galería por `tema` exacto (FALLBACK del motor v1.1; None → placeholder).
    Cascada: latam→internacional · tema mapeado→slug · category→economia/politica · else None."""
    if carril == 'latam':
        return 'internacional'
    if tema and tema != 'General':
        slug = GALLERY_TEMA_SLUGS.get(tema)
        if slug:
            return slug
    if category in ('economia', 'politica'):
        return category
    return None


# ── Galería v1.1: PASS de prioridad por keyword (PRIMARIO) ───────────────────
# Antepone un escaneo del TEXTO de la nota (title+summary+detail) al lookup por
# `tema`. Cuando co-ocurren varios tópicos, gana el de mayor prioridad (orden de
# la tabla). Sin match → delega a gallery_slug(tema,...) (FALLBACK, arriba).
#
# Normalización: ESPEJO de noticias_ingest/scraper.py:487-499 (_ACENTOS/_norm/_wb).
# NO se importa scraper: arrastra feedparser/requests/bs4 a nivel módulo y dashboard.py
# se mantiene STDLIB-ONLY (path de publish liviano). Réplica byte-equivalente; si
# scraper._norm cambia, sincronizar acá (es un fold de acentos estable). Word-boundary
# vía lookaround sobre [0-9a-z] → 'oro' NO matchea ahorro/tesoro; frases multipalabra
# ('tipo de cambio') matchean como frase. Nada de substring crudo.
_GAL_ACENTOS = str.maketrans("áàäéèëíìïóòöúùüñ", "aaaeeeiiiooouuun")


def _gal_norm(s):
    return re.sub(r"\s+", " ", (s or "").lower().translate(_GAL_ACENTOS)).strip()


def _gal_wb(term):
    return re.compile(r"(?<![0-9a-z])" + re.escape(_gal_norm(term)) + r"(?![0-9a-z])")


# TABLA DE PRIORIDAD: LISTA ORDENADA de reglas (keywords, slug). Orden = prioridad
# (1ª regla con match gana ante co-ocurrencia). Un MISMO slug PUEDE repetirse en varias
# reglas — así una ENTIDAD nombrada tiene prioridad propia compartiendo imagen con un
# tema general. Editable por criterio humano (orden/keywords/proxies). Targets = SOLO
# las 14 imágenes existentes (guarda abajo). Keywords ya plegadas (sin acentos); _gal_wb
# las re-normaliza igual. Plurales se listan aparte (límite de palabra: 'eleccion' NO
# matchea 'elecciones'). Frases multipalabra ('banco central') matchean como frase.
#
# Reglas [ENT] = ENTIDAD nombrada con prioridad propia. fmi y banco-central (banda de
# arriba) y gobierno (más abajo, sobre las generales) ya tienen IMAGEN DEDICADA
# (gal-fmi / gal-banco-central / gal-gobierno, este PR). Las [ENT] aún marcadas PROXY
# (multilaterales, asfi) apuntan a una imagen prestada hasta tener la suya: al crear su
# dedicada, cambiar SOLO el slug, NO la posición.
GALLERY_KEYWORD_PRIORITY = [
    (['eleccion', 'elecciones', 'electoral', 'comicios', 'votacion', 'candidato', 'tse'], 'elecciones'),
    (['bloqueo', 'paro', 'conflicto', 'protesta', 'movilizacion'], 'bloqueos'),  # 'marcha' quitado (polisémico: 'marcha de la economia'/'marcha atras')
    (['fmi', 'fondo monetario'], 'fmi'),                 # [ENT] fmi → imagen dedicada (sede del FMI; dominio público)
    (['banco central', 'bcb'], 'banco-central'),         # [ENT] banco-central → imagen dedicada (edificio BCB, La Paz; CC)
    (['banco mundial', 'bid', 'caf'], 'deuda'),          # [ENT] multilaterales → proxy provisional 'deuda'
    (['asfi'], 'inversion'),                             # [ENT] asfi → proxy 'inversion' (PROXY FLOJO)
    (['combustible', 'combustibles', 'diesel', 'gasolina', 'ypfb', 'surtidor', 'carburante'], 'combustibles'),
    (['litio', 'ylb', 'salar'], 'litio'),
    (['deuda', 'bonos', 'eurobono', 'calificadora', 'default', 'financiamiento'], 'deuda'),
    (['exportacion', 'exportaciones', 'exportador', 'gas natural'], 'exportaciones'),  # 'divisas' movido a tipo-cambio (concepto cambiario)
    (['inflacion', 'ipc', 'precios', 'carestia'], 'inflacion'),
    (['alimento', 'alimentos', 'canasta', 'abastecimiento', 'harina', 'azucar', 'aceite'], 'alimentos'),
    (['agro', 'soya', 'agropecuario', 'cosecha'], 'agro'),
    (['inversion', 'credito', 'reservas internacionales', 'rin'], 'inversion'),
    (['dolar', 'tipo de cambio', 'paralelo', 'divisa', 'divisas', 'usdt', 'cotizacion'], 'tipo-cambio'),  # 'divisa(s)' unificado acá
    # [ENT] gobierno: entidad SOBRE las generales (economia/politica) pero DEBAJO de los temas
    # concretos de arriba → un tópico nombrado (diesel, litio, soya…) sigue ganando a 'gobierno'.
    # Mantiene 'ley'/'decreto'/'asamblea' suelta en la regla politica de abajo (no migran a la sede).
    (['gobierno', 'ministerio', 'ministro', 'casa grande del pueblo', 'asamblea legislativa', 'plaza murillo'], 'gobierno'),  # [ENT] gobierno → imagen dedicada (sede de gobierno; CC)
    (['pib', 'crecimiento', 'fiscal', 'deficit', 'subvencion'], 'economia'),
    # Poder legislativo = señal política: cubre notas "otros"/General que hoy caían a placeholder
    # (ej. "Brigadas Parlamentarias…"). Plurales/géneros listados aparte (límite de palabra:
    # 'parlamentario' NO matchea 'parlamentarias'). 'congreso' y 'orden' EXCLUIDOS (ambiguos).
    (['gobierno', 'ministro', 'asamblea', 'ley', 'decreto',
      'parlamentario', 'parlamentaria', 'parlamentarios', 'parlamentarias', 'brigadas parlamentarias',
      'diputado', 'diputada', 'diputados', 'diputadas',
      'senador', 'senadora', 'senadores', 'senadoras',
      'legislativo', 'legislativa', 'legislativos', 'legislativas'], 'politica'),
]

# Universo de slugs emisibles = las 17 imágenes existentes (14 base + fmi / banco-central /
# gobierno, entidades con foto dedicada de este PR). Ninguna regla puede emitir un slug
# fuera de acá (guarda fail-fast: rompe al cargar, no en runtime silencioso). Las [ENT] de
# multilaterales y asfi siguen proxyeando a slugs base → no introducen slugs nuevos.
VALID_GALLERY_SLUGS = frozenset(GALLERY_TEMA_SLUGS.values()) | {
    'economia', 'politica', 'internacional',   # genéricas por category / carril latam
    'fmi', 'banco-central', 'gobierno',         # entidades con imagen dedicada (este PR)
}
assert all(slug in VALID_GALLERY_SLUGS for _, slug in GALLERY_KEYWORD_PRIORITY), \
    "GALLERY_KEYWORD_PRIORITY emite un slug sin imagen en static/gal-<slug>.webp"

# Compilación una sola vez al cargar el módulo (no por nota): (patrones, slug).
_GALLERY_KW_COMPILED = [([_gal_wb(k) for k in kws], slug) for kws, slug in GALLERY_KEYWORD_PRIORITY]


def gallery_slug_v2(title, summary, detail, tema, category, carril):
    """Selección de slug v1.1. carril latam → 'internacional'. Si no, escanea
    title+summary+detail normalizado y recorre GALLERY_KEYWORD_PRIORITY en orden;
    la 1ª regla con match por límite de palabra gana (su slug). Sin match → fallback
    a gallery_slug(tema,...). Solo emite slugs de VALID_GALLERY_SLUGS."""
    if carril == 'latam':
        return 'internacional'
    texto = _gal_norm(' '.join(p for p in (title, summary, detail) if p))
    for pats, slug in _GALLERY_KW_COMPILED:
        if any(p.search(texto) for p in pats):
            return slug
    return gallery_slug(tema, category, carril)


# ── Galería v2: rotación con cooldown ────────────────────────────────────────
# Cada slug tiene un SET de imágenes (gal-<slug>-<k>.webp, k=1..N en static/) en
# vez de una sola foto fija. A cada nota se le asigna UNA imagen de su slug
# evitando repetir una usada en los últimos GALLERY_COOLDOWN_DAYS días — salvo que
# no haya alternativa (fallback round-robin LRU, "salvo que no haya más imágenes").
#
# Determinístico (no aleatorio) y STATELESS: una pasada greedy en orden de fecha
# ascendente sobre las notas mostradas. No persiste estado ni escribe el DB
# (dashboard.py sigue read-only). En CADA build el cooldown se respeta: ninguna
# imagen se repite dentro de los GALLERY_COOLDOWN_DAYS si hay alternativa.
# NO está fijada build-a-build: como el estado arranca vacío en cada corrida, la
# fase de rotación se ancla a la primera nota de la ventana de 30 días → cuando la
# ventana avanza (cron */12) una nota puede recibir OTRA imagen de su mismo set
# (cosmético: sigue siendo una foto correcta del tema; no afecta data ni pipeline).
# Fijar la imagen por nota requeriría estado persistido (ticket aparte). El
# inspector lo refleja solo (lee esto vivo).
GALLERY_COOLDOWN_DAYS = 3

# slug -> nº de imágenes gal-<slug>-1..N.webp presentes en static/. Fuente de verdad
# del set por slug. Un slug sin entrada (o N=0) → sin galleryImg → placeholder CSS.
GALLERY_SETS = {
    'agro': 3, 'alimentos': 2, 'banco-central': 3, 'bloqueos': 3,
    'combustibles': 4, 'deuda': 3, 'economia': 3,
    'exportaciones': 3, 'fmi': 2, 'gobierno': 3, 'inflacion': 1,
    'internacional': 3, 'inversion': 3, 'litio': 4, 'politica': 3,
    'tipo-cambio': 3,
}
assert set(GALLERY_SETS) <= VALID_GALLERY_SLUGS, \
    "GALLERY_SETS tiene un slug fuera de VALID_GALLERY_SLUGS"

# Estado de licencias por asset 'slug-k' -> (licencia, atrib_requerida). SOLO
# metadata/medición: NO cambia el render. Poblado a mano desde GALLERY-CREDITS.md
# (única fuente; el test de sync abajo asegura que ambas vistas no driftean).
# Sirve para (i) medir el % de atribución que arrastramos mientras acumulamos
# assets clean y (ii) habilitar el borrado en bloque en el switchover. Esperado:
# 41 con atrib / 5 clean (agro-2, agro-3, banco-central-3, combustibles-3, fmi-1).
GALLERY_LICENSES = {
    'agro-1': ('CC BY-SA 2.0', True),
    'agro-2': ('Public domain', False),
    'agro-3': ('Public domain', False),
    'alimentos-1': ('CC BY-SA 4.0', True),
    'alimentos-2': ('CC BY-SA 4.0', True),
    'banco-central-1': ('CC BY-SA 3.0', True),
    'banco-central-2': ('CC BY-SA 2.0', True),
    'banco-central-3': ('CC0', False),
    'bloqueos-1': ('CC BY-SA 4.0', True),
    'bloqueos-2': ('CC BY-SA 4.0', True),
    'bloqueos-3': ('CC BY-SA 4.0', True),
    'combustibles-1': ('CC BY-SA 4.0', True),
    'combustibles-2': ('CC BY-SA 4.0', True),
    'combustibles-3': ('CC0', False),
    'combustibles-4': ('CC BY-SA 3.0', True),
    'deuda-1': ('CC BY-SA 4.0', True),
    'deuda-2': ('CC BY-SA 3.0', True),
    'deuda-3': ('CC BY-SA 4.0', True),
    'economia-1': ('CC BY-SA 2.0', True),
    'economia-2': ('CC BY-SA 4.0', True),
    'economia-3': ('CC BY-SA 4.0', True),
    'exportaciones-1': ('CC BY-SA 4.0', True),
    'exportaciones-2': ('CC BY 4.0', True),
    'exportaciones-3': ('CC BY-SA 3.0', True),
    'fmi-1': ('Public domain', False),
    'fmi-2': ('CC BY 3.0', True),
    'gobierno-1': ('CC BY-SA 4.0', True),
    'gobierno-2': ('CC BY-SA 4.0', True),
    'gobierno-3': ('CC BY-SA 3.0', True),
    'inflacion-1': ('CC BY-SA 4.0', True),
    'internacional-1': ('CC BY-SA 3.0', True),
    'internacional-2': ('CC BY 2.0', True),
    'internacional-3': ('CC BY-SA 3.0', True),
    'inversion-1': ('CC BY-SA 2.0', True),
    'inversion-2': ('CC BY-SA 4.0', True),
    'inversion-3': ('CC BY-SA 4.0', True),
    'litio-1': ('CC BY-SA 4.0', True),
    'litio-2': ('CC BY-SA 4.0', True),
    'litio-3': ('CC BY-SA 4.0', True),
    'litio-4': ('CC BY-SA 4.0', True),
    'politica-1': ('CC BY-SA 4.0', True),
    'politica-2': ('CC BY 3.0', True),
    'politica-3': ('CC BY 2.0', True),
    'tipo-cambio-1': ('CC BY-SA 4.0', True),
    'tipo-cambio-2': ('CC BY-SA 4.0', True),
    'tipo-cambio-3': ('CC BY-SA 4.0', True),
}

# Set de assets que requieren atribución (los que se purgan en el switchover).
GALLERY_ATTRIB_REQUIRED = frozenset(k for k, (lic, req) in GALLERY_LICENSES.items() if req)

# Variantes (slug,k) que GALLERY_SETS implica realmente. Fail-fast: las keys de
# GALLERY_LICENSES deben cubrirlas EXACTAMENTE — un desajuste (foto agregada al
# set sin licencia, o licencia huérfana) rompe en carga del módulo, no en silencio.
_GALLERY_VARIANTS = frozenset(
    f'{slug}-{k}' for slug, n in GALLERY_SETS.items() for k in range(1, n + 1))
assert set(GALLERY_LICENSES) == _GALLERY_VARIANTS, \
    ("GALLERY_LICENSES no cubre exactamente las variantes de GALLERY_SETS; "
     f"faltan={sorted(_GALLERY_VARIANTS - set(GALLERY_LICENSES))} "
     f"sobran={sorted(set(GALLERY_LICENSES) - _GALLERY_VARIANTS)}")


def gallery_attrib_stats():
    """% de assets que requieren atribución (len-based), global y por slug.
    Mide cuánta atribución arrastramos mientras acumulamos clean. Devuelve
    (pct_global, {slug: pct}); pct en [0,100], slugs en orden de GALLERY_SETS."""
    total = len(GALLERY_LICENSES)
    pct_global = 100.0 * len(GALLERY_ATTRIB_REQUIRED) / total if total else 0.0
    por_slug = {}
    for slug, n in GALLERY_SETS.items():
        keys = [f'{slug}-{k}' for k in range(1, n + 1)]
        req = sum(1 for key in keys if key in GALLERY_ATTRIB_REQUIRED)
        por_slug[slug] = 100.0 * req / len(keys) if keys else 0.0
    return pct_global, por_slug


def _gal_parse_date(d):
    """'YYYY-MM-DD...' -> date; None si no parsea."""
    try:
        y, m, dd = (int(x) for x in str(d)[:10].split('-'))
        return date(y, m, dd)
    except Exception:
        return None


def assign_gallery_images(notas):
    """Asigna n['galleryImg'] ('slug-k' o None) a cada nota rotando con cooldown.
    Muta `notas` in-place. Cada nota debe traer 'gallerySlug', 'date' (y opcional
    'time'/'id' para orden estable). Algoritmo: por slug, elige la imagen menos
    recientemente usada (por secuencia de asignación) entre las que están FUERA del
    cooldown de fecha; si todas están dentro del cooldown, cae a la menos reciente
    igual (LRU). Procesa en orden de fecha ascendente para que el resultado sea
    determinístico y estable para las notas recientes."""
    cd = timedelta(days=GALLERY_COOLDOWN_DAYS)
    order = sorted(range(len(notas)), key=lambda i: (
        str(notas[i].get('date') or ''), str(notas[i].get('time') or ''),
        str(notas[i].get('id') or '')))
    last_date = {}   # (slug, k) -> date del último uso (para cooldown)
    last_seq = {}    # (slug, k) -> int (orden de asignación; mayor = más reciente)
    seq = 0
    for i in order:
        seq += 1
        n = notas[i]
        slug = n.get('gallerySlug')
        cnt = GALLERY_SETS.get(slug, 0)
        if not slug or cnt <= 0:
            n['galleryImg'] = None
            continue
        d = _gal_parse_date(n.get('date'))
        ks = range(1, cnt + 1)
        if d is not None:
            elig = [k for k in ks
                    if (slug, k) not in last_date or (d - last_date[(slug, k)]) >= cd]
        else:
            elig = list(ks)
        pool = elig if elig else list(ks)
        # menos recientemente usada: secuencia ascendente (nunca usada = -1 = la más
        # antigua), desempate por k → round-robin estable incluso dentro del cooldown.
        chosen = min(pool, key=lambda k: (last_seq.get((slug, k), -1), k))
        n['galleryImg'] = '%s-%d' % (slug, chosen)
        if d is not None:
            last_date[(slug, chosen)] = d
        last_seq[(slug, chosen)] = seq


def _laspeyres_contrib(idx_div: dict, idx_tot: dict, var12_tot: dict):
    """Recupera las ponderaciones fijas del índice total (Laspeyres base 2016)
    a partir de los índices de división que ya ingerimos, y deriva la
    contribución de cada división a la variación 12m del total:

        c_i(t) = w_i · (I_i(t) − I_i(t−12)) / I_T(t−12) · 100

    El INE no publica las ponderaciones en los cuadros que ingerimos, pero el
    total es combinación lineal EXACTA de las divisiones (verificado: error de
    reconstrucción 0.000 en IPC y 0.001 en IPP sobre toda la serie), así que
    los pesos se recuperan por mínimos cuadrados. Doble guarda fail-closed:
    si la reconstrucción del índice no es casi exacta, o la suma de
    contribuciones no replica la var_12m publicada (tolerancias abajo),
    devuelve (None, None) y el payload va sin contribuciones — el frontend
    degrada a la vista de líneas. Sin numpy: ecuaciones normales + eliminación
    gaussiana (sistema chico, n=12), dashboard.py se mantiene stdlib-only.

    idx_div: {slug: {periodo: indice}}, idx_tot/var12_tot: {periodo: valor}.
    Devuelve (pesos {slug: w}, contrib {slug: {periodo: pts}}).
    """
    slugs = sorted(idx_div)
    n = len(slugs)
    periodos = [p for p in sorted(idx_tot)
                if all(p in idx_div[s] for s in slugs)]
    if n == 0 or len(periodos) < n + 12:
        return None, None
    rows = [[idx_div[s][p] for s in slugs] for p in periodos]
    y = [idx_tot[p] for p in periodos]
    # Matriz aumentada de ecuaciones normales (XᵀX | Xᵀy), Gauss-Jordan con
    # pivoteo parcial.
    aug = [[sum(r[i] * r[j] for r in rows) for j in range(n)]
           + [sum(r[i] * yk for r, yk in zip(rows, y))] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-9:
            return None, None
        aug[col], aug[piv] = aug[piv], aug[col]
        for r in range(n):
            if r != col and aug[r][col]:
                factor = aug[r][col] / aug[col][col]
                aug[r] = [a - factor * b for a, b in zip(aug[r], aug[col])]
    pesos = {s: aug[i][n] / aug[i][i] for i, s in enumerate(slugs)}
    # Guarda 1: pesos sanos + reconstrucción casi exacta del índice total.
    recon_err = max(abs(sum(pesos[s] * idx_div[s][p] for s in slugs) - idx_tot[p])
                    for p in periodos)
    if (recon_err > 0.02 or abs(sum(pesos.values()) - 1) > 0.001
            or min(pesos.values()) <= 0):
        return None, None
    contrib = {s: {} for s in slugs}
    diffs = []
    for p in periodos:
        p12 = f"{int(p[:4]) - 1}-{p[5:]}"
        if p12 not in idx_tot or any(p12 not in idx_div[s] for s in slugs):
            continue
        base = idx_tot[p12]
        total = 0.0
        for s in slugs:
            c = pesos[s] * (idx_div[s][p] - idx_div[s][p12]) / base * 100
            contrib[s][p] = c
            total += c
        if p in var12_tot:
            diffs.append(abs(total - var12_tot[p]))
    # Guarda 2: la suma de contribuciones replica la var 12m publicada.
    if not diffs or max(diffs) > 0.05:
        return None, None
    return pesos, contrib


def load_bcb_ref(first_date: str | None = None) -> dict:
    """Lee bcb_referencial.json (array de {fecha,compra,venta}). Soporta formato
    viejo (dict) como fallback. Devuelve dict con latest + history.

    first_date (YYYY-MM-DD): si se pasa, filtra el histórico para que solo incluya
    entradas con fecha >= first_date. La última entrada siempre se conserva para
    el KPI aunque esté fuera de rango."""
    out = {'bcb_ref_compra': None, 'bcb_ref_venta': None,
           'bcb_ref_fecha': None, 'bcb_ref_history': []}
    try:
        if BCB_REF_FILE.exists():
            data = json.loads(BCB_REF_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('fecha_publicacion'):
                # Formato viejo
                data = [{'fecha': data['fecha_publicacion'],
                         'compra': data.get('compra'),
                         'venta': data.get('venta')}]
            if isinstance(data, list) and data:
                full_hist = sorted(
                    [h for h in data if h.get('fecha')],
                    key=lambda h: h['fecha'])
                latest = full_hist[-1]
                out['bcb_ref_compra'] = latest.get('compra')
                out['bcb_ref_venta'] = latest.get('venta')
                out['bcb_ref_fecha'] = latest.get('fecha')
                # Filtrar para el gráfico (serie temporal dentro del rango de snapshots)
                if first_date:
                    out['bcb_ref_history'] = [h for h in full_hist if h['fecha'] >= first_date]
                else:
                    out['bcb_ref_history'] = full_hist
    except Exception:
        pass
    return out


def _fill_weekends_tco(pub: list[dict]) -> list[dict]:
    """Rellena sábados y domingos con el TCO VIGENTE del viernes (backward-fill).

    Regla operativa (confirmada por Diego 2026-07-20): el valor que el BCB publica
    un jueves 20:00 (fechado por su vigencia = viernes) rige viernes, sábado y
    domingo; el que publica el viernes (vigencia = lunes) recién rige el lunes. Por
    eso el finde arrastra el valor del ÚLTIMO día hábil publicado ANTERIOR (= el
    viernes), NO el del próximo. Consecuencia: el delta día del finde queda PLANO y
    el salto aparece el lunes, uniforme en las 3+ superficies (KPI, gráfico, ticker
    "día en cifras", tarjeta /boletin-4k9x/). NO es interpolación silenciosa: el
    valor del finde es el del último día hábil vigente. Las entradas sintéticas
    llevan `source='bcb_tco_fin_semana'` y NO pisan valores publicados.

    `pub` viene ordenado por fecha, con `tco` no nulo. Un finde SIN día hábil
    publicado anterior (ej. el finde previo al primer publicado) queda como hueco
    visible: no se inventa un valor. Feriados: un lunes feriado (sin publicación)
    hereda el valor del viernes vía el mismo 'último ≤ fecha' que usan los
    consumidores (tcoOnOrBefore / _close_on_or_before)."""
    if not pub:
        return pub
    have = {h['fecha'] for h in pub}
    pub_days = [(datetime.fromisoformat(h['fecha']).date(), h['tco']) for h in pub]
    first, last = pub_days[0][0], pub_days[-1][0]
    extra = []
    d, one = first, timedelta(days=1)
    while d <= last:
        if d.weekday() >= 5 and d.isoformat() not in have:  # 5=sábado, 6=domingo
            prev = None  # valor del último día hábil publicado ANTERIOR (= viernes)
            for (pd, val) in pub_days:
                if pd < d:
                    prev = val
                else:
                    break
            if prev is not None:
                extra.append({'fecha': d.isoformat(), 'tco': prev, 'source': 'bcb_tco_fin_semana'})
        d += one
    return sorted(pub + extra, key=lambda h: h['fecha'])


def load_bcb_tco(first_date: str | None = None) -> dict:
    """Lee bcb_tco.json (array de {fecha, tco}, generado por ingest_bcb_tco.py).
    Devuelve el último TCO (para la KPI Prima P2P) + el histórico filtrado al
    rango del gráfico. Fail-soft idéntico a load_bcb_ref: si falta el archivo o
    está vacío, devuelve None/[] y el frontend cae al fijo 6.96.

    first_date (YYYY-MM-DD): filtra el histórico para el gráfico; el último valor
    se conserva siempre (bcb_tco_last) para la KPI aunque caiga fuera de rango.

    Emite además `bcb_tco_stale` (+ `bcb_tco_today_bo`) para la alerta admin del
    frontend: el TCO se fecha por su VIGENCIA (próximo día hábil), que para un
    histórico fresco es SIEMPRE >= hoy BO (RD 88/2026, incl. regla de fin de
    semana). Si la última vigencia publicada quedó ANTES de hoy BO, el ingest dejó
    de actualizar el histórico → alerta."""
    today_bo = (datetime.now(timezone.utc) - timedelta(hours=4)).date().isoformat()
    out = {'bcb_tco_last': None, 'bcb_tco_fecha': None, 'bcb_tco_history': [],
           'bcb_tco_today_bo': today_bo, 'bcb_tco_stale': False}
    try:
        if BCB_TCO_FILE.exists():
            data = json.loads(BCB_TCO_FILE.read_text(encoding='utf-8'))
            if isinstance(data, list) and data:
                full_hist = sorted(
                    [h for h in data if h.get('fecha') and h.get('tco') is not None],
                    key=lambda h: h['fecha'])
                if full_hist:
                    latest = full_hist[-1]  # último PUBLICADO (no sintético) para la KPI
                    out['bcb_tco_last'] = latest.get('tco')
                    out['bcb_tco_fecha'] = latest.get('fecha')
                    # Rellena sáb/dom con el valor del próximo día hábil (regla RD 88/2026)
                    filled = _fill_weekends_tco(full_hist)
                    if first_date:
                        out['bcb_tco_history'] = [h for h in filled if h['fecha'] >= first_date]
                    else:
                        out['bcb_tco_history'] = filled
    except Exception:
        pass
    # Última vigencia publicada < hoy BO → el histórico no se está actualizando.
    out['bcb_tco_stale'] = bool(out['bcb_tco_fecha'] and out['bcb_tco_fecha'] < today_bo)
    return out


def load_bcb_tre() -> dict:
    """Lee bcb_tre.json (serie mensual de la TRE por vigencia, generado por
    ingest_bcb_tre.py). Fail-soft: sin archivo o corrupto → history vacío y el
    frontend muestra 'Sin datos de TRE'."""
    out = {'history': []}
    try:
        if BCB_TRE_JSON.exists():
            data = json.loads(BCB_TRE_JSON.read_text(encoding='utf-8'))
            if isinstance(data, list):
                out['history'] = sorted(
                    [h for h in data if h.get('vigencia') and h.get('mn') is not None],
                    key=lambda h: h['vigencia'])
    except Exception:
        pass
    return out


def load_bloqueos():
    """Lee bloqueos.json (generado por ingest_bloqueos.py desde el dataset abierto
    de @mauforonda, que archiva el registro de incidentes de la ABC). Devuelve el
    dict o None si no existe / falla (fail-soft, igual que load_bcb_ref)."""
    try:
        f = Path(__file__).parent / 'bloqueos.json'
        if f.exists():
            return json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        pass
    return None

# ── Cálculo de VWAP ────────────────────────────────────────────────────────

def vwap_by_depth(prices_and_sizes, pct):
    """prices_and_sizes: lista de (price, surplus) ya ordenada por 'mejor' primero."""
    if not prices_and_sizes:
        return None
    total = sum(s for _, s in prices_and_sizes)
    if total == 0:
        return None
    budget = total * pct
    acc = wp = 0.0
    for price, size in prices_and_sizes:
        take = min(size, budget - acc)
        if take <= 0:
            break
        wp += price * take
        acc += take
    return round(wp / acc, 6) if acc > 0 else None


# ── Procesamiento ──────────────────────────────────────────────────────────

def process_data(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Filtro de calidad: las queries de precio/profundidad/métricas leen ads_verified
    # (is_merchant=1 = MASS + BLOCK, excluye usuarios regulares). La detección de
    # cobertura (existencia de snapshots, abajo) sigue sobre `ads` crudo para no
    # confundir un snapshot sin merchants con un hueco real.
    conn.execute("CREATE TEMP VIEW ads_verified AS SELECT * FROM ads WHERE is_merchant=1")
    timestamps = [r[0] for r in conn.execute(
        "SELECT DISTINCT snapshot_ts_utc FROM ads WHERE snapshot_ts_utc >= '2026-05-08 00:00:00' ORDER BY snapshot_ts_utc"
    ).fetchall()]
    ts_data = []
    for ts in timestamps:
        rows = conn.execute(
            "SELECT side, price, surplus_usdt, advertiser_id FROM ads_verified WHERE snapshot_ts_utc=?",
            (ts,)).fetchall()
        buy_raw = [(r['price'], r['surplus_usdt'], r['advertiser_id']) for r in rows if r['side'] == 'BUY']
        sell_raw = [(r['price'], r['surplus_usdt'], r['advertiser_id']) for r in rows if r['side'] == 'SELL']
        buy_sorted = sorted(buy_raw, key=lambda x: x[0])
        sell_sorted = sorted(sell_raw, key=lambda x: -x[0])
        buy_ps = [(p, s) for p, s, _ in buy_sorted]
        sell_ps = [(p, s) for p, s, _ in sell_sorted]
        buy_depth = sum(s for _, s in buy_ps)
        sell_depth = sum(s for _, s in sell_ps)
        d = {
            'ts': ts, 'buy_count': len(buy_raw), 'sell_count': len(sell_raw),
            'buy_depth': round(buy_depth), 'sell_depth': round(sell_depth),
            'depth_ratio': round(sell_depth / buy_depth, 2) if buy_depth > 0 else None,
        }
        for pl, pv in [('5', 0.05), ('10', 0.10), ('25', 0.25), ('50', 0.50)]:
            vb = vwap_by_depth(buy_ps, pv)
            vs = vwap_by_depth(sell_ps, pv)
            d[f'vb{pl}'] = vb
            d[f'vs{pl}'] = vs
            d[f'sp{pl}'] = round(vb - vs, 4) if (vb and vs) else None
        for side_name, side_data, depth in [('buy', buy_raw, buy_depth), ('sell', sell_raw, sell_depth)]:
            merchants = {}
            for _, surplus, adv_id in side_data:
                merchants[adv_id] = merchants.get(adv_id, 0) + surplus
            top5 = sum(sorted(merchants.values(), reverse=True)[:5])
            d[f't5{side_name}'] = round(top5 / depth * 100, 1) if depth > 0 else 0
        ts_data.append(d)
    def _group_last(data, key_fn):
        groups = {}
        for d in data:
            groups[key_fn(d['ts'])] = d
        return list(groups.values())
    hourly = _group_last(ts_data, lambda ts: ts[:13])
    daily = _group_last(ts_data, lambda ts: ts[:10])
    last_ts = timestamps[-1]
    bank_rows = conn.execute("SELECT banks, surplus_usdt FROM ads_verified WHERE snapshot_ts_utc=?", (last_ts,)).fetchall()
    bank_stats = {}
    total_depth_last = 0
    for r in bank_rows:
        banks = json.loads(r['banks']) if r['banks'] else []
        total_depth_last += r['surplus_usdt']
        for b in banks:
            if b == 'BANK': continue
            if b not in bank_stats: bank_stats[b] = {'count': 0, 'depth': 0}
            bank_stats[b]['count'] += 1
            bank_stats[b]['depth'] += r['surplus_usdt']
    bank_list = [
        {'name': BANK_CANONICAL.get(b, b), 'count': s['count'],
         'depth': round(s['depth']),
         'depth_pct': round(s['depth'] / total_depth_last * 100, 4)}
        for b, s in sorted(bank_stats.items(), key=lambda x: -x[1]['depth'])
    ]

    # ── Panel 1: Top merchants (last snapshot of each view) ──
    view_last_ts = set()
    if ts_data:    view_last_ts.add(ts_data[-1]['ts'])
    if hourly:     view_last_ts.add(hourly[-1]['ts'])
    if daily:      view_last_ts.add(daily[-1]['ts'])
    top_merchants = {}
    for view_ts in view_last_ts:
        rows = conn.execute("""
            SELECT side, advertiser_nick, advertiser_id, price, surplus_usdt,
                   n_banks, month_order_count
            FROM ads_verified WHERE snapshot_ts_utc=?
        """, (view_ts,)).fetchall()
        agg = {}
        for r in rows:
            key = (r['side'], r['advertiser_id'])
            if key not in agg:
                agg[key] = {'nick': r['advertiser_nick'] or '(sin nick)',
                            'depth': 0, 'price_w': 0,
                            'n_banks': r['n_banks'] or 0,
                            'month_order_count': r['month_order_count'] or 0}
            agg[key]['depth'] += r['surplus_usdt'] or 0
            agg[key]['price_w'] += (r['price'] or 0) * (r['surplus_usdt'] or 0)
        totals = {'BUY': 0, 'SELL': 0}
        for (side, _), v in agg.items():
            totals[side] += v['depth']
        result = {'BUY': [], 'SELL': []}
        for side in ('BUY', 'SELL'):
            entries = sorted(
                [v for (s, _), v in agg.items() if s == side],
                key=lambda e: -e['depth']
            )[:10]
            total = totals[side] or 1
            result[side] = [{
                'nick': e['nick'],
                'depth': round(e['depth']),
                'pct': round(e['depth'] / total * 100, 1),
                'vwap': round(e['price_w'] / e['depth'], 4) if e['depth'] > 0 else None,
                'n_banks': e['n_banks'],
                'month_order_count': e['month_order_count'],
            } for e in entries]
        top_merchants[view_ts] = result

    # ── Panel 2: Merchants activos / flow ──
    all_ts_list = [d['ts'] for d in ts_data]
    ids_by_ts = defaultdict(lambda: {'BUY': set(), 'SELL': set()})
    if all_ts_list:
        rows = conn.execute(
            "SELECT snapshot_ts_utc, side, advertiser_id FROM ads_verified WHERE snapshot_ts_utc >= '2026-05-08 00:00:00'"
        ).fetchall()
        for r in rows:
            ids_by_ts[r['snapshot_ts_utc']][r['side']].add(r['advertiser_id'])

    def compute_flow(ts_list):
        out = []
        prev = None
        for ts in ts_list:
            cur = ids_by_ts.get(ts, {'BUY': set(), 'SELL': set()})
            entry = {'ts': ts, 'n_buy': len(cur['BUY']), 'n_sell': len(cur['SELL'])}
            if prev is None:
                entry.update({'new_buy': 0, 'gone_buy': 0, 'new_sell': 0, 'gone_sell': 0})
            else:
                entry.update({
                    'new_buy':  len(cur['BUY']  - prev['BUY']),
                    'gone_buy': len(prev['BUY'] - cur['BUY']),
                    'new_sell':  len(cur['SELL']  - prev['SELL']),
                    'gone_sell': len(prev['SELL'] - cur['SELL']),
                })
            out.append(entry)
            prev = cur
        return out

    merchant_flow = {
        'all':    compute_flow(all_ts_list),
        'hourly': compute_flow([d['ts'] for d in hourly]),
        'daily':  compute_flow([d['ts'] for d in daily]),
    }

    # ── Panel 4: Heatmap por hora del día (Bolivia UTC-4) ──
    bolivia = timezone(timedelta(hours=-4))
    metrics_def = [
        ('buy_depth',  'Profundidad Compra'),
        ('sell_depth', 'Profundidad Venta'),
        ('sp10',       'Spread 10%'),
        ('n_ads',      'Anuncios verificados'),
        ('vb10',       'VWAP 10% Compra'),
        ('vs10',       'VWAP 10% Venta'),
    ]
    hm_sums = {k: [[0, 0] for _ in range(24)] for k, _ in metrics_def}
    for d in ts_data:
        try:
            dt = datetime.fromisoformat(d['ts'].replace('Z', '+00:00')).astimezone(bolivia)
            h = dt.hour
        except Exception:
            continue
        for key, _ in metrics_def:
            val = (d['buy_count'] + d['sell_count']) if key == 'n_ads' else d.get(key)
            if val is None:
                continue
            hm_sums[key][h][0] += val
            hm_sums[key][h][1] += 1
    heatmap_data = {
        'hours': list(range(24)),
        'metrics': [
            {'key': key, 'label': label, 'values': [
                round(hm_sums[key][h][0] / hm_sums[key][h][1], 4)
                if hm_sums[key][h][1] > 0 else None
                for h in range(24)
            ]}
            for key, label in metrics_def
        ]
    }

    # ── Huecos de snapshots (>20 min entre consecutivos) ──
    gaps = []
    gap_threshold_s = 20 * 60
    for i in range(1, len(timestamps)):
        try:
            t0 = datetime.fromisoformat(timestamps[i-1].replace('Z', '+00:00'))
            t1 = datetime.fromisoformat(timestamps[i].replace('Z', '+00:00'))
        except Exception:
            continue
        diff_s = (t1 - t0).total_seconds()
        if diff_s > gap_threshold_s:
            gaps.append({
                'start': timestamps[i-1],
                'end':   timestamps[i],
                'minutes': round(diff_s / 60),
            })

    # ── SCHEMA NUEVO (columnar, capa de compatibilidad — eliminar en commit 17) ──
    # Construido en paralelo al schema viejo para que los renderers JS migren
    # uno por uno en commits 13–16. Ningún cambio visible al usuario hasta
    # que JS comience a leer de los nuevos campos.

    # ts_metrics: arrays paralelos por métrica (~30 KB).
    ts_metrics = {'ts': [d['ts'] for d in ts_data]}
    for k in ('vb5', 'vb10', 'vb25', 'vb50',
              'vs5', 'vs10', 'vs25', 'vs50',
              'sp5', 'sp10', 'sp25', 'sp50',
              'buy_depth', 'sell_depth', 'buy_count', 'sell_count',
              'depth_ratio', 't5buy', 't5sell'):
        ts_metrics[k] = [d.get(k) for d in ts_data]

    last_ts_str = timestamps[-1]
    # merchants_last incluye TODOS los merchants del último snapshot (no top
    # 10) para alimentar tanto rMerchants (top por depth, slice cliente) como
    # rOutliers (todos, filtrado por threshold). Re-agrega aquí en lugar de
    # heredar el slice de top_merchants[last_ts_str].
    ml_rows = conn.execute("""
        SELECT side, advertiser_nick, advertiser_id, price, surplus_usdt,
               n_banks, month_order_count
        FROM ads_verified WHERE snapshot_ts_utc=?
    """, (last_ts_str,)).fetchall()
    ml_agg = {}
    for r in ml_rows:
        key = (r['side'], r['advertiser_id'])
        if key not in ml_agg:
            ml_agg[key] = {'nick': r['advertiser_nick'] or '(sin nick)',
                           'depth': 0.0, 'price_w': 0.0,
                           'n_banks': r['n_banks'] or 0,
                           'month_order_count': r['month_order_count'] or 0}
        ml_agg[key]['depth']   += r['surplus_usdt'] or 0
        ml_agg[key]['price_w'] += (r['price'] or 0) * (r['surplus_usdt'] or 0)
    ml_totals = {'BUY': 0.0, 'SELL': 0.0}
    for (side, _), v in ml_agg.items():
        ml_totals[side] += v['depth']
    ml_full = {'BUY': [], 'SELL': []}
    for side in ('BUY', 'SELL'):
        entries = sorted([v for (s, _), v in ml_agg.items() if s == side],
                         key=lambda e: -e['depth'])
        total = ml_totals[side] or 1
        ml_full[side] = [{
            'nick': e['nick'],
            'depth': round(e['depth']),
            'pct': round(e['depth'] / total * 100, 2),
            'vwap': round(e['price_w'] / e['depth'], 4) if e['depth'] > 0 else None,
            'n_banks': e['n_banks'],
            'month_order_count': e['month_order_count'],
        } for e in entries]
    merchants_last = {
        'snapshot_ts': last_ts_str,
        'vwap10_buy':  ts_data[-1].get('vb10'),
        'vwap10_sell': ts_data[-1].get('vs10'),
        'BUY':  ml_full['BUY'],
        'SELL': ml_full['SELL'],
    }

    # banks_daily: nueva pasada por día (último snapshot de cada día).
    banks_daily = []
    for d in daily:
        ts = d['ts']
        rows_b = conn.execute(
            "SELECT banks, surplus_usdt FROM ads_verified WHERE snapshot_ts_utc=?",
            (ts,)).fetchall()
        bs = {}
        total = 0.0
        for r in rows_b:
            bks = json.loads(r['banks']) if r['banks'] else []
            total += r['surplus_usdt'] or 0
            for b in bks:
                if b == 'BANK':
                    continue
                if b not in bs:
                    bs[b] = {'count': 0, 'depth': 0.0}
                bs[b]['count'] += 1
                bs[b]['depth'] += r['surplus_usdt'] or 0
        items = [{'name': BANK_CANONICAL.get(b, b),
                  'count': v['count'],
                  'depth': round(v['depth'])}
                 for b, v in sorted(bs.items(), key=lambda x: -x[1]['depth'])]
        banks_daily.append({
            'date': ts[:10],
            'snapshot_ts': ts,
            'total_depth': round(total),
            'items': items,
        })

    # offer_daily: ads crudos del último snapshot de cada día, columnar.
    aids_table = {}      # advertiser_id -> índice incremental
    od_dates, od_snaps = [], []
    od_offsets = [0]
    od_side, od_price, od_surplus, od_aid_idx = [], [], [], []
    od_vwap10_buy, od_vwap10_sell = [], []

    def _aid_idx(aid):
        if aid not in aids_table:
            aids_table[aid] = len(aids_table)
        return aids_table[aid]

    for d in daily:
        ts = d['ts']
        rows_o = conn.execute(
            "SELECT side, price, surplus_usdt, advertiser_id FROM ads_verified WHERE snapshot_ts_utc=?",
            (ts,)).fetchall()
        buy_ps  = sorted([(r['price'], r['surplus_usdt']) for r in rows_o
                          if r['side'] == 'BUY' and r['price'] and r['surplus_usdt']],
                         key=lambda x: x[0])
        sell_ps = sorted([(r['price'], r['surplus_usdt']) for r in rows_o
                          if r['side'] == 'SELL' and r['price'] and r['surplus_usdt']],
                         key=lambda x: -x[0])
        od_vwap10_buy.append(vwap_by_depth(buy_ps, 0.10))
        od_vwap10_sell.append(vwap_by_depth(sell_ps, 0.10))
        for r in rows_o:
            if r['price'] is None or r['surplus_usdt'] is None:
                continue
            od_side.append(0 if r['side'] == 'BUY' else 1)
            od_price.append(round(r['price'], 4))
            od_surplus.append(round(r['surplus_usdt'], 2))
            od_aid_idx.append(_aid_idx(r['advertiser_id']))
        od_offsets.append(len(od_side))
        od_dates.append(ts[:10])
        od_snaps.append(ts)

    offer_daily = {
        'dates': od_dates,
        'snapshot_ts': od_snaps,
        'row_offsets': od_offsets,
        'side': od_side,
        'price': od_price,
        'surplus': od_surplus,
        'aid_idx': od_aid_idx,
        'vwap10_buy': od_vwap10_buy,
        'vwap10_sell': od_vwap10_sell,
    }
    aids_list = sorted(aids_table.keys(), key=lambda a: aids_table[a])

    # flow_per_snapshot: aplanar merchant_flow['all'] columnar.
    fps_src = merchant_flow.get('all', [])
    flow_per_snapshot = {
        'ts':        [f['ts']        for f in fps_src],
        'n_buy':     [f['n_buy']     for f in fps_src],
        'n_sell':    [f['n_sell']    for f in fps_src],
        'new_buy':   [f.get('new_buy', 0)   for f in fps_src],
        'gone_buy':  [f.get('gone_buy', 0)  for f in fps_src],
        'new_sell':  [f.get('new_sell', 0)  for f in fps_src],
        'gone_sell': [f.get('gone_sell', 0) for f in fps_src],
    }

    # ── Order book: individual ads from last snapshot for depth chart ──
    ob_rows = conn.execute(
        "SELECT side, price, surplus_usdt FROM ads_verified WHERE snapshot_ts_utc=? AND price IS NOT NULL AND surplus_usdt IS NOT NULL",
        (last_ts_str,)).fetchall()
    order_book = {
        'buy': [{'p': round(r['price'], 2), 'a': round(r['surplus_usdt'], 2)} for r in ob_rows if r['side'] == 'BUY'],
        'sell': [{'p': round(r['price'], 2), 'a': round(r['surplus_usdt'], 2)} for r in ob_rows if r['side'] == 'SELL'],
    }

    # ── Activity heatmap: volume by (day_of_week, hour) in Bolivia time (UTC-4) ──
    activity_hm_rows = conn.execute("""
        SELECT
            CAST(strftime('%w', snapshot_ts_utc, '-4 hours') AS INTEGER) AS dow,
            CAST(strftime('%H', snapshot_ts_utc, '-4 hours') AS INTEGER) AS hour,
            SUM(surplus_usdt) AS total_amount
        FROM ads_verified
        WHERE snapshot_ts_utc >= '2026-05-08 00:00:00'
        GROUP BY dow, hour
    """).fetchall()
    # Build 7x24 matrix. SQLite %w: 0=Sun,1=Mon...6=Sat → reorder to Mon-Sun
    activity_matrix = [[0]*24 for _ in range(7)]
    for row in activity_hm_rows:
        dow_sqlite = row['dow']  # 0=Sun
        hour = row['hour']
        dow_mon = (dow_sqlite - 1) % 7  # Sun(0)→6, Mon(1)→0, Tue(2)→1, etc.
        activity_matrix[dow_mon][hour] = round(row['total_amount'])

    # ── DPF rates (from bcb_dpf_rates table, if exists) ──
    dpf_data = {'report_date': None, 'rates': []}
    try:
        latest_dpf_row = conn.execute("SELECT MAX(report_date) FROM bcb_dpf_rates").fetchone()
        latest_dpf_date = latest_dpf_row[0] if latest_dpf_row else None
        if latest_dpf_date:
            dpf_rows = conn.execute("""
                SELECT entidad, moneda, producto, plazo, tasa, categoria
                FROM bcb_dpf_rates WHERE report_date = ?
                ORDER BY categoria, entidad, moneda, producto, plazo
            """, (latest_dpf_date,)).fetchall()
            dpf_data = {
                'report_date': latest_dpf_date,
                'rates': [{'entidad': r['entidad'], 'moneda': r['moneda'],
                           'producto': r['producto'], 'plazo': r['plazo'],
                           'tasa': r['tasa'], 'categoria': r['categoria']}
                          for r in dpf_rows]
            }
    except Exception:
        pass  # Table doesn't exist yet — graceful degradation

    # ── EMBI spreads (from embi_spreads table, if exists) ──
    # Schema columnar: fechas + paises + series[pais] alineadas por índice.
    # None donde el país no tiene observación esa fecha (pre-debut o feriado).
    embi_data = {'fecha_actualizado': None, 'paises': [],
                 'fechas': [], 'series': {}}
    try:
        # Embebe todo el histórico (2007→). El payload completo agrega ~880 KB
        # al index.html (vs ~239 KB del trimming a 5 años). Tradeoff aceptado:
        # el toggle "Max" del frontend lo necesita; el resto de rangos clip
        # client-side.
        embi_rows = conn.execute(
            "SELECT fecha, pais, spread_bps FROM embi_spreads "
            "ORDER BY fecha, pais"
        ).fetchall()
        if embi_rows:
            fechas = sorted({r['fecha'] for r in embi_rows})
            paises = sorted({r['pais'] for r in embi_rows})
            fecha_idx = {f: i for i, f in enumerate(fechas)}
            series = {p: [None] * len(fechas) for p in paises}
            for r in embi_rows:
                series[r['pais']][fecha_idx[r['fecha']]] = r['spread_bps']
            embi_data = {
                'fecha_actualizado': fechas[-1],
                'paises': paises,
                'fechas': fechas,
                'series': series,
            }
    except Exception:
        pass  # Table doesn't exist yet — graceful degradation

    # ── Inflación INE (from ine_ipc / ine_ipp tables, if exist) ──
    # Shape columnar estilo EMBI: `periodos` + series alineadas por índice,
    # None donde falta la observación. Indicadores tal cual vienen del INE
    # (pivot, no recálculo). `valor IS NOT NULL` siempre: el parser INE
    # persiste filas placeholder para los meses futuros del año en curso.
    # El slug 'total' de los cuadros desagregados replica el agregado
    # nacional (verificado idéntico en data real) — se omite del payload;
    # el frontend usa `general` donde necesita el total.
    def _inflacion_familia(table: str, cuadro_nacional: str,
                           cuadro_desglose: str, labels: dict,
                           overlay: dict | None = None) -> dict | None:
        metricas_nac = ('var_12m', 'var_mensual', 'var_acumulada')
        metricas_des = ('var_12m', 'var_mensual')
        nac_rows = conn.execute(
            f"SELECT periodo, indicador, valor FROM {table} "
            f"WHERE cuadro = ? AND valor IS NOT NULL",
            (cuadro_nacional,)).fetchall()
        des_rows = conn.execute(
            f"SELECT periodo, indicador, valor FROM {table} "
            f"WHERE cuadro = ? AND valor IS NOT NULL",
            (cuadro_desglose,)).fetchall()
        # Split por prefijo en Python (LIKE con '_' es wildcard en SQL).
        # Los índices por división + total y la var_12m del total alimentan
        # el cálculo de contribuciones (no viajan crudos en el payload).
        nac = [(r['periodo'], r['indicador'], r['valor']) for r in nac_rows
               if r['indicador'] in metricas_nac]
        des = []
        idx_div, idx_tot, var12_tot = {}, {}, {}
        for r in des_rows:
            ind, p, val = r['indicador'], r['periodo'], r['valor']
            if ind.startswith('indice_'):
                slug = ind[len('indice_'):]
                if slug == 'total':
                    idx_tot[p] = val
                else:
                    idx_div.setdefault(slug, {})[p] = val
                continue
            if ind == 'var_12m_total':
                var12_tot[p] = val
            for m in metricas_des:
                if ind.startswith(m + '_'):
                    slug = ind[len(m) + 1:]
                    if slug != 'total':
                        des.append((p, m, slug, val))
                    break
        # Overlay PROVISIONAL (comunicado de prensa del INE): rellena SOLO los
        # periodos que el Excel (nac) aún no tiene. El Excel manda — cuando llega
        # su cuadro, ese periodo deja de estar en el overlay y pisa al provisional.
        prov_periodos = set()
        if overlay:
            excel_periodos = {p for p, _, _ in nac}
            for per, vals in overlay.items():
                if per in excel_periodos:
                    continue
                for ind in ('var_12m', 'var_mensual', 'var_acumulada'):
                    v = vals.get(ind)
                    if v is not None:
                        nac.append((per, ind, v))
                        prov_periodos.add(per)
        if not nac:
            return None
        periodos = sorted({p for p, _, _ in nac} | {p for p, _, _, _ in des})
        p_idx = {p: i for i, p in enumerate(periodos)}
        general = {m: [None] * len(periodos) for m in metricas_nac}
        for p, ind, val in nac:
            general[ind][p_idx[p]] = round(val, 4)
        # Slugs en orden canónico del mapa de labels; los desconocidos (cambios
        # futuros del INE) se anexan al final con label derivado, no se dropean.
        slugs_data = {s for _, _, s, _ in des}
        slugs = [s for s in labels if s in slugs_data] \
            + sorted(slugs_data - set(labels))
        desglose = {
            s: {'label': labels.get(s, s.replace('_', ' ').capitalize()),
                **{m: [None] * len(periodos) for m in metricas_des}}
            for s in slugs
        }
        for p, m, s, val in des:
            desglose[s][m][p_idx[p]] = round(val, 4)
        # Contribuciones a la var 12m del total (vista apilada del frontend).
        # All-or-nothing: solo se adjuntan si TODOS los slugs del desglose las
        # tienen — una suma parcial de barras apiladas sería engañosa.
        pesos, contrib = _laspeyres_contrib(idx_div, idx_tot, var12_tot)
        if contrib and all(s in contrib for s in slugs):
            for s in slugs:
                desglose[s]['peso'] = round(pesos[s], 4)
                desglose[s]['contrib'] = [
                    round(contrib[s][p], 4) if p in contrib[s] else None
                    for p in periodos]
        # KPIs precomputados: métricas del último periodo con var_12m no-null.
        ultimo_p = max((p for p, ind, _ in nac if ind == 'var_12m'),
                       default=None)
        ultimo = None
        if ultimo_p is not None:
            i = p_idx[ultimo_p]
            ultimo = {'periodo': ultimo_p,
                      **{m: general[m][i] for m in metricas_nac},
                      'provisional': ultimo_p in prov_periodos}
        return {'periodos': periodos, 'general': general,
                'desglose': desglose, 'ultimo': ultimo,
                'provisional': sorted(prov_periodos)}

    inflacion_data = {'ipc': None, 'ipp': None, 'ultimo': {'ipc': None, 'ipp': None}}
    # Overlay provisional del comunicado (tabla ine_ipc_comunicado, poblada por
    # ingest_ine_comunicado.py). Solo IPC; el Excel tiene prioridad.
    ipc_overlay = {}
    try:
        for r in conn.execute("SELECT periodo, var_mensual, var_acumulada, var_12m "
                              "FROM ine_ipc_comunicado"):
            ipc_overlay[r['periodo']] = {'var_mensual': r['var_mensual'],
                                         'var_acumulada': r['var_acumulada'],
                                         'var_12m': r['var_12m']}
    except Exception:
        pass  # tabla aún no existe → sin overlay
    try:
        ipc = _inflacion_familia('ine_ipc', 'ipc_nacional_general',
                                 'ipc_division_coicop', INE_IPC_DIVISIONES,
                                 overlay=ipc_overlay)
        if ipc:
            inflacion_data['ultimo']['ipc'] = ipc.pop('ultimo')
            ipc['divisiones'] = ipc.pop('desglose')
            inflacion_data['ipc'] = ipc
    except Exception:
        pass  # Table doesn't exist yet — graceful degradation
    try:
        ipp = _inflacion_familia('ine_ipp', 'ipp_nacional',
                                 'ipp_grandes_grupos', INE_IPP_GRUPOS)
        if ipp:
            inflacion_data['ultimo']['ipp'] = ipp.pop('ultimo')
            ipp['grupos'] = ipp.pop('desglose')
            inflacion_data['ipp'] = ipp
    except Exception:
        pass  # Table doesn't exist yet — graceful degradation

    # ── Noticias (from noticias table, if exists) ──
    # Últimos 30 días en hora Bolivia (UTC-4): el slider del tab cubre
    # exactamente [hoy-29 .. hoy] y el frontend no clampa — la ventana la
    # garantiza esta query. Schema por nota: HANDOFF.md § Frontend tab Noticias.
    noticias_data = []
    try:
        # Mirror/cache de ids ocultos (fuente de verdad = KV Cloudflare). Self-create
        # idempotente: la migración 0003 se aplica a mano en el VPS sin runner, así que
        # mergear a main no crea la tabla allá. Sin esto, el filtro de abajo tiraría
        # "no such table", el except la tragaría y la tab Noticias se BLANQUEARÍA en el
        # primer publish. Con la tabla vacía el filtro es no-op → build idéntico a hoy.
        conn.execute("CREATE TABLE IF NOT EXISTS noticias_hidden (id TEXT NOT NULL PRIMARY KEY)")
        # Self-migrate idempotente de image_url (FASE 2a). SQLite no tiene ADD COLUMN
        # IF NOT EXISTS, así que re-aplicar tira "duplicate column name" — inocuo, se
        # traga acá adentro (NO en el except de afuera, que blanquearía el feed). Igual
        # que el self-create de arriba, desacopla el build de cuándo se aplica 0004 a
        # mano en el VPS: sin esto, el SELECT de abajo tiraría "no such column", el
        # except lo tragaría y la tab Noticias se BLANQUEARÍA en el primer publish tras
        # el merge. Tabla inexistente (DB fresca) → "no such table" → al except de afuera
        # (degradación a feed vacío, igual que hoy).
        try:
            conn.execute("ALTER TABLE noticias ADD COLUMN image_url TEXT")
        except Exception:
            pass  # columna ya existe (idempotente)
        # Self-migrate de columnas FASE 3 (carril, tema_hits, entidades). Mismo
        # patrón: cada ALTER en su try para no abortar las siguientes. Nullables →
        # el SELECT/payload tolera NULL (COALESCE carril; entidades || '[]').
        for _col, _decl in (("carril", "TEXT"), ("tema_hits", "INTEGER"), ("entidades", "TEXT"),
                            ("tambien_en", "TEXT"), ("summary_origen", "TEXT"),
                            ("extract_len", "INTEGER"), ("resumen_reintentos", "INTEGER")):
            try:
                conn.execute(f"ALTER TABLE noticias ADD COLUMN {_col} {_decl}")
            except Exception:
                pass
        # `WHERE id IS NOT NULL` en el subquery: SQLite permite NULL en un TEXT PK, y
        # un solo NULL en el subquery volvería el NOT IN falso para TODA fila (footgun
        # del NOT IN), blanqueando el feed — justo lo que esta capa evita.
        noticias_rows = conn.execute(
            "SELECT id, date, time, source, category, title, summary, detail, "
            "       topics, impact, source_note, url, image_url, "
            "       COALESCE(carril, CASE WHEN category = 'latam' THEN 'latam' ELSE 'bolivia' END) AS carril, "
            "       tema, tema_hits, entidades, tambien_en, summary_origen, created_at_utc "
            "FROM noticias "
            "WHERE date >= date('now', '-4 hours', '-29 days') "
            "  AND id NOT IN (SELECT id FROM noticias_hidden WHERE id IS NOT NULL) "
            "ORDER BY date DESC, time DESC, puntaje DESC"
        ).fetchall()
        noticias_data = [{
            'id': r['id'], 'date': r['date'], 'time': r['time'],
            'source': r['source'], 'category': r['category'],
            'title': r['title'], 'summary': r['summary'], 'detail': r['detail'],
            'topics': json.loads(r['topics'] or '[]'),
            'impact': r['impact'], 'sourceNote': r['source_note'], 'url': r['url'],
            'imageUrl': r['image_url'],
            # Hora de la CORRIDA del scraper (ISO UTC). Solo la consume el gating admin
            # del render de hora (npTime): el carril BO la oculta al público y el admin la
            # ve como "Scrapeado a las HH:MM"; en Latam el admin la usa para el scrapeo real
            # (n.time de Latam es la publicación, no el scrapeo). No la ve el usuario normal.
            'createdAtUtc': r['created_at_utc'],
            'carril': r['carril'],   # 'bolivia'|'latam': el frontend parte los carriles por acá
            'tema': r['tema'],                  # tema fino (clasificación v1) — para matching de galería
            'temaConfianza': r['tema_hits'],    # confianza del tema (gate sugerido >=10)
            'entidades': json.loads(r['entidades'] or '[]'),
            # Mismo evento en otros medios (calibración 2026-06-21): [{source,portal,url}].
            'tambienEn': json.loads(r['tambien_en'] or '[]') if r['tambien_en'] else [],
            # Origen del summary (0007): 'ia'|'extractivo'|None(legacy). El frontend
            # marca con asterisco todo lo que NO sea 'ia' (NULL legacy = extractivo).
            'summaryOrigen': r['summary_origen'],
            # Slug de galería precomputado: motor v1.1 (keyword-priority PRIMARIO sobre
            # title+summary+detail; fallback al lookup por tema). El front arma
            # /gal-<slug>.webp; None → placeholder CSS. Ver gallery_slug_v2().
            'gallerySlug': gallery_slug_v2(r['title'], r['summary'], r['detail'],
                                           r['tema'], r['category'], r['carril']),
        } for r in noticias_rows]
        # Galería v2: asigna la imagen rotada por nota (gal-<slug>-<k>.webp) con
        # cooldown. Muta noticias_data agregando 'galleryImg'. Ver assign_gallery_images().
        assign_gallery_images(noticias_data)
    except Exception:
        pass  # Tabla noticias no existe aún (dev/fresh DB) — graceful degradation

    conn.close()

    payload = {
        # Schema columnar (commit 12 → único schema desde commit 17).
        'ts_metrics': ts_metrics,
        'merchants_last': merchants_last,
        'banks_daily': banks_daily,
        'offer_daily': offer_daily,
        'flow_per_snapshot': flow_per_snapshot,
        'order_book': order_book,
        'activity_heatmap': activity_matrix,
        'dpf_data': dpf_data,
        'embi_data': embi_data,
        'inflacion': inflacion_data,
        'noticias': noticias_data,
        'bloqueos': load_bloqueos(),
        'bcb_tre': load_bcb_tre(),
        'gaps': gaps,
        'meta': {
            'total_snapshots': len(timestamps),
            'total_ads': sum(d['buy_count'] + d['sell_count'] for d in ts_data),
            'first_ts': timestamps[0], 'last_ts': timestamps[-1], 'bcb_rate': BCB_RATE,
            'aids': aids_list,
            'version': '0.3.0',
            'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            **load_bcb_ref(first_date=timestamps[0][:10] if timestamps else None),
            **load_bcb_tco(first_date=timestamps[0][:10] if timestamps else None),
        }
    }
    # DPF desbakeado (config.MODULOS_NO_BAKEADOS): su panel/JS no se inyectan, así
    # que dpf_data es peso muerto en el DATA embebido — se omite. NO se toca la
    # tabla bcb_dpf_rates ni el ingest; solo se deja de emitir el payload.
    if 'dpf' in MODULOS_NO_BAKEADOS:
        payload.pop('dpf_data', None)
    return payload


# ── CSV horario ────────────────────────────────────────────────────────────

def export_hourly_csv(data: dict, csv_path: Path):
    import csv
    rows = []
    for d in data['ts']:
        rows.append({
            'timestamp_utc': d['ts'], 'buy_count': d['buy_count'], 'sell_count': d['sell_count'],
            'buy_depth_usdt': d['buy_depth'], 'sell_depth_usdt': d['sell_depth'],
            'depth_ratio': d['depth_ratio'],
            'vwap_buy_5': d.get('vb5'), 'vwap_buy_10': d.get('vb10'),
            'vwap_buy_25': d.get('vb25'), 'vwap_buy_50': d.get('vb50'),
            'vwap_sell_5': d.get('vs5'), 'vwap_sell_10': d.get('vs10'),
            'vwap_sell_25': d.get('vs25'), 'vwap_sell_50': d.get('vs50'),
            'spread_5': d.get('sp5'), 'spread_10': d.get('sp10'),
            'spread_25': d.get('sp25'), 'spread_50': d.get('sp50'),
            'top5_buy_pct': d.get('t5buy'), 'top5_sell_pct': d.get('t5sell'),
        })
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV horario: {csv_path} ({len(rows)} filas)")



# ── Umami injection (counter + tracker) ────────────────────────────────────

def _fmt_visits(n):
    """None → '—'. Int → separador de miles estilo '3,247' (mismo que hardcode)."""
    if n is None:
        return '—'
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return '—'


def _fetch_umami_stats() -> dict:
    """Trae las visitas de la API de Umami UNA sola vez (llamada HTTP).

    Separado de la inyección para que el doble bake (ES + EN) no duplique el
    hit a la API. Si faltan env vars o la API falla, devuelve Nones (counters
    en '—')."""
    api_key = os.environ.get('UMAMI_API_KEY', '').strip()
    website_id = os.environ.get('UMAMI_WEBSITE_ID', '').strip()
    host = os.environ.get('UMAMI_HOST', '').strip()
    auth_header = os.environ.get('UMAMI_AUTH_HEADER', '').strip() or None
    path_prefix = os.environ.get('UMAMI_API_PATH_PREFIX', '').strip() or None

    if api_key and website_id and host:
        kwargs = {}
        if auth_header: kwargs['auth_header'] = auth_header
        if path_prefix: kwargs['path_prefix'] = path_prefix
        return fetch_visits(api_key, website_id, host, **kwargs)
    return {'visits_today': None, 'visits_month': None}


def _inject_umami(html: str, stats: dict) -> str:
    """Reemplaza __VISITS_TODAY__, __VISITS_MONTH__ y __UMAMI_SCRIPT__ en el
    HTML ya horneado. `stats` viene de _fetch_umami_stats() (fetch único,
    inyección por idioma). Sin env vars el <script> de tracking no se emite."""
    website_id = os.environ.get('UMAMI_WEBSITE_ID', '').strip()
    host = os.environ.get('UMAMI_HOST', '').strip()
    script_url = os.environ.get('UMAMI_SCRIPT_URL', '').strip()

    html = html.replace('__VISITS_TODAY__', _fmt_visits(stats['visits_today']))
    html = html.replace('__VISITS_MONTH__', _fmt_visits(stats['visits_month']))

    if website_id and (script_url or host):
        src = script_url or f"{host.rstrip('/')}/script.js"
        tag = (f'<script async defer src="{src}" '
               f'data-website-id="{website_id}"></script>')
    else:
        tag = ''
    html = html.replace('__UMAMI_SCRIPT__', tag)
    return html


# ── Relabel por idioma (workstream f) ───────────────────────────────────────
# `data` se construye UNA sola vez (ver SEAM más abajo) con labels en español
# (INE_IPC_DIVISIONES / INE_IPP_GRUPOS). Para EN no se reconstruye la data:
# se relabelan in-place las dos subtrees que cargan 'label' (payload de
# inflación IPC/IPP), sobre un deep copy — el payload ES nunca se toca. Los
# slugs desconocidos (futuros cambios del INE) preservan el mismo fallback
# que process_data ya usa: slug.replace('_', ' ').capitalize().
_RELABEL_PATHS = (
    # (ruta dentro de data['inflacion'], prefijo de clave i18n)
    (('ipc', 'divisiones'), 'data.coicop.'),
    (('ipp', 'grupos'), 'data.pib.'),
)


def _relabel_inflacion_for_lang(data: dict, table: dict) -> dict:
    """Devuelve `data` con los labels de divisiones/grupos de inflación
    resueltos contra `table` (i18n_bake.load_lang(lang)) para el idioma dado.

    No muta `data`: deep-copy solo de la subtree 'inflacion' (evita copiar
    ts_metrics/merchants/etc., que son potencialmente grandes). El resto del
    dict se comparte por referencia con el original.
    """
    out = dict(data)
    inflacion = copy.deepcopy(data.get('inflacion'))
    if inflacion:
        for (familia, campo), prefix in _RELABEL_PATHS:
            desglose = (inflacion.get(familia) or {}).get(campo)
            if not desglose:
                continue
            for slug, entry in desglose.items():
                entry['label'] = table.get(
                    prefix + slug, slug.replace('_', ' ').capitalize())
    out['inflacion'] = inflacion
    return out


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera dashboard HTML desde SQLite")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Base SQLite (default: {DEFAULT_DB})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"HTML de salida (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--output-en", type=Path, default=None,
                        help="HTML de salida en inglés "
                             "(default: <dir de --output>/en/index.html)")
    parser.add_argument("--csv", action="store_true",
                        help="También exportar CSV con métricas por snapshot")
    parser.add_argument("--incluir-modulo", action="append", metavar="MOD",
                        help="Bakear también este módulo desbakeado SOLO en esta "
                             "corrida (repetible; ej. --incluir-modulo agro). "
                             "Pensado para previews locales de módulos de "
                             "config.MODULOS_NO_BAKEADOS — no muta la config ni "
                             "afecta el publish productivo.")
    args = parser.parse_args()

    # --incluir-modulo solo acepta módulos desbakeados conocidos: un typo
    # silencioso produciría un preview SIN el módulo pedido, sin aviso.
    desconocidos = set(args.incluir_modulo or []) - MODULOS_NO_BAKEADOS
    if desconocidos:
        parser.error(
            f"--incluir-modulo desconocido(s): {', '.join(sorted(desconocidos))}. "
            f"Válidos: {', '.join(sorted(MODULOS_NO_BAKEADOS))}")

    if not args.db.exists():
        print(f"No se encontró {args.db}. Corré normalize.py primero.", file=sys.stderr)
        sys.exit(1)

    print(f"Leyendo {args.db} ...")
    data = process_data(args.db)

    print(f"  {data['meta']['total_snapshots']} snapshots, "
          f"{data['meta']['total_ads']:,} anuncios")

    template = TEMPLATE_HTML.read_text(encoding='utf-8')

    # Data única para ambos idiomas (una sola pasada de process_data). Labels
    # de inflación IPC/IPP (COICOP/PIB) sí varían por idioma: se resuelven acá
    # ABAJO, dentro del loop, sobre un deep-copy barato de la subtree
    # 'inflacion' (_relabel_inflacion_for_lang) — nunca se reconstruye `data`
    # dos veces ni se muta el payload ES.
    umami_stats = _fetch_umami_stats()  # fetch único (una sola llamada HTTP)

    # Módulos excluidos del bake: los desbakeados MENOS los pedidos por CLI
    # (--incluir-modulo, preview local). Set nuevo — la config no se muta y
    # process_data sigue gobernada por MODULOS_NO_BAKEADOS (los payloads de
    # módulos con data en DATA, ej. dpf, no se re-emiten por este flag).
    excluidos = MODULOS_NO_BAKEADOS - set(args.incluir_modulo or [])

    output_en = args.output_en or (args.output.parent / 'en' / 'index.html')
    for lang, base, outpath in (('es', '', args.output),
                                ('en', '/en', output_en)):
        try:
            lang_table = i18n_bake.load_lang(lang)
            html = i18n_bake.bake(template, lang, base, lang_table,
                                  excluidos=excluidos)
            data_lang = _relabel_inflacion_for_lang(data, lang_table)
            data_json = json.dumps(data_lang)
        except Exception as e:
            if lang == 'es':
                raise  # ES es el producto primario: abort ruidoso, sin output.
            # EN fail-soft: un problema de en.json (clave faltante, JSON roto)
            # NO puede frenar el publish del ES. Se omite el output EN — el
            # publish degradará a warn + EN stale (validate_en output_missing).
            print(f"[i18n] WARN: bake EN falló — se omite {outpath} "
                  f"(el ES no se bloquea): {e}", file=sys.stderr)
            continue
        html = html.replace('__DATA_PLACEHOLDER__', data_json)
        html = _inject_umami(html, umami_stats)

        outpath.parent.mkdir(parents=True, exist_ok=True)
        with open(outpath, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Dashboard ({lang}): {outpath} "
              f"({outpath.stat().st_size / 1024:.1f} KB)")
        # Alias por compatibilidad (solo para el ES default index.html)
        if lang == 'es' and outpath.name == 'index.html':
            alias = outpath.with_name('p2p_dashboard.html')
            with open(alias, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"Alias:     {alias}")

    # Boletín diario (texto plano copy-paste, ES only) → <dir de index.html>/
    # boletin-4k9x/index.html. Reusa el `data` ya computado (no re-corre
    # process_data). Fail-SAFE con matiz: si falta un valor base, boletin.write_boletin
    # lanza BoletinDataError y acá se loguea RUIDOSO y se OMITE la escritura — el
    # archivo anterior queda intacto (un boletín con hueco es peor que uno viejo).
    # Un fallo del boletín NUNCA bloquea el publish del index.html (mismo espíritu
    # fail-safe que _inject_riesgo / el EN fail-soft).
    try:
        bpath = boletin.write_boletin(data, args.output.parent)
        print(f"Boletín:   {bpath} ({bpath.stat().st_size / 1024:.1f} KB)")
    except boletin.BoletinDataError as e:
        print(f"[boletin] ERROR: {e} — se preserva el boletín anterior "
              f"(no se emite parcial).", file=sys.stderr)
    except Exception as e:
        print(f"[boletin] WARN: fallo inesperado ({type(e).__name__}: {e}) — "
              f"se preserva el boletín anterior.", file=sys.stderr)

    if args.csv:
        csv_path = args.output.with_name('p2p_metrics.csv')
        export_hourly_csv(data, csv_path)

    print("Abrí los .html en cualquier navegador para ver el dashboard "
          f"(ES: {args.output} · EN: {output_en}).")


if __name__ == "__main__":
    main()
