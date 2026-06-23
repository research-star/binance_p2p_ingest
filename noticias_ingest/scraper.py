"""
scraper.py — Scraper + scoring de noticias económicas de Bolivia.

Port headless de buscar_noticias.py (research-star/boletines, v2.20). Se
conserva el pipeline scrape → score → dedupe intra-corrida casi verbatim
para que futuros diffs contra el origen sean legibles. Se eliminó todo lo
acoplado al flujo boletines: progreso.json/watchdog de la app Flask,
outputs CSV/MD para el paso de resúmenes vía Claude, y el logging global.

API pública:
    correr_scraper() -> (candidatos, descartados, portales_ok, portales_fail)

Cada candidato: {puntaje, tema, portal, titulo, descripcion, cuerpo, link,
portales_lista, score_crudo, score_ajustado, ajuste_aplicado}.

Si existe modelo_relevancia.pkl (junto a este archivo), usa TF-IDF para
puntuar relevancia (puntaje = score_ajustado × 10). Si no, usa keywords.
"""

import hashlib
import logging
import pickle
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup

try:
    import trafilatura
    TIENE_TRAFILATURA = True
except ImportError:
    TIENE_TRAFILATURA = False

try:
    from rapidfuzz import fuzz
    TIENE_RAPIDFUZZ = True
except ImportError:
    TIENE_RAPIDFUZZ = False

try:
    import cloudscraper
    TIENE_CLOUDSCRAPER = True
except ImportError:
    TIENE_CLOUDSCRAPER = False

try:
    from curl_cffi import requests as curl_requests
    TIENE_CURL_CFFI = True
except ImportError:
    TIENE_CURL_CFFI = False

try:
    from googlenewsdecoder import new_decoderv1
    TIENE_GNEWS_DECODER = True
except ImportError:
    TIENE_GNEWS_DECODER = False

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"   # runtime: cache_urls.db, debug CSV — gitignored

HORAS_ATRAS = 28
CACHE_DB_PATH = DATA_DIR / "cache_urls.db"
MODELO_PATH = BASE_DIR / "modelo_relevancia.pkl"
CACHE_DIAS = 7
MAX_WORKERS = 6
TIMEOUT_URL_CUERPO = 15       # segundos máximo por URL en fase de cuerpos
TIMEOUT_PORTAL_CUERPOS = 90   # segundos acumulados por portal en fase de cuerpos

