"""
config.py — Constantes compartidas del proyecto Binance P2P USDT/BOB.

Centraliza valores que cruzan varios scripts: tipos de cambio referenciales,
rutas default de entrada/salida, intervalos del loop de ingesta y umbrales
del watchdog. Los scripts importan de aquí en lugar de redefinir.

Las constantes específicas de un solo módulo (ej. parámetros del POST a
Binance, keywords de KYC, fields de restricciones del taker) viven en sus
respectivos archivos.
"""

import os
from pathlib import Path

# ── Tipo de cambio oficial (referencia para prima paralela) ─────────────────
# OJO: 6.96 es el tipo de cambio FIJO histórico (vigente 2011 → jun-2026), hoy
# obsoleto. Desde la RD N° 88/2026 (26-jun-2026) el oficial es el TCO diario
# (ver BCB_TCO_JSON / ingest_bcb_tco.py). Se conserva como fallback fail-soft
# del frontend cuando aún no hay datos de TCO.
BCB_RATE = 6.96

# ── Rutas default (relativas a la raíz del proyecto / cwd) ──────────────────
SNAPSHOTS_DIR = Path("snapshots")
LOGS_DIR = Path("logs")
NORMALIZED_DB = Path("p2p_normalized.db")
DASHBOARD_HTML = Path("index.html")
BCB_REF_JSON = Path("bcb_referencial.json")
BCB_TCO_JSON = Path("bcb_tco.json")  # Tipo de Cambio Oficial diario (RD 88/2026)
BCB_TRE_JSON = Path("bcb_tre.json")  # Tasa de Referencia mensual (Actas 026/2018 y 040/2023)
TEMPLATE_HTML = Path(__file__).parent / "template.html"

# ── Módulos desbakeados (opción B: presentes en repo, NO servidos en prod) ──
# Punto de control ÚNICO del desbake. Un módulo listado aquí NO se inyecta en
# index.html (dashboard.py lo strippea vía marcadores `bake:optional:<mod>` +
# omite su payload) NI se sirve su asset estático (publish_dashboard.py lo
# excluye del copiado de static/). Su código fuente PERMANECE en el repo.
#
# Revertir (re-bakear un módulo) = quitarlo de este set y rebakear. Es la ÚNICA
# edición necesaria — nada de arqueología. (Nota de acoplamiento: `guide`
# depende de datasets/helpers de `bbv`; re-bakear `guide` requiere `bbv` también
# bakeado. Ver HANDOFF.md § Módulos desbakeados.)
# `agro` RE-DESBAKEADO (pedido de Diego 2026-07-16): la tab entera se guarda
# (tab + subtabs + rutas + assets, todo envuelto en bake:optional:agro) y sale
# del HTML publicado. Revertir = quitar "agro" del set. Historial: desbakeado
# hasta 2026-07-10, luego bakeado público, ahora oculto de nuevo.
MODULOS_NO_BAKEADOS = {"dpf", "bbv", "guide", "mercado247", "agro", "calendario"}

# Assets en static/ que pertenecen a un módulo. publish_dashboard.py no copia a
# prod los de módulos desbakeados (derivado de MODULOS_NO_BAKEADOS, no lista
# paralela). Solo mercado247 sirve un asset propio; dpf/bbv/guide viven inline.
MODULO_ASSETS = {
    "mercado247": ("mercado247-tab.js",),
    # agro: datasets lazy del front (fetch absoluto /agro_*.json). Entrada
    # DORMIDA desde 2026-07-10 (agro salió de MODULOS_NO_BAKEADOS → sus assets
    # SÍ se publican); se conserva para re-desbakear con solo re-agregar "agro"
    # al set. Se listan también los shards preventivos agro_prod_g1..g7 del
    # harvest completo: HOY no existen en static/ (el índice parcial trae
    # series_mun inline) y listar nombres inexistentes es inocuo (publish solo
    # filtra archivos presentes) — future-proof para cuando el harvest los genere.
    "agro": (
        "agro_produccion.json", "agro_exportaciones.json", "agro_precios.json",
        "agro_geo_municipal.json", "agro_geo_departamental.json",
        "agro_prod_g1.json", "agro_prod_g2.json", "agro_prod_g3.json",
        "agro_prod_g4.json", "agro_prod_g5.json", "agro_prod_g6.json",
        "agro_prod_g7.json",
    ),
}


def assets_no_publicados() -> set:
    """Nombres de archivos de static/ que NO deben copiarse a prod porque su
    módulo está desbakeado. Único derivado de MODULOS_NO_BAKEADOS + MODULO_ASSETS."""
    return {a for m in MODULOS_NO_BAKEADOS for a in MODULO_ASSETS.get(m, ())}

# Backup opcional de snapshots (env var P2P_BACKUP_DIR). Si no está definida
# o la ruta no existe, normalize.py la ignora silenciosamente.
_backup_env = os.environ.get("P2P_BACKUP_DIR", "").strip()
SNAPSHOTS_BACKUP_DIR = Path(_backup_env) if _backup_env else Path("snapshots_backup_not_configured")

# ── Loop de ingesta ─────────────────────────────────────────────────────────
INGEST_INTERVAL_S = 600  # 10 min

# ── Watchdog ────────────────────────────────────────────────────────────────
WATCHDOG_STALE_MIN = 15

