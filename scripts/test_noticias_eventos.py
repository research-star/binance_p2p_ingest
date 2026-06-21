#!/usr/bin/env python3
"""test_noticias_eventos.py — Agrupación por evento + tier ("También en…").

Verifica (calibración 2026-06-21):
  - Notas del mismo evento (título similar) colapsan a UNA representante con
    tambien_en = [{source,portal,url}] de las demás.
  - La representante es la de MENOR tier de fuente (oficiales/gremios T1 > T2 > T3),
    aunque tenga menor puntaje (tier desempata).
  - Eventos distintos NO se fusionan; los grupos se ordenan por puntaje máximo.
  - Round-trip de la columna tambien_en (insert + select).

Uso: python scripts/test_noticias_eventos.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest_noticias
from ingest_noticias import agrupar_eventos, source_tier
from noticias_ingest.transform import build_nota


def _n(title, source, portal, url, puntaje, ents=None):
    return {"title": title, "source": source, "portal": portal, "url": url,
            "puntaje": puntaje, "entidades": ents or []}


def run() -> int:
    errores = []

    # 1. Mismo evento (título idéntico), T2 (eldeber) vs T3 (unitel) → rep T2.
    g = agrupar_eventos([
        _n("El dólar paralelo sube en Bolivia y preocupa a importadores", "unitel", "Unitel", "https://u/1", 8.0),
        _n("El dólar paralelo sube en Bolivia y preocupa a importadores", "eldeber", "El Deber", "https://e/1", 7.5),
    ])
    if len(g) != 1:
        errores.append(f"mismo evento debería dar 1 grupo, dio {len(g)}")
    elif g[0]["source"] != "eldeber":
        errores.append(f"representante debería ser eldeber (T2<T3), fue {g[0]['source']}")
    elif [t["source"] for t in g[0].get("tambien_en", [])] != ["unitel"]:
        errores.append(f"tambien_en debería ser [unitel], fue {g[0].get('tambien_en')}")

    # 2. Tier MANDA sobre puntaje: T1 (ypfb, 6.8) gana a T3 (unitel, 9.0) como rep.
    g2 = agrupar_eventos([
        _n("YPFB anuncia inversión en nuevos pozos de gas en Tarija", "unitel", "Unitel", "https://u/2", 9.0, ["YPFB"]),
        _n("YPFB anuncia inversión en nuevos pozos de gas en Tarija", "ypfb", "YPFB", "https://y/2", 6.8, ["YPFB"]),
    ])
    if len(g2) != 1 or g2[0]["source"] != "ypfb":
        errores.append(f"T1 (ypfb) debería ser representante sobre T3, dio {[x['source'] for x in g2]}")

    # 3. Eventos distintos NO se fusionan; orden por puntaje máximo (dólar 8 > soya 7).
    g3 = agrupar_eventos([
        _n("El dólar paralelo sube en Bolivia", "unitel", "Unitel", "https://u/3", 8.0),
        _n("Productores de soya cierran la zafra con cifras récord", "eldeber", "El Deber", "https://e/3", 7.0),
    ])
    if len(g3) != 2:
        errores.append(f"eventos distintos deberían dar 2 grupos, dio {len(g3)}")
    elif g3[0]["puntaje"] < g3[1]["puntaje"]:
        errores.append("grupos deberían ordenarse por puntaje máximo desc")
    elif any("tambien_en" in x for x in g3):
        errores.append("eventos distintos NO deberían tener tambien_en")

    # 4. Tier default.
    if source_tier("desconocido") != 3 or source_tier("bcb") != 1 or source_tier("eldeber") != 2:
        errores.append("source_tier mal: bcb→1, eldeber→2, desconocido→3")

    # 5. Round-trip de la columna tambien_en (insert + select).
    ahora = datetime.now(timezone.utc)
    cand = {"portal": "El Deber", "link": "https://eldeber.com.bo/economia/x_42",
            "titulo": "Nota con también-en", "descripcion": "", "cuerpo": "",
            "tema": "Tipo de cambio / Dólar", "puntaje": 7.8,
            "score_crudo": None, "score_ajustado": None, "image_url": ""}
    nota = build_nota(cand, ahora)
    nota["tambien_en"] = [{"source": "unitel", "portal": "Unitel", "url": "https://u/x"}]
    tmp = Path(tempfile.mkdtemp(prefix="fb_eventos_test_"))
    conn = sqlite3.connect(str(tmp / "t.db"))
    ingest_noticias.init_schema(conn)
    ingest_noticias.insertar_notas(conn, [nota])
    row = conn.execute("SELECT tambien_en FROM noticias WHERE id=?", (nota["id"],)).fetchone()
    conn.close()
    got = json.loads(row[0]) if row and row[0] else []
    if got != nota["tambien_en"]:
        errores.append(f"round-trip tambien_en falló: {got!r}")

    if errores:
        print("FAIL test_noticias_eventos:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_noticias_eventos: agrupa por evento, tier elige representante "
          "(T1>T2>T3 sobre puntaje), eventos distintos separados + round-trip tambien_en.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
