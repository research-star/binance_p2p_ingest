#!/usr/bin/env python3
"""
test_noticias_carril.py — Test del carril flag + category colapsada (FASE 3 Capa 2).

Verifica:
  - build_nota (carril='bolivia') y build_nota_latam (carril='latam', category='internacional').
  - category ∈ {economia, finanzas, politica, internacional, otros}; General → 'otros'.
  - INSERT + SELECT con COALESCE(carril, ...) round-trip correcto.
  - Compatibilidad legacy: fila con carril NULL + category='latam' → COALESCE='latam'
    (así el bloque Latam del frontend no se rompe en filas viejas).

Corre sobre DB temporal (NUNCA prod). Uso: python scripts/test_noticias_carril.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest_noticias
from noticias_ingest import transform
from noticias_ingest.transform import TEMA_CATEGORIA, build_nota, build_nota_latam

# Expresión idéntica a dashboard.py / ingest CARRIL_SQL.
CARRIL_SQL = "COALESCE(carril, CASE WHEN category = 'latam' THEN 'latam' ELSE 'bolivia' END)"


def run():
    errores = []

    # 1. category editorial: todos los valores ∈ {economia, finanzas, politica,
    #    internacional, otros} (5 cubos honestos). 'General' → 'otros' (relleno),
    #    NO se descarta ni se disfraza de economía.
    CATS = {"economia", "finanzas", "politica", "internacional", "otros"}
    vals = set(TEMA_CATEGORIA.values())
    if not vals <= CATS:
        errores.append(f"TEMA_CATEGORIA tiene valores fuera de {CATS}: {vals}")
    if TEMA_CATEGORIA.get("General") != "otros":
        errores.append(f"General debería mapear a 'otros', no {TEMA_CATEGORIA.get('General')!r}")
    if transform.categoria_de_tema("tema inexistente") != "otros":
        errores.append("default de categoria_de_tema debería ser 'otros'")

    ahora = datetime.now(timezone.utc)

    # 2. build_nota (Bolivia).
    cand = {"portal": "El Deber", "link": "https://eldeber.com.bo/economia/x_1781800000",
            "titulo": "Nota economica boliviana de prueba", "descripcion": "", "cuerpo": "",
            "tema": "Bloqueos / Conflictos", "puntaje": 7.5,
            "score_crudo": None, "score_ajustado": None, "image_url": ""}
    nbo = build_nota(cand, ahora)
    if nbo.get("carril") != "bolivia":
        errores.append(f"build_nota carril={nbo.get('carril')!r} (esperado 'bolivia')")
    if nbo["category"] != "politica":
        errores.append(f"build_nota category={nbo['category']!r} (Bloqueos→politica esperado)")

    # 3. build_nota_latam.
    entry = SimpleNamespace(summary="resumen latam", content=None,
                            link="https://www.bloomberglinea.com/latinoamerica/argentina/nota/",
                            id="guid-latam-1", author="", title="Nota latam de prueba")
    nlt = build_nota_latam(ahora, entry, ahora)
    if nlt.get("carril") != "latam":
        errores.append(f"build_nota_latam carril={nlt.get('carril')!r} (esperado 'latam')")
    if nlt["category"] != "internacional":
        errores.append(f"build_nota_latam category={nlt['category']!r} (esperado 'internacional')")

    # 4. INSERT + SELECT round-trip (incluye fila legacy con carril NULL).
    tmp = Path(tempfile.mkdtemp(prefix="fb_carril_test_"))
    conn = sqlite3.connect(str(tmp / "t.db"))
    ingest_noticias.init_schema(conn)
    ingest_noticias.insertar_notas(conn, [nbo, nlt])
    # Fila legacy: sin carril, category='latam' (esquema viejo).
    conn.execute(
        "INSERT INTO noticias (id,date,time,source,category,title,impact,url,portal,tema,puntaje,created_at_utc) "
        "VALUES ('legacy1','2026-06-01','07:45','bloomberg','latam','Nota legacy','medio',"
        "'https://x.test/legacy','Bloomberg Línea','',0.0,'2026-06-01T11:45:00Z')")
    conn.commit()

    rows = {r[0]: r[1] for r in conn.execute(f"SELECT id, {CARRIL_SQL} FROM noticias").fetchall()}
    conn.close()

    if rows.get(nbo["id"]) != "bolivia":
        errores.append(f"SELECT carril BO={rows.get(nbo['id'])!r} (esperado 'bolivia')")
    if rows.get(nlt["id"]) != "latam":
        errores.append(f"SELECT carril latam={rows.get(nlt['id'])!r} (esperado 'latam')")
    if rows.get("legacy1") != "latam":
        errores.append(f"SELECT carril legacy={rows.get('legacy1')!r} (esperado 'latam' por COALESCE)")

    if errores:
        print("FAIL test_noticias_carril:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_noticias_carril: carril BO/latam + category∈{economia,finanzas,politica,"
          "internacional,otros} (General→otros, latam→internacional) + legacy COALESCE='latam'.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
