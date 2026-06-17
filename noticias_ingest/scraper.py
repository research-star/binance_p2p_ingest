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
]


# ---------------------------------------------------------------------------
# KEYWORDS (fallback si no hay modelo; KEYWORDS además clasifica el tema)
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
]

TERMINOS_BOLIVIA = [
    "bolivia", "bolivian", "boliviano", "boliviana",
    "santa cruz", "la paz", "cochabamba", "sucre", "oruro", "potosí",
    "beni", "pando", "tarija", "el alto", "samaipata",
    "ypfb", "bcb", "mefp", "ofep", "central obrera", "ley 1720",
]
PORTALES_EXIGEN_BOLIVIA = {"Bloomberg Línea", "Urgente.bo", "Opinión"}


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------
def score_keywords(titulo: str, descripcion: str, portal: str) -> tuple:
    """Fallback: devuelve (puntaje_int, tema_str)."""
    texto = (titulo + " " + descripcion).lower()
    for excl in KEYWORDS_EXCLUIR:
        if excl in texto:
            return 0, ""
    if portal in PORTALES_EXIGEN_BOLIVIA:
        if not any(t in texto for t in TERMINOS_BOLIVIA):
            return 0, ""
    for kw in KEYWORDS_FORZADO:
        if kw in texto:
            return 10, _tema(texto)
    mejor = 0
    mejor_t = "General"
    for tema, kws in KEYWORDS.items():
        m = sum(1 for kw in kws if kw in texto)
        if m > mejor:
            mejor = m
            mejor_t = tema
    return mejor, mejor_t


def _tema(texto: str) -> str:
    mejor = 0
    mejor_t = "General"
    for tema, kws in KEYWORDS.items():
        m = sum(1 for kw in kws if kw in texto)
        if m > mejor:
            mejor = m
            mejor_t = tema
    return mejor_t


def evaluar(titulo: str, descripcion: str, portal: str) -> tuple:
    """
    Devuelve (puntaje, tema, score_crudo, score_ajustado, ajuste_aplicado, descartado_por).
    - puntaje: float 0-10 (1 decimal). 0 = descartar.
    - score_crudo / score_ajustado: floats 0-1 (None si no hubo modelo).
    - ajuste_aplicado: string descriptivo ("—" si no hubo).
    - descartado_por: "" si pasa, o uno de: "keyword_excluida", "falta_bolivia", "umbral".
    """
    # Siempre aplicar exclusiones básicas primero
    texto = (titulo + " " + descripcion).lower()
    for excl in KEYWORDS_EXCLUIR:
        if excl in texto:
            return 0, "", None, None, "—", "keyword_excluida"
    if portal in PORTALES_EXIGEN_BOLIVIA:
        if not any(t in texto for t in TERMINOS_BOLIVIA):
            return 0, "", None, None, "—", "falta_bolivia"

    # Intentar modelo TF-IDF
    prob_crudo = get_modelo().puntaje(titulo, descripcion)
    if prob_crudo >= 0:
        # Ajustar score con reglas editoriales
        prob_ajustado = ajustar_score(prob_crudo, titulo, descripcion, portal)
        ajuste = detectar_ajuste(titulo, descripcion, portal)
        # Modelo disponible
        if prob_ajustado < UMBRAL_MODELO:
            return 0, "", round(prob_crudo, 4), round(prob_ajustado, 4), ajuste, "umbral"
        return (round(prob_ajustado * 10, 1), _tema(texto),
                round(prob_crudo, 4), round(prob_ajustado, 4), ajuste, "")

    # Fallback keywords
    puntaje, tema = score_keywords(titulo, descripcion, portal)
    return puntaje, tema, None, None, "—", ""


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


def ajustar_score(score: float, titulo: str, descripcion: str, portal: str = "") -> float:
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


def detectar_ajuste(titulo: str, descripcion: str, portal: str) -> str:
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
                puntaje, tema, sc_crudo, sc_ajustado, ajuste, descartado_por = evaluar(
                    item["titulo"], item["descripcion"], portal)
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
                    "puntaje": puntaje, "tema": tema, "portal": portal,
                    "titulo": item["titulo"], "descripcion": item["descripcion"],
                    "link": item["link"], "cuerpo": "",
                    "portales_lista": [{"nombre": portal, "url": item["link"]}],
                    "score_crudo": sc_crudo, "score_ajustado": sc_ajustado,
                    "ajuste_aplicado": ajuste,
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

    for n in deduplicadas:
        cache.marcar(n["link"], n["portal"])
    cache.close()

    log.info(f"  {len(deduplicadas)} candidatos únicos "
             f"({len(portales_ok)} portales ok, {len(portales_fail)} fail)")
    return deduplicadas, descartados, portales_ok, portales_fail
