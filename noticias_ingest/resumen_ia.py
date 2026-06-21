"""
resumen_ia.py — Resumen editorial neutral (1-2 frases) de una nota, vía Claude.

OPT-IN y degradación elegante: si no hay ANTHROPIC_API_KEY (o la llamada falla
o tarda), resumir() devuelve None y el pipeline usa el extracto del cuerpo como
hasta hoy. NUNCA bloquea ni rompe la ingesta.

Calibración 2026-06-21: resumen NEUTRAL y FACTUAL (qué pasó), sin interpretar.
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
import urllib.request

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
MODELO_DEFAULT = "claude-haiku-4-5-20251001"  # corto y barato; overridable por env
TIMEOUT_S = 20
MAX_TOKENS = 120
RESUMEN_MAX_CHARS = 200  # = transform.SUMMARY_MAX (mismo slot del frontend)

_PROMPT = (
    "Resumí esta noticia económica boliviana en 1-2 frases, en español neutro y "
    "factual (qué pasó), SIN opinar ni interpretar y sin preámbulo. Máximo ~40 "
    "palabras. Devolvé solo el resumen.\n\nTitular: {titulo}\n\nTexto: {texto}"
)


def habilitado() -> bool:
    """True si hay API key y el flag NOTICIAS_RESUMEN no está apagado."""
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return False
    return os.environ.get("NOTICIAS_RESUMEN", "1").strip().lower() not in ("0", "false", "no")


def resumir(titulo: str, texto: str) -> str | None:
    """Resumen neutral 1-2 frases (≤200 chars), o None si no hay key / falla.

    Pura degradación: cualquier error (sin key, red, timeout, respuesta rara) →
    None, y el caller conserva el extracto que ya tenía.
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
        "messages": [{"role": "user", "content": _PROMPT.format(titulo=titulo, texto=cuerpo)}],
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
        if not txt:
            return None
        if len(txt) > RESUMEN_MAX_CHARS:
            corte = txt.rfind(" ", 0, RESUMEN_MAX_CHARS)
            txt = txt[: corte if corte > RESUMEN_MAX_CHARS // 2 else RESUMEN_MAX_CHARS].rstrip(" ,;:.") + "…"
        return txt
    except Exception as e:
        log.warning(f"[resumen_ia] fallo (uso extracto): {e}")
        return None


def aplicar(notas: list) -> int:
    """Reemplaza n['summary'] por el resumen IA en las notas dadas, si está
    habilitado. No-op si no hay key. Devuelve cuántas se resumieron.

    Usa `detail` (cuerpo ~400 chars) como insumo; si no hay, el summary actual.
    Conserva el extracto original si la API falla en esa nota."""
    if not habilitado():
        return 0
    n_ok = 0
    for n in notas:
        r = resumir(n.get("title", ""), n.get("detail") or n.get("summary") or "")
        if r:
            n["summary"] = r
            n_ok += 1
    return n_ok
