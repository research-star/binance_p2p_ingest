#!/usr/bin/env python3
"""
ingest_asfi.py — Reporte Informativo diario ASFI/RMV → JSON publicable.

Sección "ASFI" de finanzasbo.com: cada día hábil la Dirección de Supervisión
de Valores publica un Reporte Informativo (PDF) con los hechos relevantes del
mercado de valores. Este ingest lo baja (vía proxy con exit Bolivia — ver
asfi_ingest/fetch.py), lo parsea a items estructurados (asfi_ingest/parser.py)
y les agrega un one-liner IA opcional (asfi_ingest/resumen.py, candado + cap).

Salida (committeada al repo, patrón data-BCB; publish_dashboard.py copia los
archivos sueltos de static/ a la raíz de gh-pages):
  static/asfi_YYYY-MM.json  — {"dias": {"YYYY-MM-DD": {guid, titulo, items}}}
  static/asfi_index.json    — {"generado", "dias": {fecha: n_items}, "meses"}

La página static/asfi.html consume esos JSON client-side (selector de fecha).

Modos:
  (default)            corrida diaria de cron: baja lo nuevo de la gestión
                       actual, parsea, resume (si hay key) y reescribe JSONs.
  --backfill DIR       parsea PDFs locales (p.ej. los 122 bajados a mano) sin
                       tocar la red. Dedupe por fecha, idempotente.
  --resumir            pasa la IA sobre items pendientes (origen != 'ia') de
                       toda la data existente — permite backfill de resúmenes
                       en tandas bajo el cap mensual.
  --sin-ia             suprime la IA en cualquier modo (solo extractivo).

Dedupe: por FECHA del reporte (no por guid) — los títulos del listado llevan
la fecha, así el backfill manual (sin guid) y el cron (con guid) no se pisan.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from asfi_ingest import extract, fetch, parser, resumen

log = logging.getLogger("ingest_asfi")

REPO_ROOT = Path(__file__).parent
STATIC_DIR = REPO_ROOT / "static"
NORMALIZED_DB = REPO_ROOT / "p2p_normalized.db"

_RE_FECHA_TITULO = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


# ── Persistencia JSON mensual ────────────────────────────────────────────────

def _mes_path(mes: str, datadir: Path) -> Path:
    return datadir / f"asfi_{mes}.json"


def cargar_mes(mes: str, datadir: Path) -> dict:
    p = _mes_path(mes, datadir)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"dias": {}}


def guardar_mes(mes: str, data: dict, datadir: Path) -> None:
    data["dias"] = dict(sorted(data["dias"].items()))
    with open(_mes_path(mes, datadir), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def fechas_existentes(datadir: Path) -> set[str]:
    out: set[str] = set()
    for p in datadir.glob("asfi_????-??.json"):
        try:
            with open(p, encoding="utf-8") as f:
                out.update(json.load(f).get("dias", {}).keys())
        except (ValueError, OSError) as e:
            log.warning(f"mes ilegible {p.name}: {e}")
    return out


def reescribir_index(datadir: Path) -> dict:
    """Regenera asfi_index.json desde los meses presentes (fuente de verdad =
    archivos mensuales; el índice es derivado, siempre reconstruible)."""
    dias: dict[str, int] = {}
    meses: list[str] = []
    for p in sorted(datadir.glob("asfi_????-??.json")):
        mes = p.stem.replace("asfi_", "")
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (ValueError, OSError):
            continue
        meses.append(mes)
        for fecha, dia in data.get("dias", {}).items():
            dias[fecha] = len(dia.get("items", []))
    index = {
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "meses": meses,
        "dias": dict(sorted(dias.items())),
    }
    with open(datadir / "asfi_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return index


# ── Procesamiento de un reporte ──────────────────────────────────────────────

def persistir_reporte(pdf: "bytes | str", guid: str, titulo: str,
                      datadir: Path, conocidas: set[str]) -> str | None:
    """Parsea un reporte y lo persiste en su archivo mensual SI la fecha no
    existe ya (nunca pisa un día persistido: preservar guid/resúmenes IA de
    corridas previas es parte del contrato de idempotencia). Devuelve la
    fecha si persistió, None si la descartó (sin fecha o ya conocida)."""
    rep = parser.extraer_reporte(pdf)
    fecha = rep["fecha"]
    if not fecha:
        log.warning(f"reporte sin fecha (guid={guid or '?'}, titulo={titulo!r}) — descartado")
        return None
    if fecha in conocidas:
        return None
    for it in rep["items"]:
        it.setdefault("resumen", resumen.extracto(it["texto"]))
        it.setdefault("resumen_origen", "extractivo")
        extract.enriquecer(it)  # grupo + campos para las tablitas del frontend
    mes = fecha[:7]
    data = cargar_mes(mes, datadir)
    data["dias"][fecha] = {"guid": guid, "titulo": titulo, "items": rep["items"]}
    guardar_mes(mes, data, datadir)
    log.info(f"{fecha}: {len(rep['items'])} items → asfi_{mes}.json")
    return fecha


def aplicar_ia(datadir: Path, *, meses: "list[str] | None" = None) -> int:
    """Resume con IA los items pendientes de los meses dados (o todos).
    Cap-bounded: si el cap mensual se alcanza, los restantes quedan
    extractivos y una corrida futura los retoma (aplicar es idempotente)."""
    if not resumen.habilitado():
        log.info("IA no habilitada (sin ANTHROPIC_API_KEY o ASFI_RESUMEN=0) — quedan extractivos")
        return 0
    if not NORMALIZED_DB.exists():
        log.warning("sin p2p_normalized.db — cap ilegible, fail-closed (sin IA)")
        return 0
    conn = sqlite3.connect(str(NORMALIZED_DB))
    resumen.init_spend_schema(conn)
    n_total = 0
    try:
        paths = sorted(datadir.glob("asfi_????-??.json"))
        if meses is not None:
            paths = [p for p in paths if p.stem.replace("asfi_", "") in meses]
        for p in paths:
            mes = p.stem.replace("asfi_", "")
            data = cargar_mes(mes, datadir)
            items = [it for dia in data["dias"].values() for it in dia["items"]]
            n = resumen.aplicar(items, autorizado=True, conn=conn)
            if n:
                guardar_mes(mes, data, datadir)
                n_total += n
                log.info(f"IA: {n} resúmenes nuevos en {mes}")
    finally:
        conn.close()
    return n_total


# ── Modos ────────────────────────────────────────────────────────────────────

def correr_diario(gestion: int, datadir: Path, con_ia: bool) -> int:
    """Corrida de cron: baja los reportes de la gestión que aún no están en
    data. Devuelve cuántos reportes nuevos persistió."""
    conocidas = fechas_existentes(datadir)
    listado = fetch.listar_reportes(gestion)
    if not listado:
        log.warning("listado vacío (proxy caído, geo-block o página cambió)")
        return 0
    nuevos = 0
    meses_tocados: set[str] = set()
    for guid, titulo in listado:
        m = _RE_FECHA_TITULO.search(titulo)
        if m:
            fecha_titulo = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            if fecha_titulo in conocidas:
                continue
        pdf = fetch.descargar_pdf(guid, gestion)
        if pdf is None:
            log.warning(f"descarga fallida guid={guid} ({titulo!r})")
            continue
        fecha = persistir_reporte(pdf, guid, titulo, datadir, conocidas)
        if fecha:
            nuevos += 1
            meses_tocados.add(fecha[:7])
            conocidas.add(fecha)
    if con_ia and meses_tocados:
        aplicar_ia(datadir, meses=sorted(meses_tocados))
    if nuevos:
        reescribir_index(datadir)
    return nuevos


def correr_reextraer(datadir: Path) -> int:
    """Recomputa tags/grupo/campos sobre TODA la data persistida (los JSON
    guardan `texto` completo — no hace falta re-bajar PDFs). Para cuando
    evoluciona el clasificador o el extractor de campos. No toca resúmenes."""
    n = 0
    for p in sorted(datadir.glob("asfi_????-??.json")):
        mes = p.stem.replace("asfi_", "")
        data = cargar_mes(mes, datadir)
        for dia in data["dias"].values():
            for it in dia["items"]:
                it["tags"] = parser.clasificar_tags(it["texto"], it["seccion"])
                extract.enriquecer(it)
                n += 1
        guardar_mes(mes, data, datadir)
    return n


def correr_backfill(pdf_dir: Path, datadir: Path, con_ia: bool) -> int:
    conocidas = fechas_existentes(datadir)
    n = 0
    for p in sorted(pdf_dir.glob("*.pdf")):
        try:
            rep_fecha = persistir_reporte(str(p), "", p.stem, datadir, conocidas)
        except Exception as e:
            log.warning(f"backfill: {p.name} ilegible: {e!r}")
            continue
        if rep_fecha:
            n += 1
            conocidas.add(rep_fecha)
    if con_ia:
        aplicar_ia(datadir)
    if n:
        reescribir_index(datadir)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--backfill", metavar="DIR", help="parsear PDFs locales de DIR")
    ap.add_argument("--resumir", action="store_true",
                    help="solo pasar IA sobre items pendientes de la data existente")
    ap.add_argument("--reextraer", action="store_true",
                    help="recomputar tags/grupo/campos sobre la data existente (sin red ni IA)")
    ap.add_argument("--gestion", type=int,
                    default=datetime.now(timezone.utc).year)
    ap.add_argument("--sin-ia", action="store_true")
    ap.add_argument("--datadir", type=Path, default=STATIC_DIR)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    args.datadir.mkdir(parents=True, exist_ok=True)
    con_ia = not args.sin_ia

    if args.reextraer:
        n = correr_reextraer(args.datadir)
        reescribir_index(args.datadir)
        log.info(f"reextraer: {n} items recomputados")
        return 0
    if args.resumir:
        n = aplicar_ia(args.datadir)
        reescribir_index(args.datadir)
        log.info(f"resumir: {n} items promovidos a IA")
        return 0
    if args.backfill:
        n = correr_backfill(Path(args.backfill), args.datadir, con_ia)
        log.info(f"backfill: {n} reportes nuevos")
        return 0

    n = correr_diario(args.gestion, args.datadir, con_ia)
    log.info(f"diario: {n} reportes nuevos")
    # HC ping (opcional): el wrapper de cron pinguea HC_ASFI si está seteado —
    # acá solo el exit code. 0 también cuando no hay reporte nuevo (feriados).
    return 0


if __name__ == "__main__":
    sys.exit(main())
