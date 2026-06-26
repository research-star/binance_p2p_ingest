"""
resumen_ia.py — Resumen editorial neutral (1-2 frases) de una nota, vía Claude.

OPT-IN y degradación elegante: si no hay ANTHROPIC_API_KEY (o la llamada falla
o tarda), resumir() devuelve None y el pipeline usa el extracto del cuerpo como
hasta hoy. NUNCA bloquea ni rompe la ingesta.

Calibración 2026-06-25 (prompt V2, bake-off): resumen NEUTRAL y FACTUAL que
SUMA un dato fuera del título (baja el eco título↔resumen), parametrizado por
ÁMBITO según carril (BO="Bolivia" / Latam="América Latina" — nunca "boliviana"
en Latam). Centinela INSUFICIENTE + patrones de rechazo se tratan como FALLO
→ resumir() devuelve None y el caller conserva el extracto (origen='extractivo').
Solo se llama para las notas que se INSERTAN (≤14 BO + ≤8 latam por día) → costo
acotado. Usa solo stdlib (urllib) — no agrega dependencia al repo.

Activación en el VPS (no se prende solo):
    export ANTHROPIC_API_KEY=sk-ant-...
    # opcionales:
    export NOTICIAS_RESUMEN=1                       # default on cuando hay key; 0 lo apaga
    export NOTICIAS_RESUMEN_MODELO=claude-haiku-4-5-20251001  # default (corto y barato)
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
MODELO_DEFAULT = "claude-haiku-4-5-20251001"  # corto y barato; overridable por env
TIMEOUT_S = 20
MAX_TOKENS = 120
RESUMEN_MAX_CHARS = 200  # = transform.SUMMARY_MAX (mismo slot del frontend)
# Palanca de extracción (PR re-resumen): la IA se resume sobre el CUERPO scrapeado
# (≤10000, = cap de scraper.scrape_cuerpo), no sobre el detail de 400 → menos
# INSUFICIENTE. TEXTO_MAX acota el insumo (cost-bound). CUERPO_GATE: el cuerpo se usa
# solo si es "sustantivo"; si no bajó o es basura corta (p.ej. método 1 sin gate de
# longitud), se cae al detail/RSS como antes — no se feedea un cuerpo trunco "bueno".
TEXTO_MAX = 10000
CUERPO_GATE = 300

# ── Cap de gasto API (defensa en profundidad) ─────────────────────────────────
# 2ª condición de aborto del POST, DENTRO del candado: autorizado=True cubre la
# INTENCIÓN (acto deliberado); el cap cubre el ACCIDENTE (código futuro que resuma
# de más → runaway de Haiku). El gasto se acumula en api_spend (mig 0009) por mes
# UTC; el cap lee el acumulado ANTES de cada POST. Overshoot ≤1 llamada (~$0.004)
# aceptable: se chequea con el acumulado real, no se estima el costo pre-POST.
CAP_USD_MENSUAL = 1.00          # techo mensual configurable (USD)
PRECIO_IN_USD_MTOK = 1.00       # Haiku 4.5 input  $/1M tokens (catálogo SDK 2026-06)
PRECIO_OUT_USD_MTOK = 5.00      # Haiku 4.5 output $/1M tokens

SPEND_DDL = (
    "CREATE TABLE IF NOT EXISTS api_spend ("
    " mes TEXT PRIMARY KEY,"
    " est_usd REAL NOT NULL DEFAULT 0,"
    " llamadas INTEGER NOT NULL DEFAULT 0,"
    " in_tokens INTEGER NOT NULL DEFAULT 0,"
    " out_tokens INTEGER NOT NULL DEFAULT 0)"
)


def init_spend_schema(conn) -> None:
    """Crea api_spend idempotente (self-apply, como el column-migrate de init_schema).
    Lo invoca ingest_noticias.init_schema en cada corrida → desacopla el cap de
    cuándo se aplica 0009 a mano en el VPS. Es CRÍTICO autocrearla: el cap lee el
    acumulado y fail-closea si la tabla falta → sin self-apply, deployar esto
    bloquearía TODO resumen en prod hasta correr la migración a mano."""
    conn.execute(SPEND_DDL)
    conn.commit()


def _mes_utc() -> str:
    """Partición mensual del gasto en UTC (matchea cron y logs)."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _gasto_mes(conn, mes: str) -> float:
    """Acumulado USD del mes. Lanza si conn es None o api_spend es ilegible — el
    cap (caller) lo trata como FAIL-CLOSED (aborta el POST)."""
    row = conn.execute("SELECT est_usd FROM api_spend WHERE mes = ?", (mes,)).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def _acumular_gasto(conn, mes: str, in_tok: int, out_tok: int) -> None:
    """Suma costo estimado + contadores en api_spend del mes. SIN commit: el caller
    commitea, así el gasto entra en la MISMA transacción que persiste la nota
    (atómico con el INSERT/UPDATE por nota existente)."""
    costo = in_tok / 1e6 * PRECIO_IN_USD_MTOK + out_tok / 1e6 * PRECIO_OUT_USD_MTOK
    conn.execute(
        "INSERT INTO api_spend (mes, est_usd, llamadas, in_tokens, out_tokens) "
        "VALUES (?, ?, 1, ?, ?) "
        "ON CONFLICT(mes) DO UPDATE SET "
        "  est_usd = est_usd + excluded.est_usd,"
        "  llamadas = llamadas + 1,"
        "  in_tokens = in_tokens + excluded.in_tokens,"
        "  out_tokens = out_tokens + excluded.out_tokens",
        (mes, costo, in_tok, out_tok))

