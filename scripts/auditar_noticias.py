#!/usr/bin/env python3
"""
auditar_noticias.py — Dry-run READ-ONLY del incremento 1 de selección de noticias.

Re-aplica las compuertas NUEVAS (geo-gate universal + matar General→economía) a las
notas Bolivia YA PUBLICADAS en la DB, para medir —sobre datos reales— cuántas
cortaría cada regla antes de mergear el cambio a la ingesta. No escribe nada.

Responde:
  - ¿Cuántas notas publicadas serían descartadas por `falta_bolivia` (extranjeras /
    sin ancla en Bolivia) y por `general_sin_clasificar` (sin tema ni evidencia
    económica)? → si son basura, el cambio es bueno; si hay legítimas, hay falso
    negativo a calibrar.
  - ¿Algún día quedaría por debajo del presupuesto (riesgo de huecos en el feed)?
  - ¿Qué portales aportan más descartes?

Uso:
    python scripts/auditar_noticias.py                 # DB p2p_normalized.db, 30 días
    python scripts/auditar_noticias.py --db otra.db --dias 60
    python scripts/auditar_noticias.py --motivo falta_bolivia --limit 40   # ver todos

Correr en el VPS (donde vive la DB de prod) o contra una copia. Es read-only.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticias_ingest import scraper

# Umbral de presupuesto diario Bolivia (informativo, para señalar días flacos).
TOP_N_BOLIVIA = 14


def clasificar_dryrun(title: str, summary: str) -> tuple:
    """Aplica las compuertas NUEVAS del incremento 1 a una nota ya publicada.

    Devuelve (motivo_descarte | None, tema, entidades). Reusa _tema /
    detectar_entidades / las constantes de scraper para ser fiel al carril vivo.
    """
    title = title or ""
    summary = summary or ""
    text = (title + " " + summary).lower()
    tema, _ = scraper._tema(title, summary)
    ents = scraper.detectar_entidades(title, summary)
    geo_ok = (any(t in text for t in scraper.TERMINOS_BOLIVIA)
              or any(e in scraper.ENTIDADES_BOLIVIANAS for e in ents))
    if not geo_ok:
        return "falta_bolivia", tema, ents
    if tema == "General" and not any(e in scraper.ENTIDADES_ECONOMICAS for e in ents):
        return "general_sin_clasificar", tema, ents
    return None, tema, ents


def auditar(conn: sqlite3.Connection, dias: int = 30) -> dict:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT date, source, title, summary, tema FROM noticias "
        "WHERE date >= date('now','-4 hours',?) "
        "  AND COALESCE(carril, CASE WHEN category='latam' THEN 'latam' ELSE 'bolivia' END) != 'latam' "
        "ORDER BY date DESC, time DESC",
        (f"-{dias} days",),
    ).fetchall()

    motivos = Counter()
    ejemplos = defaultdict(list)
    por_portal = defaultdict(lambda: [0, 0])   # source -> [total, cortadas]
    por_dia = defaultdict(lambda: [0, 0])       # date   -> [total, sobreviven]

    for r in rows:
        motivo, tema, ents = clasificar_dryrun(r["title"], r["summary"])
        por_portal[r["source"]][0] += 1
        por_dia[r["date"]][0] += 1
        if motivo:
            motivos[motivo] += 1
            por_portal[r["source"]][1] += 1
            ejemplos[motivo].append((r["date"], r["source"], (r["title"] or "").strip(),
                                     r["tema"], tema, ents))
        else:
            por_dia[r["date"]][1] += 1

    return {
        "total": len(rows), "dias": dias, "motivos": motivos, "ejemplos": ejemplos,
        "por_portal": dict(por_portal), "por_dia": dict(por_dia),
    }


def imprimir(rep: dict, motivo_filtro: str | None, limit: int) -> None:
    total = rep["total"]
    cortadas = sum(rep["motivos"].values())
    print(f"\n══ AUDITORÍA INCREMENTO 1 · últimos {rep['dias']} días ══")
    print(f"Notas Bolivia publicadas: {total}")
    if not total:
        print("(sin notas en la ventana — ¿DB vacía o ruta equivocada?)")
        return
    pct = 100.0 * cortadas / total
    print(f"Serían descartadas por las reglas nuevas: {cortadas} ({pct:.1f}%)")
    for m, n in rep["motivos"].most_common():
        print(f"   · {m}: {n} ({100.0*n/total:.1f}%)")

    for m in (["falta_bolivia", "general_sin_clasificar"] if not motivo_filtro else [motivo_filtro]):
        ej = rep["ejemplos"].get(m, [])
        if not ej:
            continue
        print(f"\n── Ejemplos «{m}» ({len(ej)}; muestro {min(limit, len(ej))}) ──")
        for date, src, title, tema_db, tema_now, ents in ej[:limit]:
            ent_s = ("[" + ",".join(ents) + "]") if ents else "[]"
            print(f"  {date} · {src} · tema={tema_now!r} ent={ent_s}\n     {title}")

    print("\n── Descartes por portal (cortadas/total) ──")
    for src, (tot, cut) in sorted(rep["por_portal"].items(), key=lambda kv: -kv[1][1]):
        if cut:
            print(f"  {src:<18} {cut}/{tot}  ({100.0*cut/tot:.0f}%)")

    flacos = sorted((d, s, t) for d, (t, s) in rep["por_dia"].items() if s < 10)
    print(f"\n── Días que quedarían con <10 notas (presupuesto {TOP_N_BOLIVIA}) ──")
    if flacos:
        for d, s, t in flacos:
            print(f"  {d}: {s} sobreviven de {t}")
    else:
        print("  ninguno — ningún día baja de 10 notas.")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Dry-run read-only del incremento 1 de noticias.")
    ap.add_argument("--db", default="p2p_normalized.db", help="ruta a la DB (default p2p_normalized.db)")
    ap.add_argument("--dias", type=int, default=30, help="ventana en días (default 30)")
    ap.add_argument("--motivo", choices=["falta_bolivia", "general_sin_clasificar"],
                    default=None, help="filtrar ejemplos por un motivo")
    ap.add_argument("--limit", type=int, default=12, help="máximo de ejemplos por motivo")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"ERROR: no existe la DB {args.db!r}. Pasá --db con la ruta correcta.")
        return 2
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)  # READ-ONLY
    try:
        rep = auditar(conn, args.dias)
    finally:
        conn.close()
    imprimir(rep, args.motivo, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