# ── Noticias ingest (tab Noticias) ──────────────────────────────────────────
# Cupos diarios por carril (presupuestos INDEPENDIENTES; budget rolling: las
# corridas del día llenan hasta el cupo, no la primera se queda con todo).
# También overridables por CLI (--top / --top-latam). Subidos de 10/5 → 14/8
# en FASE 3 para más cobertura con la cadencia diurna cada 3h. BO subido a 50
# al pasar de budget ADITIVO (llenaba y frenaba) a ranking ROTATIVO intra-día
# (la de menor score se evicta cuando entra una mejor; ver lane_bolivia).
NOTICIAS_TOP_BOLIVIA = 50
NOTICIAS_TOP_LATAM = 8

# ── INE Bolivia ingest ──────────────────────────────────────────────────────
# Audit folder en VPS prod; en laptop dev OSError → degradación elegante.
INE_AUDIT_DIR = Path("/opt/binance_p2p/ine_audit")

# Dos hosts conviven: nimbus (Nextcloud nuevo, 303→200) y nube (Owncloud, 200 directo).
# Mismo token a veces resuelve en ambos; mantener primary + fallback explícito.
INE_HOSTS = {
    "nimbus": "https://nimbus.ine.gob.bo",
    "nube":   "https://nube.ine.gob.bo",
}

# Cuadro registry — V1 scope, 8 cuadros.
# `host` es el host primario confirmado; el fallback es el OTRO host con el mismo token.
# `family` = 'pib' | 'ipc' (selecciona el ingest script).
# `layout` selecciona el adapter de parsing en ine_parser.py.
# `unit` (PIB) / `base_year` (IPC) son metadata persistida en cada fila.
# `dimension_kind` (PIB) describe el eje no-temporal del cuadro.
INE_CUADROS = {
    # ── PIB Trimestral (host nimbus, layout vertical) ──
    "pib_trim_01_01_01": {
        "host": "nimbus", "token": "LgCGFBWiz2QccwP",
        "family": "pib", "layout": "pib_trim_vertical",
        "desc": "PIB constante por actividad (trimestral, base 1990)",
        "unit": "miles_bs_1990", "dimension_kind": "actividad",
    },
    "pib_trim_01_01_04": {
        "host": "nimbus", "token": "r6rwwCc9LqddEys",
        "family": "pib", "layout": "pib_trim_vertical",
        "desc": "Var YoY PIB constante por actividad (trimestral)",
        "unit": "pct_yoy", "dimension_kind": "actividad",
    },
    "pib_trim_02_01_01": {
        "host": "nimbus", "token": "HPaSw4gp9LG8Xit",
        "family": "pib", "layout": "pib_trim_vertical",
        "desc": "PIB constante por gasto (trimestral, base 1990)",
        "unit": "miles_bs_1990", "dimension_kind": "gasto",
    },
    # ── PIB Anual Serie Histórica (host nube, layout wide) ──
    "pib_anual_serie_actividad": {
        "host": "nube", "token": "5HukXcuvSj76wKo",
        "family": "pib", "layout": "pib_anual_wide",
        "desc": "Serie histórica PIB cte por actividad 1980-presente",
        "unit": "miles_bs_1990", "dimension_kind": "actividad",
    },
    "pib_anual_serie_gasto": {
        "host": "nube", "token": "dksqGfnoVsCeeq6",
        "family": "pib", "layout": "pib_anual_wide",
        "desc": "Serie histórica PIB cte por gasto 1980-presente",
        "unit": "miles_bs_1990", "dimension_kind": "gasto",
    },
    # ── IPC (host nube) ──
    "ipc_nacional_general": {
        "host": "nube", "token": "P2HkvtlKILPhbvB",
        "family": "ipc", "layout": "ipc_nacional",
        "desc": "IPC Nacional: índice general + var mensual/acumulada/12 meses",
        "base_year": "2016",
    },
    "ipc_division_coicop": {
        "host": "nube", "token": "xiffVcALyTuppvB",
        "family": "ipc", "layout": "ipc_coicop_doubleheader",
        "desc": "IPC por División COICOP (12 divisiones + total general)",
        "base_year": "2016",
    },
    "ipc_empalmada": {
        "host": "nube", "token": "Jyfc30EJeAiTMvh",
        "family": "ipc", "layout": "ipc_empalmada",
        "desc": "IPC Serie Histórica Empalmada (1937-presente, base 2016)",
        "base_year": "2016",
    },
    # ── IPP (Índice de Precios al Productor, host nube) ──
    # Estructuralmente idéntico al IPC: 4 hojas (1.1-1.4), single-band header
    # para el nacional / double-band para el sectorial. Reutiliza los mismos
    # adapters via aliases en LAYOUT_DISPATCH. Base year confirmado 2016=100.
    "ipp_nacional": {
        "host": "nube", "token": "jiPDzh0nsOiDGY0",
        "family": "ipp", "layout": "ipp_nacional",
        "desc": "IPP Bolivia agregado: índice general + var mensual/acumulada/12 meses",
        "base_year": "2016",
    },
    "ipp_grandes_grupos": {
        "host": "nube", "token": "RbTQhRDB6bpuPWx",
        "family": "ipp", "layout": "ipp_grandes_grupos",
        "desc": "IPP por Grandes Grupos (6 sectores actividad + total general)",
        "base_year": "2016",
    },
}


def ine_url(cuadro_id: str, host_override: str | None = None) -> str:
    """URL de descarga del share Nextcloud/Owncloud. host_override permite probar
    el fallback (el otro host) si el primario devolvió 404."""
    c = INE_CUADROS[cuadro_id]
    host = host_override or c["host"]
    return f"{INE_HOSTS[host]}/index.php/s/{c['token']}/download"