# Sentinela de FALLO TRANSITORIO (red/timeout/HTTP/JSON): la llamada se intentó pero
# falló por un error REINTENTABLE. Se DISTINGUE del fallo SEMÁNTICO (INSUFICIENTE/
# rechazo/vacío → None): el re-resumen NO debe marcar el cuerpo como "ya juzgado"
# (extract_len) ante un transitorio — el MISMO cuerpo es reintentable, acotado por el
# cap. Es un objeto único (identidad), nunca un resumen válido. aplicar() lo trata como
# fallo (no es un string), igual que None → conserva el extracto.
TRANSITORIO = object()

# Prompt V2.1 (solo-data, 2026-06-25). {ambito} = "Bolivia" (carril BO) | "América
# Latina" (carril Latam). Endurecido: SOLO la info del texto provisto, PROHIBIDO
# agregar causas/contexto/caracterizaciones aunque el modelo las conozca de otra
# fuente (evita editorializar — riesgo en plataforma de inteligencia económica).
# Más INSUFICIENTE es esperado y aceptado (fidelidad > cobertura).
_PROMPT = (
    "Resumí en español esta noticia económica de {ambito} usando EXCLUSIVAMENTE la "
    "información del texto provisto. Máximo 200 caracteres, una sola oración, sin "
    "puntos suspensivos. No repitas el titular: incluí un dato del texto que no esté "
    "en el título (cifra, monto, fecha o actor). PROHIBIDO agregar causas, contexto, "
    "interpretaciones o caracterizaciones que no aparezcan en el texto, aunque las "
    "conozcas de otra fuente. Tono neutral y factual. Si el texto no aporta ningún "
    "dato verificable más allá del título, respondé exactamente: INSUFICIENTE."
    "\n\nTitular: {titulo}\n\nTexto: {texto}"
)

SENTINEL = "INSUFICIENTE"
# Patrones de rechazo del modelo (no es un resumen): se tratan como FALLO.
_RECHAZO = ("no puedo", "no me es posible", "lo siento", "la noticia trata sobre")
# V2.1 induce a veces "INSUFICIENTE\n\n(explicación)" en vez del token exacto. Se
# trata como FALLO cuando ARRANCA con el centinela seguido de fin / salto / ':' /
# '(' / '.' / '—' / '-'. ANCLA ^ (no `contains`): un resumen legítimo que use la
# palabra ("producción insuficiente para…") NO cae porque no arranca con ella.
_INSUF_PREFIJO = re.compile(r"^INSUFICIENTE(?:[\n\r:(.—-]|\s+[(:—-]|$)")