# Umbral mínimo de probabilidad para incluir como candidato (pre-selección;
# el corte editorial de la tab es puntaje >= 6.7 y lo aplica ingest_noticias.py)
UMBRAL_MODELO = 0.33

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-BO,es;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# HASH DE LINK
# ---------------------------------------------------------------------------
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_EXACT = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def hash_link(url: str) -> str:
    """MD5 corto (16 chars hex) del link normalizado. Pura, determinística.
    Desvío del origen (6 chars): acá el hash es PRIMARY KEY de una tabla
    persistente sin retención — 24 bits daban colisión de cumpleaños
    esperable en ~1-2 años de feed; 64 bits la vuelven despreciable."""
    u = (url or "").strip().lower()
    if not u:
        log.warning("hash_link recibió URL vacía/None")
        return hashlib.md5(b"").hexdigest()[:16]
    try:
        p = urlparse(u)
        qs = [
            (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
            if not (any(k.startswith(pref) for pref in _TRACKING_PREFIXES)
                    or k in _TRACKING_EXACT)
        ]
        path = p.path.rstrip("/")
        normalizado = urlunparse((p.scheme, p.netloc, path, p.params, urlencode(qs), ""))
    except Exception:
        normalizado = u
    return hashlib.md5(normalizado.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# MODELO TF-IDF
# ---------------------------------------------------------------------------
MIN_ETIQUETAS_MODELO = 150
MIN_F1_MODELO = 0.80


class ModeloRelevancia:
    def __init__(self, path: Path = MODELO_PATH):
        self.disponible = False
        self.vectorizador = None
        self.clasificador = None
        self.motivo_rechazo = ""
        self._cargar(path)

    def _cargar(self, path: Path):
        if not path.exists():
            log.info("  Modelo TF-IDF no encontrado — usando keywords")
            return
        try:
            with path.open("rb") as f:
                m = pickle.load(f)
        except Exception as e:
            log.warning(f"  Error cargando modelo: {e} — usando keywords")
            return

        n_etiquetas = m.get("n_etiquetas", 0)
        f1_cv = m.get("f1_cv", 0.0)

        if n_etiquetas < MIN_ETIQUETAS_MODELO:
            self.motivo_rechazo = (
                f"solo {n_etiquetas} etiquetas (mínimo {MIN_ETIQUETAS_MODELO})"
            )
            log.warning(
                f"  Modelo TF-IDF descartado: {self.motivo_rechazo} — usando keywords"
            )
            return

        if f1_cv < MIN_F1_MODELO:
            self.motivo_rechazo = f"F1={f1_cv:.3f} (mínimo {MIN_F1_MODELO})"
            log.warning(
                f"  Modelo TF-IDF descartado: {self.motivo_rechazo} — usando keywords"
            )
            return

        self.vectorizador = m["vectorizador"]
        self.clasificador = m["clasificador"]
        self.disponible = True
        log.info(
            f"  Modelo TF-IDF activo (F1={f1_cv:.3f}, "
            f"{n_etiquetas} etiquetas, umbral={UMBRAL_MODELO})"
        )

    def puntaje(self, titulo: str, descripcion: str) -> float:
        """Devuelve probabilidad de relevancia [0.0 - 1.0]."""
        if not self.disponible:
            return -1.0  # señal de "usar keywords"
        texto = f"{titulo} {descripcion}"
        X = self.vectorizador.transform([texto])
        prob = self.clasificador.predict_proba(X)[0][1]
        return float(prob)


_MODELO = None


def get_modelo() -> ModeloRelevancia:
    global _MODELO
    if _MODELO is None:
        _MODELO = ModeloRelevancia()
    return _MODELO


# ---------------------------------------------------------------------------
# CACHÉ SQLITE DE URLs VISTAS (TTL 7 días; se recrea local/VPS, no se commitea)
# ---------------------------------------------------------------------------
class CacheURLs:
    def __init__(self, db_path: Path, dias: int = CACHE_DIAS):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS urls_vistas (
                url TEXT PRIMARY KEY, portal TEXT, first_seen TEXT
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_seen ON urls_vistas(first_seen)"
        )
        self.conn.commit()
        corte = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        deleted = self.conn.execute(
            "DELETE FROM urls_vistas WHERE first_seen < ?", (corte,)
        ).rowcount
        self.conn.commit()
        if deleted:
            log.info(f"  Caché: {deleted} URLs antiguas eliminadas")

    def ya_vista(self, url: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM urls_vistas WHERE url = ?", (url,)
        ).fetchone() is not None

    def marcar(self, url: str, portal: str):
        try:
            self.conn.execute(
                "INSERT OR IGNORE INTO urls_vistas (url, portal, first_seen) VALUES (?,?,?)",
                (url, portal, datetime.now().strftime("%Y-%m-%d"))
            )
            self.conn.commit()
        except Exception:
            pass

    def close(self):
        self.conn.close()


def marcar_urls_vistas(urls_portales, cache_db_path: Path = None):
    """Marca (url, portal) como vistas en la caché TTL. La invoca el CALLER
    (ingest_noticias) DESPUÉS de decidir el budget: marca solo las insertadas +
    las que no calificaron, de modo que una nota calificada-no-insertada (perdió
    el top-N o el dedupe) siga reconsiderable en corridas posteriores. Antes
    correr_scraper marcaba TODO lo evaluado (bug: las que perdían el top-N
    quedaban vistas y nunca se reconsideraban). `cache_db_path=None` lee el módulo
    global en tiempo de llamada (testeable vía monkeypatch de CACHE_DB_PATH)."""
    if not urls_portales:
        return
    cache = CacheURLs(cache_db_path or CACHE_DB_PATH, CACHE_DIAS)
    try:
        for url, portal in urls_portales:
            cache.marcar(url, portal)
    finally:
        cache.close()


# ---------------------------------------------------------------------------
# FUENTES
# ---------------------------------------------------------------------------
FUENTES = [
    {
        "portal": "El Deber",
        "rss": [
            "https://eldeber.com.bo/rss/economia",
            "https://eldeber.com.bo/rss/pais",
            "https://eldeber.com.bo/rss",
            "https://news.google.com/rss/search?q=site:eldeber.com.bo+economia+OR+Bolivia&hl=es-419&gl=BO&ceid=BO:es",
        ],
        "scrape_urls": ["https://eldeber.com.bo/economia", "https://eldeber.com.bo/pais"],
        "scrape_selector": "h2 a, h3 a, .article-title a",
        # /pais mezcla economía/política nacional y su feed RSS (cap 25 entries, ~21h en
        # días de alto volumen) no cubre la ventana de 28h. Se scrapea SIEMPRE además del
        # camino RSS; el sufijo _<epoch> de cada URL filtra recencia y chrome (_epoch_url).
        "scrape_complemento": ["https://eldeber.com.bo/pais"],
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "Correo del Sur",
        "rss": [
            "https://news.google.com/rss/search?q=site:correodelsur.com+economia+OR+politica&hl=es-419&gl=BO&ceid=BO:es",
        ],
        "scrape_urls": [
            "https://correodelsur.com/economia",
            "https://correodelsur.com/politica",
            "https://correodelsur.com/local",
        ],
        "scrape_selector": "h2 a, h3 a, .titulo a, article a",
        "solo_bolivia": False, "metodo": "trafilatura",
    },
    {
        "portal": "Unitel",
        # Feeds anteriores muertos (404) y Google News retirados: la sección real
        # /noticias/economia es estáticamente scrapeable (no JS) con selector "article a".
        "rss": [],
        "scrape_urls": ["https://unitel.bo/noticias/economia"],
        "scrape_selector": "article a",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "La Razón",
        # Feeds generales (ruido + cap 10) reemplazados por scrape de la sección economía
        # dedicada con paginación (cubre ~28h). filtro_url restringe el scrape a artículos
        # de /economia-y-empresa/ (la página de sección lista chrome de todo el sitio).
        "rss": [],
        "scrape_urls": [
            "https://larazon.bo/economia-y-empresa/",
            "https://larazon.bo/economia-y-empresa/page/2/",
            "https://larazon.bo/economia-y-empresa/page/3/",
        ],
        "scrape_selector": "h2 a, h3 a, .post-title a",
        "scrape_paginas": 3,
        "filtro_url": "/economia-y-empresa/",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "Bloomberg Línea",
        "rss": [
            "https://www.bloomberglinea.com/arc/outboundfeeds/rss/category/economia/?outputType=xml",
        ],
        "scrape_urls": [
            "https://www.bloomberglinea.com/latinoamerica/bolivia/",
            "https://www.bloomberglinea.com/tag/bolivia/",
        ],
        "scrape_selector": "h2 a, h3 a, .headline a, article h2 a",
        "solo_bolivia": True, "metodo": "requests",
        "filtro_url": "/latinoamerica/bolivia/",
    },
    {
        "portal": "Eju!",
        "rss": ["https://eju.tv/feed/"],
        "scrape_urls": ["https://eju.tv"],
        "scrape_selector": "h2 a, h3 a, .entry-title a",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "El Día",
        "rss": [],  # feed/ devuelve 9 bytes vacios
        "scrape_urls": ["https://eldia.com.bo/economia"],
        "scrape_selector": "a[href*='/economia/']",
        "solo_bolivia": False, "metodo": "curl_cffi",
    },
    {
        "portal": "Brújula Digital",
        "rss": [],  # RSS muerto (feed/ y economia/feed/ devuelven 0 items)
        "scrape_urls": ["https://brujuladigital.net/economia/"],
        "scrape_selector": "a[href*='/economia/2026/'], a[href*='/economia/2027/']",
        "solo_bolivia": False, "metodo": "curl_cffi",
    },
    # El Diario eliminado: Sucuri WAF bloquea cuerpos (307), RSS sin filtro económico, mucho ruido
    {
        "portal": "Noticias Fides",
        "rss": [
            "https://news.google.com/rss/search?q=site:noticiasfides.com+bolivia+economia&hl=es-419&gl=BO&ceid=BO:es",
        ],
        "scrape_urls": [],
        "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "Erbol",
        "rss": [],  # RSS inexistente (Drupal sin feed habilitado)
        "scrape_urls": ["https://www.erbol.com.bo/economia"],
        # URLs con /economía/ (acento URL-encoded) y /economia/ (sin acento)
        "scrape_selector": "a[href*='/econom%C3%ADa/'], a[href*='/economia/']",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "Urgente.bo",
        "rss": ["https://urgente.bo/feed/"],
        "scrape_urls": ["https://urgente.bo"],
        "scrape_selector": "h2 a, h3 a, .entry-title a",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        # Opinión: RSS autodiscovery nativo Opennemas. Cadencia editorial baja
        # desde abril 2026 — monitorear. Filtro Bolivia activo porque RSS mezcla
        # política/deportes/nacional con economía.
        "portal": "Opinión",
        "rss": ["https://www.opinion.com.bo/rss/"],
        "scrape_urls": ["https://www.opinion.com.bo/pais/"],
        "scrape_selector": "h2 a, h3 a",
        "solo_bolivia": True, "metodo": "curl_cffi",
    },
    {
        "portal": "Los Tiempos",
        "rss": [
            "https://www.lostiempos.com/rss/lostiempos-titulares.xml",
            "https://www.lostiempos.com/rss/lostiempos-local.xml",
            "https://news.google.com/rss/search?q=site:lostiempos.com+economia&hl=es-419&gl=BO&ceid=BO:es",
        ],
        "scrape_urls": ["https://lostiempos.com/actualidad/economia/"],
        "scrape_selector": "h2 a, h3 a, .field-title a",
        "solo_bolivia": False, "metodo": "requests",
    },

    # ── Fuentes nuevas (calibración 2026-06-21) ──────────────────────────────
    # PENDIENTE VALIDAR EN VPS: agregadas vía Google News site-search (mismo patrón
    # que El Deber/Correo/Fides — no requiere recon del HTML de cada sitio, que no
    # se puede hacer desde el entorno de build por la política de red). Google News
    # puede no indexar bien los .gob.bo/.org.bo institucionales → Diego corre un
    # dry-run (`python ingest_noticias.py --dry-run`) y poda las que no rindan. El
    # scraper aísla fallos por portal (lista `fail`), así que una fuente muerta NO
    # rompe la corrida. Los slugs ya están en SOURCE_TIER (oficiales/gremios = T1).
    # Para fuentes con scraping directo de su sala de prensa (más fiable que GN),
    # hace falta recon por-sitio con red — follow-up del VPS.
    #
    # Periódicos:
    {
        "portal": "La Patria",
        "rss": ["https://news.google.com/rss/search?q=site:lapatriaenlinea.com+economia+OR+Bolivia&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "El Mundo",
        "rss": ["https://news.google.com/rss/search?q=site:elmundo.com.bo+economia+OR+Bolivia&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    # Oficiales (T1):
    {
        "portal": "BCB",
        "rss": ["https://news.google.com/rss/search?q=site:bcb.gob.bo&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "INE",
        "rss": ["https://news.google.com/rss/search?q=site:ine.gob.bo&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "MEFP",
        "rss": ["https://news.google.com/rss/search?q=site:economiayfinanzas.gob.bo&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "ASFI",
        "rss": ["https://news.google.com/rss/search?q=site:asfi.gob.bo&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "Aduana",
        "rss": ["https://news.google.com/rss/search?q=site:aduana.gob.bo&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    # Gremios (T1):
    {
        "portal": "CAINCO",
        "rss": ["https://news.google.com/rss/search?q=site:cainco.org.bo+OR+CAINCO+Bolivia&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "IBCE",
        "rss": ["https://news.google.com/rss/search?q=site:ibce.org.bo+OR+IBCE+Bolivia&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "CEPB",
        "rss": ["https://news.google.com/rss/search?q=site:cepb.org.bo+OR+CEPB+Bolivia&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
    {
        "portal": "CNI",
        "rss": ["https://news.google.com/rss/search?q=site:cni.org.bo+OR+%22C%C3%A1mara+Nacional+de+Industrias%22&hl=es-419&gl=BO&ceid=BO:es"],
        "scrape_urls": [], "scrape_selector": "",
        "solo_bolivia": False, "metodo": "requests",
    },
]


# ---------------------------------------------------------------------------
# KEYWORDS (solo conteo de relevancia del fallback sin modelo — MUERTO en prod por
# fail-closed; el TEMA lo clasifica _tema/_TEMA_SPEC, no estas listas)
# ---------------------------------------------------------------------------
KEYWORDS = {
    "Combustibles / YPFB": [
        "combustible", "diésel", "diesel", "gasolina", "ypfb", "carburante",
        "surtidor", "abastecimiento", "gnv", "glp", "hidrocarburo", "refinería",
        "desabastecimiento", "gasolina plus", "medinacelli", "petroleo",
    ],
    "Tipo de cambio / Dólar": [
        "dólar", "tipo de cambio", "reservas internacionales", "bcb",
        "banco central", "divisa", "paralelo", "devaluación",
        "tarjeta crédito", "tarjeta débito", "itf", "dólar referencial",
        "asoban", "asfi", "divisas",
    ],
    "Litio / Minería": [
        "litio", "yacimiento", "minería", "ylb", "cobalto", "zinc",
        "plata", "oro", "salar", "uyuni", "minero",
    ],
    "Agropecuario / Soya": [
        "soya", "soja", "agro", "agroindustria", "productores", "carne bovina",
        "maíz", "trigo", "cosecha", "zafra", "senasag", "frigorífico",
        "agropecruz", "bovino", "anapo", "cao",
    ],
    "Deuda / Finanzas": [
        "deuda", "crédito", "bono", "fitch", "moody", "préstamo",
        "fmi", "bid", "caf", "banco mundial", "calificación crediticia",
        "déficit fiscal", "impuesto", "sistema financiero", "banca boliviana",
    ],
    "Inflación / Precios": [
        "inflación", "canasta básica", "ipc", "costo de vida", "encarecimiento", "ine ",
    ],
    "Exportaciones / Comercio": [
        "exportación", "importación", "aduana", "ibce", "cainco", "balanza comercial",
    ],
    "Inversión / Infraestructura": [
        "inversión", "licitación", "obra pública", "carretera",
        "contratación directa", "ds 5600",
    ],
    "Elecciones / Política económica": [
        "segunda vuelta", "balotaje", "ministro de economía", "mefp",
        "rodrigo paz", "tse ", "ted ",
    ],
    "Bloqueos / Conflictos": [
        "bloqueo", "paro indefinido", "movilización", "corte de ruta",
    ],
    "EMAPA / Alimentos": [
        "emapa", "seguridad alimentaria", "ley 157",
    ],
}

KEYWORDS_FORZADO = [
    "ypfb", "bcb", "mefp", "ibce", "cainco", "senasag", "emapa", "ylb",
    "reservas internacionales", "tipo de cambio", "dólar paralelo",
    "dólar referencial", "itf ", "asfi", "medinacelli", "fitch ratings",
]

KEYWORDS_EXCLUIR = [
    "fútbol", "selección boliviana", "farándula", "masterchef", "novela ",
    "festival de cine", "orquesta sinfónica",
    "feminicidio", "asalto a mano armada", "accidente de tránsito", "choque fatal",
    "nasa ", "artemis", "astronaut",
    "sheinbaum", "elecciones en perú",
    "alerta epidemiológica", "viruela símica", "maltrato infantil",
    # Farándula/entretenimiento reforzado (calibración 2026-06-21)
    "reina de belleza", "certamen de belleza", "miss bolivia",
    # Contenido patrocinado / publicidad (excluir por marcadores de texto; la
    # exclusión por sección/URL se aplica aparte, vía es_url_patrocinada).
    "contenido de marca", "contenido patrocinado", "espacio publicitario",
    "espacio de marca", "publirreportaje", "branded content",
    # Color cultural / folklórico / ceremonial (WS5 funnel-v2): ruido sin ángulo
    # económico. CONSERVADOR: NO incluye carnaval, alasitas, ferias ni nada con
    # arista económica/turística — solo lo inequívocamente ceremonial.
    "año nuevo andino", "año nuevo aymara", "año nuevo amazónico", "solsticio",
    "ceremonia ancestral", "ritual ancestral", "fiesta patronal", "fiestas patronales",
    "entrada folklórica", "entrada folclórica", "danza folklórica", "danza folclórica",
]

# Rutas/secciones de contenido patrocinado a excluir por URL (decisión "ambas",
# calibración 2026-06-21: marcadores de texto arriba + sección/URL acá). Se aplica
# en la ingesta sobre c["link"] (evaluar() no recibe la URL).
SECCIONES_PATROCINADAS = (
    "/publicidad", "/publirreportaje", "/publireportaje", "/publinota",
    "/contenido-de-marca", "/contenido-patrocinado", "/patrocinado",
    "/branded", "/brand-studio", "/marcas/", "/espacio-publicitario",
)


def es_url_patrocinada(url: str) -> bool:
    """True si la URL cae en una sección de contenido patrocinado/publicidad."""
    u = (url or "").lower()
    return any(p in u for p in SECCIONES_PATROCINADAS)


# Opinión / columna / editorial (WS4 funnel-v2): NO se mata. El data layer le pone
# category='opinion' (categoría propia) y el ajuste editorial la penaliza ×0.7. Se
# detecta por sección de URL o por marcador en el título.
OPINION_URL_SECCIONES = (
    "/opinion/", "/opiniones/", "/opinion-y-analisis/",
    "/columna/", "/columnas/", "/columnistas/",
    "/editorial/", "/editoriales/",
)
_RE_OPINION_TIT = re.compile(
    r"\|\s*opini[oó]n\s*\|"            # ...| OPINIÓN |... (byline-marker pipe)
    r"|^\s*opini[oó]n\s*[:|\-–]"       # OPINIÓN: / OPINIÓN - al inicio
    r"|^\s*columna\s*[:|\-–]"          # COLUMNA: al inicio
    r"|^\s*editorial\s*[:|\-–]",       # EDITORIAL: al inicio
    re.IGNORECASE,
)


def es_opinion(titulo: str, url: str = "") -> bool:
    """True si la nota es opinión/columna/editorial (sección de URL o marcador de
    título). Conservador: solo marcadores inequívocos — NO infiere opinión por
    byline de nombre suelto (demasiado falso-positivo sobre nota dura)."""
    u = (url or "").lower()
    if any(s in u for s in OPINION_URL_SECCIONES):
        return True
    return bool(_RE_OPINION_TIT.search(titulo or ""))


TERMINOS_BOLIVIA = [
    "bolivia", "bolivian", "boliviano", "boliviana",
    "santa cruz", "la paz", "cochabamba", "sucre", "oruro", "potosí",
    "beni", "pando", "tarija", "el alto", "samaipata",
    "uyuni", "yacuiba", "quillacollo", "riberalta", "tupiza", "camiri",
    "llallagua", "villazón", "estado boliviano", "gobierno boliviano",
    "ypfb", "bcb", "mefp", "ofep", "central obrera", "ley 1720",
    # Gentilicios departamentales (WS2 funnel-v2). STEMS largos y no-ambiguos →
    # substring seguro (ningún término-host común los contiene). Los tokens cortos
    # o ambiguos (Bs, SIN, ABC, fisco) NO van acá: ver _ENTIDAD_SPEC (word-boundary).
    "paceñ", "cruceñ", "cochabambin", "orureñ", "potosin", "tarijeñ",
    "alteñ", "chuquisaqueñ", "beniano", "pandino",
]
PORTALES_EXIGEN_BOLIVIA = {"Bloomberg Línea", "Urgente.bo", "Opinión"}  # legacy: el carril vivo (evaluar) exige Bolivia a TODOS los portales; esto solo afecta el fallback keywords (muerto en prod)


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------
# ── Clasificación de tema v1 (FASE 3) — reglas contextuales word-boundary ──
# Reemplaza el conteo por substring del _tema viejo (`kw in texto`), que disparaba
# falsos positivos (recon: "deuda" metafórica → Deuda, "millones de dólares" →
# Dólar, "BCB" como lugar → Dólar). La nota YA pasó el corte de relevancia (modelo
# binario) + exclusiones (KEYWORDS_EXCLUIR); acá solo se elige el TEMA entre temas.
# Diseño: workflow de 3 enfoques + síntesis (ver PR). category vive en
# transform.TEMA_CATEGORIA (única fuente del mapa tema→category), no acá.

# Plegado de acentos (str.translate, stdlib): "dólar"→"dolar", una sola grafía por
# patrón. Todo el matching corre sobre texto plegado+lower+whitespace-colapsado.
_ACENTOS = str.maketrans("áàäéèëíìïóòöúùüñ", "aaaeeeiiiooouuun")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().translate(_ACENTOS)).strip()


def _wb(term: str):
    """Compila un trigger a patrón word-boundary vía lookaround sobre [0-9a-z]
    (el texto ya viene plegado a ASCII+lower). Evita 'ine' en 'define', 'oro' en
    'tesoro', 'cao' en 'caos'. Frases multipalabra: el lookaround rodea la frase.
    Para strong/weak/entidades (matching EXACTO; los plurales se listan aparte)."""
    return re.compile(r"(?<![0-9a-z])" + re.escape(_norm(term)) + r"(?![0-9a-z])")


def _pfx(term: str):
    """Patrón PREFIJO (leading boundary, SIN trailing): para los stems de contexto
    ('productor'→productores, 'ganader'→ganadería, 'cambiari'→cambiaria,
    'financ'→financiero). El contexto solo GATEA los weak (no suma score), así que
    su mayor permisividad es acotada. El leading boundary evita 'via' en 'lluvia'."""
    return re.compile(r"(?<![0-9a-z])" + re.escape(_norm(term)))


# Reglas por tema: strong (inequívoco, 1 basta) · weak (ambiguo, solo cuenta con
# contexto) · context (gatea los weak) · exclude (frase que VETA el tema; substring).
_TEMA_SPEC = {
    "Combustibles / YPFB": {
        "strong": ["ypfb", "diesel", "gasolina", "carburante", "surtidor", "gnv", "glp",
                   "hidrocarburo", "refineria", "gasolina plus", "medinacelli", "gasolinera",
                   "octanaje", "ducto", "desabastecimiento de combustible", "desabastecimiento de carburante"],
        "weak": ["combustible", "abastecimiento", "desabastecimiento", "petroleo", "cisterna",
                 "subvencion", "fila", "cola", "surtidores"],
        "context": ["combustible", "carburante", "gasolina", "diesel", "surtidor", "ypfb", "gnv",
                    "glp", "hidrocarburo", "fila", "cisterna", "subvencion", "litro"],
        "exclude": ["abastecimiento de agua", "abastecimiento de alimentos",
                    "desabastecimiento de alimentos", "desabastecimiento de medicamentos"],
    },
    "Tipo de cambio / Dólar": {
        "strong": ["tipo de cambio", "reservas internacionales", "dolar paralelo", "dolar referencial",
                   "dolar oficial", "mercado paralelo", "cotizacion del dolar", "brecha cambiaria",
                   "devaluacion", "casa de cambio", "casas de cambio", "asoban"],
        "weak": ["dolar", "dolares", "bcb", "banco central", "divisa", "divisas", "itf", "paralelo",
                 "euro", "tarjeta de credito", "tarjeta de debito"],
        "context": ["tipo de cambio", "cotizacion", "paralelo", "oficial", "reservas", "cambiari",
                    "devaluacion", "mercado negro", "brecha", "divisa", "casa de cambio", "apreciaci",
                    "deprecia", "blue", "bob", "boliviano"],
        "exclude": ["millones de dolares", "mil millones de dolares", "millon de dolares",
                    "de dolares en remesas", "de dolares en inversion", "de dolares en donacion",
                    "valorado en", "inversion de mas de", "donacion de", "financiamiento de",
                    "prestamo de", "credito de", "por un monto de", "presupuesto de",
                    "ambientes del bcb", "instalaciones del bcb", "sede del bcb", "predios del bcb",
                    "auditorio del bcb", "oficinas del bcb"],
                    # (quitado "en el bcb": vetaba strongs reales — "tipo de cambio en el BCB",
                    #  "reservas internacionales en el BCB"; los locativos de edificio ya cubren el evento)
    },
    "Litio / Minería": {
        "strong": ["litio", "ylb", "comibol", "salar de uyuni", "carbonato de litio",
                   "yacimientos de litio", "cobalto", "cooperativa minera", "explotacion minera", "mineria"],
        "weak": ["minero", "yacimiento", "zinc", "plata", "oro", "salar", "estano", "mina"],
        "context": ["mina", "minero", "mineria", "extraccion", "explotacion", "yacimiento", "litio",
                    "ylb", "comibol", "cooperativa", "onza", "tonelada", "reserva de mineral",
                    "exportacion de mineral", "cotizacion"],
        "exclude": ["medalla de oro", "oro olimpico", "edad de oro", "bodas de oro", "regla de oro",
                    "plan de oro", "oro negro", "gallina de los huevos", "plata para", "sin un peso",
                    "reglas de oro"],
    },
    "Agropecuario / Soya": {
        "strong": ["soya", "soja", "agroindustria", "agropecuaria", "anapo", "senasag", "agropecruz",
                   "carne bovina", "ganaderia", "zafra", "frigorifico", "biodiesel de soya",
                   "oleaginosa", "sorgo"],
        "weak": ["agro", "productores", "maiz", "trigo", "cosecha", "siembra", "bovino", "cao",
                 "cana", "arroz"],
        "context": ["soya", "soja", "cosecha", "siembra", "cultivo", "productor", "agro", "ganader",
                    "bovino", "exportacion", "hectarea", "campo", "rural", "agropecuari", "grano", "sequia"],
        "exclude": ["productores de cine", "productores musicales", "productores de television",
                    "cosecha de votos", "trigo limpio", "cao de "],
    },
    "Deuda / Finanzas": {
        "strong": ["deuda externa", "deuda interna", "deuda publica", "deuda soberana",
                   "servicio de la deuda", "servicio de deuda", "calificacion crediticia",
                   "deficit fiscal", "fitch", "moody", "standard and poor", "standard & poor",
                   "s&p", "fmi", "banco mundial",
                   "bono soberano", "bonos soberanos", "prestamo del fmi", "prestamo del bid",
                   "prestamo de la caf", "desembolso del bid", "desembolso de la caf",
                   "sistema financiero", "banca boliviana"],
        "weak": ["deuda", "credito", "creditos", "bono", "bonos", "prestamo", "prestamos",
                 "impuesto", "impuestos", "bid", "caf"],
        "context": ["fiscal", "externa", "interna", "publica", "soberan", "financ", "crediticia",
                    "desembolso", "millones", "intereses", "acreedor", "amortizacion", "calificacion",
                    "multilateral", "banca", "mercado de capitales", "bonos del tesoro"],
        "exclude": ["deuda social", "deuda pendiente", "deuda historica", "deuda educativa",
                    "deuda moral", "deuda de genero", "deuda ambiental", "deuda de gratitud",
                    # metáforas concretas (no el genérico "deuda con la", que vetaba deuda real:
                    # "deuda con la CAF/banca multilateral/China")
                    "deuda con la sociedad", "deuda con la patria", "deuda con la historia",
                    "deuda con el pueblo", "deuda con la naturaleza",
                    "deuda con vos", "deuda con uno", "tienen una deuda con",
                    "saldar una deuda", "credito a la educacion", "productores de cine"],
    },
    "Inflación / Precios": {
        "strong": ["inflacion", "canasta basica", "costo de vida", "indice de precios",
                   "encarecimiento", "carestia"],
        "weak": ["ipc", "precios", "ine", "alza de precios", "sube el precio"],
        "context": ["precio", "inflacion", "costo", "canasta", "encarec", "ipc", "ine", "consumidor",
                    "alza de precios", "sube el precio", "carestia", "mercado", "alimento"],
        "exclude": ["a cualquier precio", "sin precio", "precio justo electoral", "precio de la gloria"],
    },
    "Exportaciones / Comercio": {
        "strong": ["balanza comercial", "ibce", "cainco", "exportaciones bolivianas",
                   "importaciones bolivianas", "aduana nacional", "superavit comercial",
                   "deficit comercial", "comercio exterior"],
        "weak": ["exportacion", "exportaciones", "importacion", "importaciones", "aduana", "arancel",
                 "contrabando"],
        "context": ["exporta", "importa", "comercio", "balanza", "arancel", "aduana", "mercado externo",
                    "fob", "superavit", "deficit comercial", "contenedor", "frontera"],
        "exclude": ["comercio sexual", "comercio de personas", "aduana del cielo"],
    },
    "Inversión / Infraestructura": {
        "strong": ["obra publica", "licitacion", "contratacion directa", "ds 5600", "doble via",
                   "megaproyecto", "infraestructura vial", "inversion publica",
                   "inversion extranjera directa", "construccion de la carretera"],
        "weak": ["inversion", "carretera", "obra", "proyecto", "construccion", "puente", "contrato"],
        "context": ["construccion", "obra", "proyecto", "carretera", "puente", "millones", "financiar",
                    "ejecuta", "infraestructura", "planta", "tramo", "licitacion", "via", "megaproyecto"],
        "exclude": ["inversion de tiempo", "inversion emocional", "inversion de roles",
                    "inversion social", "invierte en ti"],
    },
    "Elecciones / Política económica": {
        "strong": ["segunda vuelta", "balotaje", "ministro de economia", "ministerio de economia",
                   "mefp", "rodrigo paz", "candidato presidencial", "binomio presidencial",
                   "papeleta electoral", "comicios", "elecciones generales"],
        "weak": ["tse", "ted", "candidato", "campana", "voto", "binomio", "papeleta"],
        "context": ["eleccion", "voto", "comicios", "candidat", "balotaje", "segunda vuelta", "binomio",
                    "tribunal electoral", "campana electoral", "urnas", "electoral"],
        "exclude": ["elecciones en peru", "elecciones en argentina", "elecciones en chile",
                    "eleccion del papa", "campana de vacunacion", "campana de salud",
                    "campana de limpieza", "balotaje deportivo", "segunda vuelta del partido"],
    },
    "Bloqueos / Conflictos": {
        "strong": ["bloqueo", "bloqueos", "paro indefinido", "corte de ruta", "corte de rutas",
                   "cierre de rutas", "corte de carretera", "puntos de bloqueo", "punto de bloqueo",
                   "paro civico", "huelga de hambre", "avasallamiento",
                   # Vocabulario de crisis política (calibración 2026-06-21): la cobertura
                   # de la crisis cae en Política, no en Otros/General.
                   "estado de excepcion", "estado de sitio", "toque de queda",
                   "comite multisectorial", "pacificacion del pais",
                   # Post-conflicto / reactivación (WS3 funnel-v2): la cobertura del
                   # desenlace de la crisis caía a General→Otros. Las FRASES específicas
                   # van como strong (1 basta); los stems ambiguos (reactivacion,
                   # reconstruccion, normalizacion) van como weak GATEADO por el contexto
                   # de conflicto de abajo, para NO mis-routear economía genérica.
                   "desbloqueo", "levantamiento del bloqueo", "levantamiento de los bloqueos",
                   "fin del paro", "fin de los bloqueos", "reanudacion del transito",
                   "transitabilidad", "reactivacion economica", "reconstruccion economica",
                   "reconstruccion del pais"],
        "weak": ["paro", "conflicto", "protesta", "marcha", "movilizacion", "huelga", "vigilia",
                 "choferes", "transportistas", "bloqueadores", "pacificacion",
                 "reactivacion", "reconstruccion", "normalizacion",
                 "brigada parlamentaria", "brigadas parlamentarias"],
        "context": ["ruta", "carretera", "via", "bloqueo", "paro", "protesta", "sector", "huelga",
                    "transportista", "gremial", "movilizad", "sindical", "conflicto", "camino",
                    "estado de excepcion", "central obrera", "pacificacion", "chofer",
                    "desbloqueo", "transitabilidad", "reanudacion", "normalizacion del abastecimiento",
                    "brigada parlamentaria", "post conflicto", "mesa de dialogo", "reactivacion economica",
                    "multisectorial", "decreto supremo"],
        "exclude": ["bloqueo mental", "bloqueo de tarjeta", "bloqueo de cuenta", "bloqueo de pantalla",
                    "sin bloqueo", "paro cardiaco", "paro respiratorio", "marcha atras",
                    "marcha de la noticia"],
    },
    "EMAPA / Alimentos": {
        "strong": ["emapa", "seguridad alimentaria", "soberania alimentaria", "ley 157",
                   "subvencion de alimentos", "subsidio alimentario"],
        "weak": ["alimentos", "abastecimiento de alimentos", "desabastecimiento de alimentos", "pan",
                 "azucar", "arroz", "aceite", "harina"],
        "context": ["emapa", "alimento", "subvencion", "subsidio", "arroz", "azucar", "harina", "pan",
                    "aceite", "seguridad alimentaria", "abastecimiento", "escasez"],
        "exclude": ["alimentos para el alma", "alimentos chatarra"],
    },
}

# Tie-break determinista ante empate de score (1º mayor strong_hits, 2º este orden).
# Temas-evento y de vocabulario concreto primero; Deuda y Dólar al fondo (los grandes
# generadores de falso positivo por "deuda"/"dolar"). Hace el resultado independiente
# del orden del dict y de la redacción del portal.
_PRIORIDAD = ["Bloqueos / Conflictos", "Combustibles / YPFB", "Litio / Minería",
              "Agropecuario / Soya", "EMAPA / Alimentos", "Elecciones / Política económica",
              "Inflación / Precios", "Exportaciones / Comercio", "Inversión / Infraestructura",
              "Deuda / Finanzas", "Tipo de cambio / Dólar"]
_PRIORIDAD_IDX = {t: i for i, t in enumerate(_PRIORIDAD)}

# Compilación una sola vez al cargar el módulo (no por nota).
_TEMA_RULES = {
    tema: {
        "strong": [_wb(t) for t in spec["strong"]],
        "weak": [_wb(t) for t in spec["weak"]],
        "context": [_pfx(t) for t in spec["context"]],   # prefijo: stems gatean weaks
        "exclude": [_norm(p) for p in spec["exclude"]],  # frases inequívocas: substring
    }
    for tema, spec in _TEMA_SPEC.items()
}

# Entidades (independiente del tema): canonical → patrones de alias. Se reportan
# SIEMPRE, aunque el tema sea General — BCB/Gobierno/MEFP son entidad válida sin
# disparar tema (resuelve "BCB como lugar" del recon).
_ENTIDAD_SPEC = {
    "BCB": ["bcb", "banco central de bolivia", "banco central"],
    "YPFB": ["ypfb", "yacimientos petroliferos fiscales bolivianos"],
    "ANH": ["anh", "agencia nacional de hidrocarburos"],
    "YLB": ["ylb", "yacimientos de litio bolivianos"],
    "COMIBOL": ["comibol", "corporacion minera de bolivia"],
    "FMI": ["fmi", "fondo monetario internacional"],
    "Banco Mundial": ["banco mundial", "bird"],
    "BID": ["bid", "banco interamericano de desarrollo"],
    "CAF": ["caf", "banco de desarrollo de america latina"],
    "Gobierno": ["gobierno", "poder ejecutivo", "ejecutivo nacional", "casa grande", "palacio quemado"],
    "ASFI": ["asfi", "autoridad de supervision del sistema financiero"],
    "ASOBAN": ["asoban", "asociacion de bancos privados"],
    "INE": ["ine", "instituto nacional de estadistica"],
    "Aduana": ["aduana", "aduana nacional"],
    "IBCE": ["ibce", "instituto boliviano de comercio exterior"],
    "CAINCO": ["cainco", "camara de industria comercio servicios y turismo"],
    "SENASAG": ["senasag"],
    "ANAPO": ["anapo", "asociacion de productores de oleaginosas"],
    "CAO": ["cao", "camara agropecuaria del oriente"],
    "EMAPA": ["emapa", "empresa de apoyo a la produccion de alimentos"],
    "COB": ["cob", "central obrera boliviana"],
    "MEFP": ["mefp", "ministerio de economia", "ministerio de economia y finanzas publicas",
             "ministro de economia"],
    "TSE": ["tse", "tribunal supremo electoral"],
    "TED": ["ted", "tribunal electoral departamental"],
    "Fitch": ["fitch", "fitch ratings"],
    "Moody's": ["moody", "moodys"],
    "S&P": ["standard and poor", "standard & poor", "standard & poors", "s&p"],
    # ── Ancla BO ampliada (WS2 funnel-v2) ──
    # Instituciones/figuras/moneda que anclan la nota en Bolivia aunque NO nombre el
    # país. TODO token corto o ambiguo entra SOLO por acá (word-boundary vía _wb),
    # NUNCA por TERMINOS_BOLIVIA (substring crudo), para no matchear "sin"→preposición,
    # "abc"→alfabeto/diario, "bs"→texto random. Por eso SIN/ABC se anclan por su nombre
    # completo (no por la sigla pelada), y "bs"/"fisco" van con boundary estricto.
    "Senasir": ["senasir"],
    "Gestora": ["gestora publica", "gestora publica de la seguridad social"],
    "ABC": ["administradora boliviana de carreteras"],
    "SIN": ["servicio de impuestos nacionales", "impuestos nacionales"],
    "Fisco": ["fisco"],
    "Bs": ["bs"],
    "Figuras BO": ["rodrigo paz", "doria medina", "edman lara", "edmand lara", "evo morales"],
}
_ENTIDADES = {canon: [_wb(a) for a in aliases] for canon, aliases in _ENTIDAD_SPEC.items()}

# Entidades cuya sola presencia ancla la nota en Bolivia (geo-gate universal).
# Excluye organismos internacionales (FMI, BM, BID, CAF, calificadoras): por sí
# solos no implican relevancia boliviana.
ENTIDADES_BOLIVIANAS = {
    "BCB", "YPFB", "ANH", "YLB", "COMIBOL", "Gobierno", "ASFI", "ASOBAN", "INE",
    "Aduana", "IBCE", "CAINCO", "SENASAG", "ANAPO", "CAO", "EMAPA", "COB", "MEFP",
    "TSE", "TED",
    # Ancla BO ampliada (WS2 funnel-v2): instituciones/figuras/moneda word-boundary.
    "Senasir", "Gestora", "ABC", "SIN", "Fisco", "Bs", "Figuras BO",
}
# Entidades que dan evidencia económica suficiente para CONSERVAR una nota "General"
# (sin tema). Excluye las puramente políticas/electorales (Gobierno, TSE, TED, COB).
ENTIDADES_ECONOMICAS = {
    "BCB", "YPFB", "ANH", "YLB", "COMIBOL", "ASFI", "ASOBAN", "INE", "Aduana",
    "IBCE", "CAINCO", "SENASAG", "ANAPO", "CAO", "EMAPA", "MEFP",
    "FMI", "Banco Mundial", "BID", "CAF", "Fitch", "Moody's", "S&P",
}


def detectar_entidades(titulo: str, descripcion: str = "") -> list:
    """Entidades canónicas presentes (word-boundary, independiente del tema)."""
    texto = _norm(titulo + " . " + descripcion)
    return sorted(canon for canon, pats in _ENTIDADES.items()
                  if any(p.search(texto) for p in pats))


def _tema(titulo: str, descripcion: str = "") -> tuple:
    """Devuelve (tema, confianza). confianza = strong*10 + weak-con-contexto del
    tema ganador (0 si General). Determinista e independiente del orden del dict.
    Gate aguas-abajo sugerido: imagen específica solo si confianza >= 10 (≥1 strong)."""
    texto = _norm(titulo + " . " + descripcion)
    mejor = None  # (score, strong, -prioridad_idx, tema)
    for tema, rule in _TEMA_RULES.items():
        if any(ph in texto for ph in rule["exclude"]):
            continue
        strong = sum(1 for p in rule["strong"] if p.search(texto))
        tiene_ctx = any(p.search(texto) for p in rule["context"])
        weak = sum(1 for p in rule["weak"] if p.search(texto)) if tiene_ctx else 0
        score = strong * 10 + weak
        if score <= 0:
            continue
        cand = (score, strong, -_PRIORIDAD_IDX[tema], tema)
        if mejor is None or cand > mejor:
            mejor = cand
    if mejor is None:
        return "General", 0
    return mejor[3], mejor[0]


def score_keywords(titulo: str, descripcion: str, portal: str) -> tuple:
    """FALLBACK sin modelo TF-IDF — MUERTO en prod (ingest es fail-closed y aborta
    el carril Bolivia sin modelo). Se conserva por el port de boletines. Relevancia
    por conteo de KEYWORDS (legacy); el TEMA y la confianza salen de _tema.
    Devuelve (puntaje_int, tema, confianza)."""
    texto = (titulo + " " + descripcion).lower()
    for excl in KEYWORDS_EXCLUIR:
        if excl in texto:
            return 0, "", 0
    if portal in PORTALES_EXIGEN_BOLIVIA:
        if not any(t in texto for t in TERMINOS_BOLIVIA):
            return 0, "", 0
    tema, conf = _tema(titulo, descripcion)
    for kw in KEYWORDS_FORZADO:
        if kw in texto:
            return 10, tema, conf
    mejor = max((sum(1 for kw in kws if kw in texto) for kws in KEYWORDS.values()), default=0)
    return mejor, tema, conf


def evaluar(titulo: str, descripcion: str, portal: str, es_opinion: bool = False) -> tuple:
    """
    Devuelve (puntaje, tema, tema_hits, entidades, score_crudo, score_ajustado,
              ajuste_aplicado, descartado_por).
    - puntaje: float 0-10 (1 decimal) de RELEVANCIA (modelo TF-IDF). 0 = descartar.
    - tema_hits: int de CONFIANZA del tema (strong*10 + weak-con-contexto; ≠ puntaje).
    - entidades: list[str] de entidades canónicas detectadas (independiente del tema).
    - score_crudo / score_ajustado: floats 0-1 (None si no hubo modelo).
    - ajuste_aplicado: string descriptivo ("—" si no hubo).
    - descartado_por: "" si pasa, o uno de: "keyword_excluida", "falta_bolivia", "umbral".
    """
    # Siempre aplicar exclusiones básicas primero
    texto = (titulo + " " + descripcion).lower()
    for excl in KEYWORDS_EXCLUIR:
        if excl in texto:
            return 0, "", 0, [], None, None, "—", "keyword_excluida"
    # Entidades + tema se computan ANTES del geo-gate (WS1 funnel-v2): el gate ahora
    # rescata por tema, así que necesita la clasificación en el punto de decisión.
    entidades = detectar_entidades(titulo, descripcion)
    tema, tema_hits = _tema(titulo, descripcion)
    # Geo-gate funnel-v2 (WS1): PASA si ANCLA en Bolivia (término geográfico/adjetivo o
    # entidad boliviana — la lógica del gate viejo) OR si clasifica en un tema económico
    # (no-General). Rescata economía boliviana legítima que NO nombra el país (ej. real:
    # "el dólar referencial baja a Bs 9,92" → tema Dólar). El set que pasa CONTIENE al del
    # gate viejo (solo agrega rescates por tema; cero pérdida de recall vs hoy). El ruido
    # internacional sin ancla NI tema lo siguen conteniendo el umbral editorial 6.7 + el
    # budget top-N (decisión cerrada: sin veto internacional en v1). "General" anclado NO
    # se descarta: entra como 'otros' (relleno por relevancia, ver transform.py).
    ancla_bo = (any(t in texto for t in TERMINOS_BOLIVIA)
                or any(e in ENTIDADES_BOLIVIANAS for e in entidades))
    if not (ancla_bo or tema != "General"):
        return 0, "", 0, [], None, None, "—", "falta_bolivia"

    # Intentar modelo TF-IDF
    prob_crudo = get_modelo().puntaje(titulo, descripcion)
    if prob_crudo >= 0:
        # Ajustar score con reglas editoriales
        prob_ajustado = ajustar_score(prob_crudo, titulo, descripcion, portal, es_opinion)
        ajuste = detectar_ajuste(titulo, descripcion, portal, es_opinion)
        # Modelo disponible
        if prob_ajustado < UMBRAL_MODELO:
            return 0, "", 0, [], round(prob_crudo, 4), round(prob_ajustado, 4), ajuste, "umbral"
        # tema / tema_hits ya computados arriba (no recomputar).
        return (round(prob_ajustado * 10, 1), tema, tema_hits, entidades,
                round(prob_crudo, 4), round(prob_ajustado, 4), ajuste, "")

    # Fallback keywords (path muerto en prod por fail-closed)
    puntaje, tema_fb, tema_hits_fb = score_keywords(titulo, descripcion, portal)
    return puntaje, tema_fb, tema_hits_fb, entidades, None, None, "—", ""


# ---------------------------------------------------------------------------
# AJUSTE DE SCORE
# ---------------------------------------------------------------------------
_RE_DEPORTES = re.compile(
    r"champions|gol\b|derrotó|venció|liga\b|copa libertadores"
    r"|eliminatorias|baloncesto|fútbol|futbol", re.IGNORECASE
)
_RE_CRIMEN = re.compile(
    r"aprehendida|aprehendido|asesinato|feminicidio|atracos"
    r"|robo de droga|operativo policial|homicidio", re.IGNORECASE
)
_RE_CHISME = re.compile(
    r"responde a|arremete contra"
    r"|denuncia violencia política|reclama su pasaporte", re.IGNORECASE
)
_RE_CONTRABANDO_ALIM = re.compile(
    r"contrabando de\s+(arroz|fideo|harina|azúcar|huevos)", re.IGNORECASE
)
_RE_MARIHUANA = re.compile(r"marihuana|cannabis", re.IGNORECASE)
_RE_INTL = re.compile(r"luna|marte|champions|\bonu\b", re.IGNORECASE)
_RE_BOLIVIA = re.compile(
    r"bolivi|ypfb|bcb|mefp|asfi|emapa|ylb|ana?po|cainco"
    r"|la paz|santa cruz|cochabamba|tarija|oruro|potosí|beni|pando|sucre",
    re.IGNORECASE
)
_RE_INSTIT = re.compile(
    r"expocruz|agropecruz|exposoya|fexco|rueda de negocios"
    r"|cainco|cao|anapo|ibce|cepb|cnc|conamype|confeagro"
    r"|congabol|fegasacruz|caneb|caboco",
    re.IGNORECASE
)
_RE_FX = re.compile(
    r"dólar paralelo|brecha de divisas|reservas internacionales"
    r"|tipo de cambio|cotización del dólar|mercado paralelo",
    re.IGNORECASE
)


_BONUS_PORTAL = {"El Deber": 1.15, "Correo del Sur": 1.10, "La Razón": 1.10}


def ajustar_score(score: float, titulo: str, descripcion: str, portal: str = "",
                  es_opinion: bool = False) -> float:
    """Ajusta el score del modelo con reglas editoriales."""
    texto = (titulo + " " + descripcion).lower()
    tit = titulo.lower()

    # Penalización fuerte (x0.3)
    if _RE_DEPORTES.search(texto):
        return score * 0.3
    if _RE_CRIMEN.search(texto):
        return score * 0.3
    if _RE_CHISME.search(tit):
        return score * 0.3

    # Penalización media (x0.5)
    if _RE_CONTRABANDO_ALIM.search(texto):
        return score * 0.5
    if _RE_MARIHUANA.search(texto):
        return score * 0.5
    if _RE_INTL.search(texto) and not _RE_BOLIVIA.search(texto):
        return score * 0.5

    # Penalización opinión (x0.7, WS4 funnel-v2): columna/editorial NO se mata
    # (lleva category='opinion' propia en transform), pero se penaliza y NO recibe
    # los bonos de portal/FX/instituciones (early-return antes de la bonificación).
    if es_opinion:
        return score * 0.7

    # Bonificación instituciones (x1.3, max 1.0)
    menciones = set(m.group().lower() for m in _RE_INSTIT.finditer(texto))
    if len(menciones) >= 2:
        score = min(score * 1.3, 1.0)

    # Bonus FX/divisas (x1.2, max 1.0)
    if _RE_FX.search(texto):
        score = min(score * 1.2, 1.0)

    # Bonus por portal principal
    bonus = _BONUS_PORTAL.get(portal, 1.0)
    if bonus > 1.0:
        score = min(score * bonus, 1.0)

    return score


def detectar_ajuste(titulo: str, descripcion: str, portal: str,
                    es_opinion: bool = False) -> str:
    """Devuelve string descriptivo de qué reglas de ajustar_score se dispararon."""
    texto = (titulo + " " + descripcion).lower()
    tit = titulo.lower()
    if _RE_DEPORTES.search(texto):
        return "×0.3 deportes"
    if _RE_CRIMEN.search(texto):
        return "×0.3 crimen"
    if _RE_CHISME.search(tit):
        return "×0.3 chisme"
    if _RE_CONTRABANDO_ALIM.search(texto):
        return "×0.5 contrabando alim."
    if _RE_MARIHUANA.search(texto):
        return "×0.5 marihuana"
    if _RE_INTL.search(texto) and not _RE_BOLIVIA.search(texto):
        return "×0.5 intl sin Bolivia"
    if es_opinion:
        return "×0.7 opinión"
    partes = []
    menciones = set(m.group().lower() for m in _RE_INSTIT.finditer(texto))
    if len(menciones) >= 2:
        partes.append("×1.3 instituciones")
    if _RE_FX.search(texto):
        partes.append("×1.2 fx")
    bonus = _BONUS_PORTAL.get(portal, 1.0)
    if bonus > 1.0:
        partes.append(f"×{bonus} portal")
    return ", ".join(partes) if partes else "—"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def get_url(url: str, metodo: str = "requests", timeout: int = 10):
    try:
        if metodo == "cloudscraper" and TIENE_CLOUDSCRAPER:
            s = cloudscraper.create_scraper()
            r = s.get(url, timeout=timeout)
            return r if r.status_code == 200 else None
        elif metodo == "curl_cffi" and TIENE_CURL_CFFI:
            r = curl_requests.get(url, impersonate="chrome120", timeout=timeout)
            return r if r.status_code == 200 else None
        else:
            r = requests.get(url, timeout=timeout, headers=HEADERS)
            return r if r.status_code == 200 else None
    except Exception:
        try:
            r = requests.get(url, timeout=timeout, headers=HEADERS)
            return r if r.status_code == 200 else None
        except Exception:
            return None


def _og_image(html: str, base_url: str) -> str:
    """URL del og:image del <head> del HTML crudo. Fallbacks en orden:
    og:image → og:image:secure_url → twitter:image (cada uno como `property`
    o `name`, porque hay portales malformados). Resuelve relativas y
    protocol-relative contra base_url → siempre absoluta o ''. '' si no hay
    (p.ej. El Deber no baja HTML → '' → image_url NULL aguas abajo). Nunca
    levanta: cualquier excepción de parseo cae a ''. Carril Bolivia, FASE 2a."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for key in ("og:image", "og:image:secure_url", "twitter:image"):
            tag = (soup.find("meta", attrs={"property": key})
                   or soup.find("meta", attrs={"name": key}))
            if tag and (tag.get("content") or "").strip():
                return urljoin(base_url, tag["content"].strip())
    except Exception:
        return ""
    return ""


def scrape_cuerpo(url: str, metodo: str = "requests", timeout: int = TIMEOUT_URL_CUERPO) -> tuple[str, str]:
    """Fallback chain: curl_cffi → trafilatura.fetch_url → cloudscraper.
    Los 3 fallbacks comparten un budget total de `timeout` segundos.

    Devuelve (cuerpo, image_url): el og:image se parsea del HTML CRUDO en el
    branch que retorna cuerpo, ANTES de que trafilatura.extract descarte el
    <head>. image_url='' si el portal no expone og:image o no bajó HTML."""
    if not TIENE_TRAFILATURA:
        return "", ""

    deadline = time.time() + timeout

    # 1. curl_cffi + trafilatura.extract
    restante = deadline - time.time()
    if restante > 0 and TIENE_CURL_CFFI:
        try:
            r = curl_requests.get(url, impersonate="chrome120", timeout=min(restante, 10))
            if r.status_code == 307:
                return "", ""  # Sucuri WAF — nunca devuelve contenido útil
            if r.status_code == 200:
                txt = trafilatura.extract(r.text, include_comments=False, include_tables=False)
                # Si curl_cffi obtuvo 200, no caer a fallbacks (evita redirect loops)
                return (txt or "")[:10000], _og_image(r.text, url)
        except Exception:
            pass

    # 2. trafilatura.fetch_url
    restante = deadline - time.time()
    if restante > 2:
        try:
            _traf_cfg = trafilatura.settings.use_config()
            _traf_cfg.set("DEFAULT", "download_timeout", str(int(min(restante, 10))))
            html = trafilatura.fetch_url(url, config=_traf_cfg)
            if html:
                txt = trafilatura.extract(html, include_comments=False, include_tables=False)
                if txt and len(txt) > 100:
                    return txt[:10000], _og_image(html, url)
        except Exception:
            pass

    # 3. cloudscraper + trafilatura.extract
    restante = deadline - time.time()
    if restante > 2 and TIENE_CLOUDSCRAPER:
        try:
            s = cloudscraper.create_scraper()
            r = s.get(url, timeout=min(restante, 10))
            if r.status_code == 200:
                txt = trafilatura.extract(r.text, include_comments=False, include_tables=False)
                if txt and len(txt) > 100:
                    return txt[:10000], _og_image(r.text, url)
        except Exception:
            pass

    return "", ""


def limpiar_html(txt: str) -> str:
    if not txt:
        return ""
    t = re.sub(r"<[^>]+>", " ", txt)
    t = re.sub(r"&#\d+;|&\w+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def es_reciente(fecha_parsed) -> bool:
    if not fecha_parsed:
        return True
    try:
        dt = datetime(*fecha_parsed[:6], tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(hours=HORAS_ATRAS)
    except Exception:
        return True


def _epoch_url(link: str):
    """Unix timestamp embebido como sufijo _<epoch> en URLs de artículo de El Deber
    (validado contra JSON-LD datePublished, delta 0-13 min). None si la URL no tiene
    el patrón — lo que además descarta chrome y paginadores (/pais/2, /pais/3)."""
    m = re.search(r"_(\d{9,})$", link)
    return int(m.group(1)) if m else None


def fetch_rss(fuente: dict) -> list:
    all_entries = []
    for url in fuente.get("rss", []):
        try:
            r = get_url(url, metodo=fuente.get("metodo", "requests"))
            if r:
                feed = feedparser.parse(r.content)
                if feed.entries:
                    all_entries.extend(feed.entries)
        except Exception:
            continue
    return all_entries


def scrape_titulos(fuente: dict) -> list:
    metodo = fuente.get("metodo", "requests")
    # scrape_paginas=1 (default) => comportamiento histórico: corta tras la 1ª URL con datos.
    # >1 => acumula esa cantidad de URLs (p.ej. paginación page/N/), deduplicando por URL.
    max_paginas = fuente.get("scrape_paginas", 1)
    resultados = []
    vistos = set()
    paginas_con_datos = 0
    for url in fuente.get("scrape_urls", []):
        r = get_url(url, metodo=metodo)
        if not r:
            continue
        try:
            soup = BeautifulSoup(r.content, "html.parser")
            antes = len(resultados)
            for a in soup.select(fuente.get("scrape_selector", "h2 a, h3 a")):
                titulo = a.get_text(strip=True)
                href = a.get("href", "")
                if not titulo or not href or len(titulo) < 15:
                    continue
                if not href.startswith("http"):
                    href = urljoin(url, href)
                if href not in vistos:  # dedupe por URL exacta (páginas solapan el destacado)
                    vistos.add(href)
                    resultados.append({"titulo": titulo, "link": href, "descripcion": ""})
            if len(resultados) > antes:
                paginas_con_datos += 1
                if paginas_con_datos >= max_paginas:
                    break
        except Exception:
            continue
    return resultados[:40 * max_paginas]


# ---------------------------------------------------------------------------
# DEDUPLICACIÓN (intra-corrida; la inter-día contra la tabla noticias la hace
# ingest_noticias.py con la misma función similitud())
# ---------------------------------------------------------------------------
UMBRAL_DEDUP = 0.70 if TIENE_RAPIDFUZZ else 0.55

# Regex para limpiar sufijos de portal antes de comparar títulos
_SUFIJOS_PORTAL = re.compile(
    r"\s*[-–—|]\s*("
    + "|".join(re.escape(f["portal"]) for f in FUENTES)
    + r"|ANF Agencia de Noticias Fides Bolivia|Bolivia"
    r")\s*$",
    re.IGNORECASE,
)


def _titulo_limpio(titulo: str) -> str:
    """Quita sufijos de portal para comparación de similitud."""
    limpio = _SUFIJOS_PORTAL.sub("", titulo)
    # Aplicar dos veces para "- El Diario - Bolivia"
    limpio = _SUFIJOS_PORTAL.sub("", limpio)
    return limpio.strip()


def similitud(t1: str, t2: str) -> float:
    if TIENE_RAPIDFUZZ:
        return fuzz.token_sort_ratio(t1, t2) / 100.0
    w1 = set(t1.lower().split())
    w2 = set(t2.lower().split())
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / max(len(w1), len(w2))


def deduplicar(noticias: list) -> list:
    # Pre-calcular títulos limpios para comparación
    titulos_limpios = [_titulo_limpio(n["titulo"]) for n in noticias]

    grupos = []
    usados = set()
    for i, n in enumerate(noticias):
        if i in usados:
            continue
        grupo = [n]
        usados.add(i)
        for j, m in enumerate(noticias):
            if j <= i or j in usados:
                continue
            if similitud(titulos_limpios[i], titulos_limpios[j]) >= UMBRAL_DEDUP:
                grupo.append(m)
                usados.add(j)
        # Elegir principal: mejor puntaje, desempate por cuerpo más largo
        principal = max(grupo, key=lambda x: (x["puntaje"], len(x.get("cuerpo", ""))))
        portales = [{"nombre": principal["portal"], "url": principal["link"]}]
        for p in grupo:
            if p is not principal and p["portal"] not in [x["nombre"] for x in portales]:
                portales.append({"nombre": p["portal"], "url": p["link"]})
        principal["portales_lista"] = portales
        grupos.append(principal)
    return grupos


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------
def procesar_portal(fuente: dict) -> tuple:
    portal = fuente["portal"]
    filtro = fuente.get("filtro_url")
    items_raw = []
    entries = fetch_rss(fuente)
    if entries:
        recientes = [e for e in entries if es_reciente(getattr(e, "published_parsed", None))]
        for entry in recientes:
            titulo = limpiar_html(getattr(entry, "title", ""))
            desc = limpiar_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
            link = getattr(entry, "link", "")
            if titulo and link:
                if filtro and filtro not in link:
                    continue
                items_raw.append({"titulo": titulo, "descripcion": desc, "link": link})
    if not items_raw:
        items_raw = scrape_titulos(fuente)
        if filtro:
            items_raw = [i for i in items_raw if filtro in i["link"]]
    # Scrape complementario: corre SIEMPRE (además de RSS o fallback) para secciones
    # cuya ventana RSS queda corta frente a HORAS_ATRAS. Solo acepta URLs con sufijo
    # _<epoch> dentro de la ventana: filtra notas viejas (el listado no trae fechas)
    # y descarta chrome del sitio en un solo paso.
    comp = fuente.get("scrape_complemento")
    if comp:
        corte = datetime.now(timezone.utc) - timedelta(hours=HORAS_ATRAS)
        vistos = {i["link"] for i in items_raw}
        for item in scrape_titulos({**fuente, "scrape_urls": comp, "scrape_paginas": len(comp)}):
            if filtro and filtro not in item["link"]:
                continue
            epoch = _epoch_url(item["link"])
            if epoch is None or item["link"] in vistos:
                continue
            try:
                if datetime.fromtimestamp(epoch, tz=timezone.utc) < corte:
                    continue
            except (OverflowError, OSError, ValueError):
                continue
            vistos.add(item["link"])
            items_raw.append(item)
    return portal, items_raw, bool(items_raw)


# ⓘ pipeline-anchor: este return es el SEAM que replica tools/noticias-inspector (etapas
#   1-8 del funnel Bolivia). Si cambiás el orden/etapas del pipeline o el contrato del dict
#   candidato, actualizá el inspector (inspector_core.py + pipeline_map.py + SYNC.md).
def correr_scraper(cache_db_path: Path = CACHE_DB_PATH) -> tuple:
    """Corre el pipeline completo: scrape 13 portales → score → dedupe
    intra-corrida → resolución Google News → cuerpos.

    Devuelve (candidatos, descartados, portales_ok, portales_fail).
    Candidatos ordenados por puntaje desc; cada uno con cuerpo (si se pudo)
    y portales_lista (réplicas del mismo título en otros portales).
    """
    modelo = get_modelo()
    if modelo.disponible:
        modo = f"TF-IDF (umbral={UMBRAL_MODELO})"
    elif modelo.motivo_rechazo:
        modo = f"Keywords (modelo existe pero descartado: {modelo.motivo_rechazo})"
    else:
        modo = "Keywords (no hay modelo)"
    log.info(f"  Modo filtrado: {modo}")

    cache = CacheURLs(cache_db_path, CACHE_DIAS)
    orden_portal = {f["portal"]: i for i, f in enumerate(FUENTES)}

    todas = []
    descartados = []
    portales_ok = []
    portales_fail = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(procesar_portal, f): f for f in FUENTES}
        for future in as_completed(futures):
            fuente = futures[future]
            portal = fuente["portal"]
            try:
                portal, items_raw, ok = future.result(timeout=90)
            except Exception as e:
                log.error(f"[ERROR] {portal}: {e}")
                portales_fail.append(portal)
                continue

            if not ok:
                log.info(f"  [FAIL] {portal}")
                portales_fail.append(portal)
                continue

            encontrados = 0
            for item in items_raw:
                if cache.ya_vista(item["link"]):
                    continue
                # Opinión/columna/editorial (WS4): se detecta acá porque la URL
                # (item["link"]) vive en el loop, no en evaluar(). Penaliza ×0.7 el
                # score y marca la nota para category='opinion' en transform.build_nota.
                es_op = es_opinion(item["titulo"], item["link"])
                (puntaje, tema, tema_hits, entidades, sc_crudo, sc_ajustado,
                 ajuste, descartado_por) = evaluar(
                    item["titulo"], item["descripcion"], portal, es_opinion=es_op)
                if puntaje == 0:
                    if descartado_por:
                        descartados.append({
                            "puntaje": 0, "tema": "", "portal": portal,
                            "titulo": item["titulo"], "descripcion": item["descripcion"],
                            "link": item["link"], "cuerpo": "", "portales_extra": "",
                            "score_crudo": sc_crudo, "score_ajustado": sc_ajustado,
                            "ajuste_aplicado": ajuste, "descartado_por": descartado_por,
                        })
                    continue
                todas.append({
                    "puntaje": puntaje, "tema": tema, "tema_hits": tema_hits,
                    "entidades": entidades, "portal": portal,
                    "titulo": item["titulo"], "descripcion": item["descripcion"],
                    "link": item["link"], "cuerpo": "",
                    "portales_lista": [{"nombre": portal, "url": item["link"]}],
                    "score_crudo": sc_crudo, "score_ajustado": sc_ajustado,
                    "ajuste_aplicado": ajuste, "es_opinion": es_op,
                })
                encontrados += 1

            log.info(f"  [OK]   {portal}  — {encontrados} candidatos")
            portales_ok.append(portal)

    todas.sort(key=lambda x: (orden_portal.get(x["portal"], 99), -x["puntaje"]))

    log.info(f"  Deduplicando {len(todas)} candidatos...")
    deduplicadas = deduplicar(todas)
    deduplicadas.sort(key=lambda x: (-x["puntaje"], orden_portal.get(x["portal"], 99)))

    # Resolver URLs de Google News antes de scrapear cuerpos
    if TIENE_GNEWS_DECODER:
        gnews_count = 0
        for n in deduplicadas:
            if n["link"].startswith("https://news.google.com/rss/articles/"):
                try:
                    result = new_decoderv1(n["link"])
                    if result.get("status") and result.get("decoded_url"):
                        n["link"] = result["decoded_url"]
                        gnews_count += 1
                except Exception:
                    pass
        if gnews_count:
            log.info(f"  Google News: {gnews_count} URLs decodificadas a URL real")

    total_cuerpos = len(deduplicadas)
    log.info(f"  Scrapeando cuerpo de {total_cuerpos} noticias únicas...")

    # Timeout acumulado por portal en fase de cuerpos, medido desde el primer
    # item procesado de cada portal (el pool comparte 6 workers entre portales).
    portal_cuerpos_inicio = {}
    portales_abortados = set()

    def scrape_item(n):
        portal = n["portal"]
        if portal not in portal_cuerpos_inicio:
            portal_cuerpos_inicio[portal] = time.time()
        elif time.time() - portal_cuerpos_inicio[portal] > TIMEOUT_PORTAL_CUERPOS:
            portales_abortados.add(portal)
            log.warning(f"  [ABORT] {portal}: >{TIMEOUT_PORTAL_CUERPOS}s en fase cuerpos, "
                        f"skipped: {n['link'][:80]}")
            return n
        fuente_src = next((f for f in FUENTES if f["portal"] == portal), {})
        t0 = time.time()
        n["cuerpo"], n["image_url"] = scrape_cuerpo(n["link"], metodo=fuente_src.get("metodo", "requests"))
        dt = time.time() - t0
        if not n["cuerpo"]:
            log.warning(f"  [SIN CUERPO] {n['link'][:80]} ({dt:.1f}s)")
        return n

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scrape_item, n): n for n in deduplicadas}
        for future in as_completed(futures):
            future.result()

    # NO se marca acá: el marcado lo hace el caller (ingest_noticias) vía
    # marcar_urls_vistas(), que solo marca insertadas + no-calificadas. Marcar
    # TODO lo evaluado acá era el bug de yield (las que perdían el top-N
    # quedaban vistas y no se reconsideraban). La caché se usó arriba SOLO para
    # leer (ya_vista) y saltar el re-scrapeo de cuerpos de URLs ya marcadas.
    cache.close()

    log.info(f"  {len(deduplicadas)} candidatos únicos "
             f"({len(portales_ok)} portales ok, {len(portales_fail)} fail)")
    return deduplicadas, descartados, portales_ok, portales_fail
