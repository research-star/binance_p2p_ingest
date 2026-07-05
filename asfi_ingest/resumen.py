"""resumen.py — One-liner IA (Haiku) por item del Reporte Informativo ASFI.

Mismo contrato de seguridad que noticias_ingest/resumen_ia.py (candado +
cap), con presupuesto SEPARADO para no comerse el cap de noticias:

  - Candado `autorizado=True`: cubre la INTENCIÓN. Autorizado por Diego en el
    brief del módulo ASFI (sesión 2026-07-05, elección explícita "Extracción +
    resumen IA (Haiku)").
  - Cap mensual propio en tabla `asfi_api_spend` (misma DDL-shape que
    api_spend): cubre el ACCIDENTE. Default $1/mes; overridable con
    ASFI_RESUMEN_CAP_USD (p.ej. para el backfill de 122 días, ~$2-3 one-shot).
  - FAIL-CLOSED sin conn o tabla ilegible → no hay POST, el item queda con
    resumen extractivo (origen='extractivo', asterisco en el frontend — misma
    taxonomía A/B que noticias).

Activación en el VPS: ANTHROPIC_API_KEY en el entorno (ya presente para
noticias). ASFI_RESUMEN=0 lo apaga sin tocar noticias.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
MODELO_DEFAULT = "claude-haiku-4-5-20251001"
TIMEOUT_S = 20
MAX_TOKENS = 120
RESUMEN_MAX_CHARS = 200
TEXTO_MAX = 6000  # los items ASFI son cortos; las tablas largas se truncan

CAP_USD_MENSUAL_DEFAULT = 1.00
PRECIO_IN_USD_MTOK = 1.00   # Haiku 4.5 (catálogo SDK 2026-06)
PRECIO_OUT_USD_MTOK = 5.00

SPEND_DDL = (
    "CREATE TABLE IF NOT EXISTS asfi_api_spend ("
    " mes TEXT PRIMARY KEY,"
    " est_usd REAL NOT NULL DEFAULT 0,"
    " llamadas INTEGER NOT NULL DEFAULT 0,"
    " in_tokens INTEGER NOT NULL DEFAULT 0,"
    " out_tokens INTEGER NOT NULL DEFAULT 0)"
)

TRANSITORIO = object()  # fallo reintentable (red/HTTP) — ver resumen_ia.py

# V2 telegráfico (2026-07-05, pedido de Diego: "más compacto"): estilo titular
# de agencia, no oración completa. RESUMEN_V versiona el prompt — aplicar()
# re-procesa los items resumidos con una versión anterior (bajo el cap).
RESUMEN_V = 2
_PROMPT = (
    "Convertí este comunicado del mercado de valores boliviano (ASFI/RMV) en un "
    "titular telegráfico de MÁXIMO 90 caracteres, estilo cable de agencia: "
    "sujeto + acción + dato clave. Ejemplos del estilo: «BISA desembolsa "
    "Bs 25,0M a DATEC», «Renuncia la Resp. de Riesgos de AICC SAFI», «Autorizan "
    "Bonos INCOTEC II», «Paga cupón N°9 de Bonos Subordinados 2021». Usá SOLO "
    "información del texto; conservá montos, números de cupón y nombres tal "
    "como aparecen (podés abreviar cargos y razones sociales). Sin punto final, "
    "sin comillas, sin puntos suspensivos, sin agregar contexto. Si el texto no "
    "da para un titular, respondé exactamente: INSUFICIENTE."
    "\n\nEntidad: {entidad}\n\nComunicado: {texto}"
)

SENTINEL = "INSUFICIENTE"
_RECHAZO = ("no puedo", "no me es posible", "lo siento")
_INSUF_PREFIJO = re.compile(r"^INSUFICIENTE(?:[\n\r:(.—-]|\s+[(:—-]|$)")


def init_spend_schema(conn) -> None:
    """Crea asfi_api_spend idempotente (self-apply; en el VPS no corre runner
    de migraciones — mismo racional que resumen_ia.init_spend_schema)."""
    conn.execute(SPEND_DDL)
    conn.commit()


def _mes_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _cap_usd() -> float:
    try:
        return float(os.environ.get("ASFI_RESUMEN_CAP_USD", "").strip() or CAP_USD_MENSUAL_DEFAULT)
    except ValueError:
        return CAP_USD_MENSUAL_DEFAULT


def _gasto_mes(conn, mes: str) -> float:
    row = conn.execute("SELECT est_usd FROM asfi_api_spend WHERE mes = ?", (mes,)).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def _acumular_gasto(conn, mes: str, in_tok: int, out_tok: int) -> None:
    costo = in_tok / 1e6 * PRECIO_IN_USD_MTOK + out_tok / 1e6 * PRECIO_OUT_USD_MTOK
    conn.execute(
        "INSERT INTO asfi_api_spend (mes, est_usd, llamadas, in_tokens, out_tokens) "
        "VALUES (?, ?, 1, ?, ?) "
        "ON CONFLICT(mes) DO UPDATE SET "
        "  est_usd = est_usd + excluded.est_usd,"
        "  llamadas = llamadas + 1,"
        "  in_tokens = in_tokens + excluded.in_tokens,"
        "  out_tokens = out_tokens + excluded.out_tokens",
        (mes, costo, in_tok, out_tok))
    conn.commit()


def _es_fallo(txt: str) -> bool:
    t = (txt or "").strip()
    if not t:
        return True
    if t.rstrip(".").upper() == SENTINEL or _INSUF_PREFIJO.match(t.upper()):
        return True
    low = t.lower()
    return any(p in low for p in _RECHAZO)


def habilitado() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return False
    return os.environ.get("ASFI_RESUMEN", "1").strip().lower() not in ("0", "false", "no")


def extracto(texto: str) -> str:
    """Fallback extractivo (origen B): primera oración, cap 200 con corte en
    palabra. Es lo que se muestra si la IA no corre o degrada."""
    t = " ".join((texto or "").split())
    m = re.match(r"(.{40,%d}?\.)\s" % RESUMEN_MAX_CHARS, t + " ")
    if m:
        return m.group(1)
    if len(t) <= RESUMEN_MAX_CHARS:
        return t
    corte = t.rfind(" ", 0, RESUMEN_MAX_CHARS)
    if corte < RESUMEN_MAX_CHARS // 2:
        corte = RESUMEN_MAX_CHARS
    return t[:corte].rstrip(" ,;:.")


def resumir_item(entidad: str, texto: str, *, autorizado: bool = False,
                 conn=None) -> "str | None | object":
    """Resumen IA de un comunicado, o None (fallo semántico) / TRANSITORIO
    (fallo de red, reintentable). Contrato de candado + cap idéntico a
    resumen_ia.resumir() — ver docstring de ese módulo."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not habilitado():
        return None
    cuerpo = (texto or "").strip()[:TEXTO_MAX]
    if not cuerpo:
        return None
    if not autorizado:
        raise RuntimeError(
            "Llamada API ad-hoc no autorizada — requiere flag explícito "
            "(autorizado=True) + autorización de Diego en el brief")

    mes = _mes_utc()
    try:
        gastado = _gasto_mes(conn, mes)
    except Exception as e:
        log.warning(f"[asfi_resumen] cap: asfi_api_spend ilegible ({e!r}) — fail-closed")
        return None
    cap = _cap_usd()
    if gastado >= cap:
        log.warning(f"[asfi_resumen] CAP mensual ${cap:.2f} alcanzado "
                    f"(gastado=${gastado:.4f}, mes={mes}) — NO POST")
        return None

    modelo = os.environ.get("ASFI_RESUMEN_MODELO", "").strip() or MODELO_DEFAULT
    payload = {
        "model": modelo,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user",
                      "content": _PROMPT.format(entidad=entidad or "ASFI", texto=cuerpo)}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-api-key": key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
        usage = data.get("usage") or {}
        _acumular_gasto(conn, mes, int(usage.get("input_tokens") or 0),
                        int(usage.get("output_tokens") or 0))
        partes = data.get("content") or []
        txt = "".join(p.get("text", "") for p in partes if p.get("type") == "text").strip()
        if _es_fallo(txt):
            return None
        if len(txt) > RESUMEN_MAX_CHARS:
            corte = txt.rfind(" ", 0, RESUMEN_MAX_CHARS)
            if corte < RESUMEN_MAX_CHARS // 2:
                corte = RESUMEN_MAX_CHARS
            txt = txt[:corte].rstrip(" ,;:.")
        return txt
    except Exception as e:
        log.warning(f"[asfi_resumen] fallo transitorio: {e}")
        return TRANSITORIO


def aplicar(items: list, *, autorizado: bool = False, conn=None) -> int:
    """Completa item['resumen']/['resumen_origen'] en los items pendientes:
    sin resumen IA, o resumidos con una versión de prompt anterior a RESUMEN_V
    (la migración a un prompt nuevo corre sola, en tandas bajo el cap).
    Idempotente. Devuelve n resumidos."""
    if not habilitado():
        return 0
    n_ok = 0
    for it in items:
        if it.get("resumen_origen") == "ia" and it.get("resumen_v") == RESUMEN_V:
            continue
        r = resumir_item(it.get("entidad", ""), it.get("texto", ""),
                         autorizado=autorizado, conn=conn)
        if isinstance(r, str):
            it["resumen"] = r
            it["resumen_origen"] = "ia"
            it["resumen_v"] = RESUMEN_V
            n_ok += 1
    return n_ok
