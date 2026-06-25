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

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
MODELO_DEFAULT = "claude-haiku-4-5-20251001"  # corto y barato; overridable por env
TIMEOUT_S = 20
MAX_TOKENS = 120
RESUMEN_MAX_CHARS = 200  # = transform.SUMMARY_MAX (mismo slot del frontend)

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


def resumir(titulo: str, texto: str, ambito: str = "Bolivia") -> str | None:
    """Resumen neutral V2 (≤200 chars, sin elipsis) para el `ambito` del carril, o
    None si no hay key / falla / la IA no pudo resumir.

    Pura degradación: cualquier error (sin key, red, timeout, respuesta rara) y
    cualquier FALLO de la IA (INSUFICIENTE, rechazo, vacío — ver _es_fallo) → None,
    y el caller conserva el extracto que ya tenía (origen='extractivo').
    `ambito` = "Bolivia" (carril BO) | "América Latina" (carril Latam).
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not habilitado():
        return None
    cuerpo = (texto or "").strip()[:2000]
    titulo = (titulo or "").strip()
    if not (titulo or cuerpo):
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
        log.warning(f"[resumen_ia] fallo (uso extracto): {e}")
        return None


def aplicar(notas: list) -> int:
    """Reemplaza n['summary'] por el resumen IA en las notas dadas, si está
    habilitado. No-op si no hay key. Devuelve cuántas se resumieron.

    Usa `detail` (cuerpo ~400 chars) como insumo; si no hay, el summary actual.
    Conserva el extracto original si la API falla en esa nota.

    En éxito marca n['summary_origen']='ia' (lo lee el frontend para NO ponerle
    asterisco). Si falla/degrada, el origen queda como lo dejó transform.build_nota
    ('extractivo') → el frontend marca con asterisco. (Col summary_origen, 0007.)"""
    if not habilitado():
        return 0
    n_ok = 0
    for n in notas:
        ambito = "Bolivia" if n.get("carril") == "bolivia" else "América Latina"
        r = resumir(n.get("title", ""), n.get("detail") or n.get("summary") or "", ambito)
        if r:
            n["summary"] = r
            n["summary_origen"] = "ia"
            n_ok += 1
    return n_ok