def _es_fallo(txt: str) -> bool:
    """True si la respuesta IA NO es un resumen usable: centinela INSUFICIENTE
    (exacto o con explicación pegada), patrón de rechazo, o vacío. El caller degrada
    a extractivo (origen='extractivo', asterisco en el front) — nunca persiste
    basura/alucinación como origen='ia'."""
    t = (txt or "").strip()
    if not t:
        return True
    if t.rstrip(".").upper() == SENTINEL:
        return True
    if _INSUF_PREFIJO.match(t.upper()):
        return True
    low = t.lower()
    return any(p in low for p in _RECHAZO)


def habilitado() -> bool:
    """True si hay API key y el flag NOTICIAS_RESUMEN no está apagado."""
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return False
    return os.environ.get("NOTICIAS_RESUMEN", "1").strip().lower() not in ("0", "false", "no")


def resumir(titulo: str, texto: str, ambito: str = "Bolivia", *,
            autorizado: bool = False, conn=None) -> str | None:
    """Resumen neutral V2 (≤200 chars, sin elipsis) para el `ambito` del carril, o
    None si no hay key / falla / la IA no pudo resumir.

    Pura degradación: cualquier error (sin key, red, timeout, respuesta rara) y
    cualquier FALLO de la IA (INSUFICIENTE, rechazo, vacío — ver _es_fallo) → None,
    y el caller conserva el extracto que ya tenía (origen='extractivo').
    `ambito` = "Bolivia" (carril BO) | "América Latina" (carril Latam).

    `autorizado`: CANDADO de gasto API (anti-accidente, NO barrera infranqueable —
    un caller puede pasar True). El POST solo procede con autorizado=True. El
    pipeline (ingest_noticias) lo pasa explícito; cualquier script ad-hoc debe
    setearlo a propósito (acto deliberado y visible) + tener OK de Diego en el brief.

    `conn`: conexión SQLite para el CAP de gasto (2ª condición de aborto) y la
    captura de usage. El cap lee api_spend ANTES del POST; FAIL-CLOSED si conn es
    None o la lectura falla (return None → extractivo). La captura acumula el gasto
    SIN commit (el caller commitea → atómico con la persistencia de la nota).
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not habilitado():
        return None
    cuerpo = (texto or "").strip()[:TEXTO_MAX]
    titulo = (titulo or "").strip()
    if not (titulo or cuerpo):
        return None
    if not autorizado:
        raise RuntimeError(
            "Llamada API ad-hoc no autorizada — requiere flag explícito "
            "(autorizado=True) + autorización de Diego en el brief")

    # 2ª CONDICIÓN DE ABORTO: cap de gasto mensual (defensa en profundidad). Lee el
    # acumulado del mes ANTES de construir el POST. FAIL-CLOSED con log ruidoso: si
    # no hay conn o api_spend es ilegible, NO se hace POST (return None → extractivo).
    # Una nota en B es recuperable (re-resumen); un runaway de Haiku no.
    mes = _mes_utc()
    try:
        gastado = _gasto_mes(conn, mes)
    except Exception as e:
        log.warning(f"[resumen_ia] cap: api_spend ilegible ({e!r}) — fail-closed, uso extracto")
        return None
    if gastado >= CAP_USD_MENSUAL:
        log.warning(
            f"[resumen_ia] CAP mensual ${CAP_USD_MENSUAL:.2f} alcanzado "
            f"(gastado=${gastado:.4f}, mes={mes}) — uso extracto, NO POST")
        return None

    modelo = os.environ.get("NOTICIAS_RESUMEN_MODELO", "").strip() or MODELO_DEFAULT
    payload = {
        "model": modelo,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user",
                      "content": _PROMPT.format(ambito=ambito, titulo=titulo, texto=cuerpo)}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
        # Captura de usage (antes se descartaba): el POST se facturó SÍ o SÍ — aun si
        # la respuesta es INSUFICIENTE/fallo — así que se acumula el gasto ANTES del
        # _es_fallo. SIN commit (el caller commitea → atómico con la persistencia de
        # la nota). El cap del próximo POST verá este gasto (read-your-writes en la
        # misma transacción).
        usage = data.get("usage") or {}
        _acumular_gasto(conn, mes, int(usage.get("input_tokens") or 0),
                        int(usage.get("output_tokens") or 0))
        partes = data.get("content") or []
        txt = "".join(p.get("text", "") for p in partes if p.get("type") == "text").strip()
        if _es_fallo(txt):
            return None  # INSUFICIENTE / rechazo / vacío → degrada a extractivo
        if len(txt) > RESUMEN_MAX_CHARS:
            # Corte LIMPIO en último límite de palabra ≤200, SIN elipsis.
            corte = txt.rfind(" ", 0, RESUMEN_MAX_CHARS)
            if corte < RESUMEN_MAX_CHARS // 2:
                corte = RESUMEN_MAX_CHARS
            txt = txt[:corte].rstrip(" ,;:.")
        return txt
    except Exception as e:
        # FALLO TRANSITORIO (red/timeout/HTTP/JSON): reintentable. Se devuelve el
        # sentinela TRANSITORIO (no None) para que el re-resumen NO marque extract_len
        # (a diferencia del INSUFICIENTE semántico). El log "uso extracto" distingue
        # esta rama del fallo silencioso de _es_fallo.
        log.warning(f"[resumen_ia] fallo (uso extracto): {e}")
        return TRANSITORIO


def insumo_para_ia(n: dict) -> str:
    """Insumo de texto para la IA: el CUERPO scrapeado (`cuerpo_full`) si es
    sustantivo (≥ CUERPO_GATE), si no el `detail`/`summary` (RSS/extracto) como antes.
    Gate anti-basura: un cuerpo corto (no bajó, o trunco del método 1 sin gate) no
    suma sobre el detail → se usa el fallback."""
    cuerpo = (n.get("cuerpo_full") or "").strip()
    if len(cuerpo) >= CUERPO_GATE:
        return cuerpo
    return (n.get("detail") or n.get("summary") or "").strip()


def aplicar(notas: list, *, autorizado: bool = False, conn=None) -> int:
    """Reemplaza n['summary'] por el resumen IA en las notas dadas, si está
    habilitado. No-op si no hay key. Devuelve cuántas se resumieron.

    Insumo = el CUERPO scrapeado completo (palanca; ver insumo_para_ia), con fallback
    al detail/summary. Conserva el extracto original si la API falla en esa nota.

    `autorizado`: se propaga al candado de resumir() (ver allí). El pipeline lo pasa
    True; un caller ad-hoc sin él hace abortar resumir() antes del POST.
    `conn`: se propaga al cap + captura de usage de resumir() (ver allí). El gasto se
    acumula en api_spend sin commit; el caller del lane commitea (insertar_notas).

    En éxito marca n['summary_origen']='ia' (lo lee el frontend para NO ponerle
    asterisco). Si falla/degrada, el origen queda como lo dejó transform.build_nota
    ('extractivo') → el frontend marca con asterisco. (Col summary_origen, 0007.)
    Setea n['extract_len'] = longitud del insumo usado (col 0008) — lo lee el
    mecanismo de re-resumen para decidir si un re-fetch trajo cuerpo mejor."""
    if not habilitado():
        return 0
    n_ok = 0
    for n in notas:
        ambito = "Bolivia" if n.get("carril") == "bolivia" else "América Latina"
        insumo = insumo_para_ia(n)
        n["extract_len"] = len(insumo)  # insumo que produjo este origen (col 0008)
        r = resumir(n.get("title", ""), insumo, ambito, autorizado=autorizado, conn=conn)
        if r and r is not TRANSITORIO:   # solo un string usable es éxito; None/TRANSITORIO → extracto
            n["summary"] = r
            n["summary_origen"] = "ia"
            n_ok += 1
    return n_ok
