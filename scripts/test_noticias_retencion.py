#!/usr/bin/env python3
"""
test_noticias_retencion.py — Tests de la retención noticias (backup 20d + borrado 30d).

Sub-tests AISLADOS (cada uno su tempdir/db/archivo), sobre DBs TEMPORALES (NUNCA prod):

  backup_20d       — archiva (marcador..umbral_20], nota COMPLETA (todas las columnas),
                     marcador avanza (incl. días sin filas), idempotente.
  borrado_survive  — GARANTÍA POR CONSTRUCCIÓN: todo id borrado quedó en el JSONL; las
                     notas <= 30d NO se borran (supervivencia de datos, DELETE real).
  boundary_30d     — nota de exactamente 30d se borra; de 29d sobrevive.
  marcador_basura  — un .state con basura no envenena el rango: se re-archiva todo y
                     ningún borrado toca algo no archivado.
  dias_perdidos    — marcador muy atrasado → el backup cose el rango entero (sin gaps).
  idempotencia     — re-correr no duplica líneas ni re-borra.
  ambos_carriles   — la retención por edad borra BO y Latam por igual.

Uso:  python scripts/test_noticias_retencion.py
"""
from __future__ import annotations

import importlib
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest_noticias
from noticias_ingest.transform import build_nota
retencion = importlib.import_module("scripts.retencion_noticias")

BO = timezone(timedelta(hours=-4))


def _cand(link, titulo, puntaje, portal="El Deber"):
    return {"portal": portal, "link": link, "titulo": titulo, "descripcion": "",
            "cuerpo": "", "tema": "General", "puntaje": puntaje,
            "score_crudo": None, "score_ajustado": None, "image_url": ""}


class Sandbox:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fb_ret_"))
        self.db = self.tmp / "test.db"
        self.archive = self.tmp / "arch.jsonl"
        self.state = self.tmp / "arch.state"
        self.lock = self.tmp / "arch.lock"
        conn = sqlite3.connect(str(self.db))
        ingest_noticias.init_schema(conn)
        conn.close()

    def seed(self, ahora, edad_dias, puntaje, *, carril="bolivia"):
        fecha = (ahora.astimezone(BO) - timedelta(days=edad_dias)).strftime("%Y-%m-%d")
        link = f"https://eldeber.com.bo/economia/n-{edad_dias}d-{carril}_{9000000000+edad_dias}"
        nota = build_nota(_cand(link, f"Nota economica de {edad_dias} dias con enlace {carril}", puntaje), ahora)
        nota["date"] = fecha
        nota["carril"] = carril
        conn = sqlite3.connect(str(self.db))
        ingest_noticias.insertar_notas(conn, [nota])
        conn.close()
        return nota["id"]

    def correr(self, ahora, dry_run=False):
        return retencion.correr(self.db, archive_path=self.archive, state_path=self.state,
                                lock_path=self.lock, dry_run=dry_run, ahora_utc=ahora)

    def db_ids(self):
        conn = sqlite3.connect(str(self.db))
        ids = {r[0] for r in conn.execute("SELECT id FROM noticias").fetchall()}
        conn.close()
        return ids

    def db_cols(self):
        conn = sqlite3.connect(str(self.db))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(noticias)").fetchall()}
        conn.close()
        return cols

    def archive_lines(self):
        if not self.archive.exists():
            return []
        return [json.loads(l) for l in self.archive.read_text(encoding="utf-8").splitlines() if l.strip()]

    def archive_ids(self):
        return {a["id"] for a in self.archive_lines()}

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def _u(ahora, dias):
    return (ahora.astimezone(BO) - timedelta(days=dias)).strftime("%Y-%m-%d")


def test_backup_20d(ahora):
    err = []; sb = Sandbox()
    ids = {e: sb.seed(ahora, e, 8.0) for e in (0, 15, 20, 21, 25)}
    res = sb.correr(ahora)
    # Archiva las >= 20d (date <= umbral_20): 20,21,25. NO 0,15.
    esp = {ids[e] for e in (20, 21, 25)}
    if sb.archive_ids() != esp:
        err.append(f"backup_20d: archivadas={sb.archive_ids()} esp={esp}")
    if sb.state.read_text().strip() != _u(ahora, 20):
        err.append(f"backup_20d: marcador={sb.state.read_text().strip()} esp={_u(ahora,20)}")
    # Nota completa: TODAS las columnas del esquema presentes en cada línea.
    faltan = sb.db_cols() - set(sb.archive_lines()[0].keys())
    if faltan:
        err.append(f"backup_20d: nota archivada incompleta, faltan {faltan}")
    # Idempotente: re-correr no agrega líneas.
    n = len(sb.archive_lines())
    sb.correr(ahora)
    if len(sb.archive_lines()) != n:
        err.append(f"backup_20d: re-correr agregó líneas ({len(sb.archive_lines())}!={n})")
    sb.cleanup(); return err


def test_borrado_survive(ahora):
    err = []; sb = Sandbox()
    ids = {e: sb.seed(ahora, e, 8.0) for e in (10, 25, 30, 31, 40)}
    sb.correr(ahora)
    vivos = sb.db_ids()
    # >=30d borradas; <30d sobreviven.
    for e in (30, 31, 40):
        if ids[e] in vivos:
            err.append(f"borrado_survive: {e}d (>=30) debía borrarse")
    for e in (10, 25):
        if ids[e] not in vivos:
            err.append(f"borrado_survive: {e}d (<30) NO debía borrarse (supervivencia)")
    # GARANTÍA: todo id borrado quedó en el archivo.
    borrados = {ids[e] for e in (30, 31, 40)}
    no_archivados = borrados - sb.archive_ids()
    if no_archivados:
        err.append(f"borrado_survive: BUG CRÍTICO — borrados NO archivados: {no_archivados}")
    sb.cleanup(); return err


def test_boundary_30d(ahora):
    err = []; sb = Sandbox()
    id29 = sb.seed(ahora, 29, 8.0)
    id30 = sb.seed(ahora, 30, 8.0)
    sb.correr(ahora)
    vivos = sb.db_ids()
    if id30 in vivos:
        err.append("boundary_30d: la nota de exactamente 30d debía borrarse (date<=umbral_30)")
    if id29 not in vivos:
        err.append("boundary_30d: la nota de 29d NO debía borrarse")
    if id30 not in sb.archive_ids():
        err.append("boundary_30d: la de 30d borrada debía quedar archivada")
    sb.cleanup(); return err


def test_marcador_basura(ahora):
    err = []; sb = Sandbox()
    ids = {e: sb.seed(ahora, e, 8.0) for e in (22, 35)}
    sb.state.write_text("basura-\xff-no-fecha-zzz", encoding="utf-8")  # ordena alto lexicográficamente
    # leer_marcador debe devolver '' ante basura.
    if retencion.leer_marcador(sb.state) != "":
        err.append("marcador_basura: leer_marcador no saneó el .state")
    res = sb.correr(ahora)  # no debe lanzar
    # backup re-archiva todo <= umbral_20 (22 y 35); borrado saca 35 (archivada antes).
    if ids[22] not in sb.archive_ids():
        err.append("marcador_basura: la de 22d debía re-archivarse (marcador saneado a '')")
    if ids[35] in sb.db_ids():
        err.append("marcador_basura: la de 35d debía borrarse")
    if ids[35] not in sb.archive_ids():
        err.append("marcador_basura: BUG — la de 35d se borró sin quedar archivada")
    if sb.state.read_text().strip() != _u(ahora, 20):
        err.append("marcador_basura: el marcador no se re-escribió válido tras la corrida")
    sb.cleanup(); return err


def test_marcador_unicode(ahora):
    """.state con bytes UTF-8 INVÁLIDOS (corrupción de disco/escritura parcial) no debe
    crashear: leer_marcador lo sanea a '' y la corrida procede fail-safe."""
    err = []; sb = Sandbox()
    id35 = sb.seed(ahora, 35, 8.0)
    sb.state.write_bytes(b"corrupto\xff\xfe\x80")  # bytes no decodificables en UTF-8
    if retencion.leer_marcador(sb.state) != "":
        err.append("marcador_unicode: leer_marcador no saneó bytes inválidos")
    res = sb.correr(ahora)  # NO debe lanzar UnicodeDecodeError
    if res.get("skipped"):
        err.append("marcador_unicode: la corrida se salteó inesperadamente")
    if id35 in sb.db_ids():
        err.append("marcador_unicode: la de 35d debía borrarse tras sanear el marcador")
    if id35 not in sb.archive_ids():
        err.append("marcador_unicode: la de 35d debía quedar archivada")
    sb.cleanup(); return err


def test_dias_perdidos(ahora):
    err = []; sb = Sandbox()
    ids = {e: sb.seed(ahora, e, 8.0) for e in (21, 25, 30, 35)}
    retencion.guardar_marcador(sb.state, _u(ahora, 40))  # marcador 40d atrás (cron paró días)
    # Sólo backup (dry_run del borrado no importa acá): corremos normal y miramos el archivo.
    sb.correr(ahora)
    # backup cose (40d, umbral_20=20d]: date>umbral_40 AND date<=umbral_20 → 21,25,30,35 (todas).
    esp = {ids[e] for e in (21, 25, 30, 35)}
    if not esp.issubset(sb.archive_ids()):
        err.append(f"dias_perdidos: el backup no cosió el rango; faltan {esp - sb.archive_ids()}")
    sb.cleanup(); return err


def test_idempotencia(ahora):
    err = []; sb = Sandbox()
    {e: sb.seed(ahora, e, 8.0) for e in (22, 35)}
    r1 = sb.correr(ahora)
    n = len(sb.archive_lines())
    r2 = sb.correr(ahora)
    if len(sb.archive_lines()) != n:
        err.append(f"idempotencia: 2da corrida agregó líneas ({len(sb.archive_lines())}!={n})")
    if r2["backup"]["archivadas"] != 0:
        err.append(f"idempotencia: 2da corrida archivó {r2['backup']['archivadas']} (esp 0)")
    if r2["borrado"]["borradas"] != 0:
        err.append(f"idempotencia: 2da corrida borró {r2['borrado']['borradas']} (esp 0)")
    sb.cleanup(); return err


def test_delete_selfarchive_gap(ahora):
    """El caso que hallaron los reviewers: una nota >30d que el backup de 20d NUNCA archivó
    (marcador ADELANTADO de su fecha — restore/desync/backfill). El self-archive del borrado
    DEBE archivarla antes de borrarla. Sin ese fix, se borraría sin quedar en el archivo."""
    err = []; sb = Sandbox()
    id35 = sb.seed(ahora, 35, 8.0)
    # Marcador 25d atrás: por delante de la fecha de la nota (35d) → el backup la salta (date>marcador).
    retencion.guardar_marcador(sb.state, _u(ahora, 25))
    sb.correr(ahora)
    # backup NO la archivó (date < marcador); el borrado SÍ (self-archive) y la borró.
    if id35 in sb.db_ids():
        err.append("selfarchive_gap: la de 35d debía borrarse")
    if id35 not in sb.archive_ids():
        err.append("selfarchive_gap: BUG CRÍTICO — se borró sin archivar (self-archive roto)")
    sb.cleanup(); return err


def test_ambos_carriles(ahora):
    err = []; sb = Sandbox()
    id_bo = sb.seed(ahora, 35, 8.0, carril="bolivia")
    id_lt = sb.seed(ahora, 35, 0.0, carril="latam")
    sb.correr(ahora)
    vivos = sb.db_ids()
    if id_bo in vivos or id_lt in vivos:
        err.append("ambos_carriles: la retención por edad debía borrar BO y Latam")
    if not {id_bo, id_lt}.issubset(sb.archive_ids()):
        err.append("ambos_carriles: ambas debían quedar archivadas")
    sb.cleanup(); return err


def run():
    ahora = datetime.now(timezone.utc)
    err = []
    for t in (test_backup_20d, test_borrado_survive, test_boundary_30d, test_marcador_basura,
              test_marcador_unicode, test_dias_perdidos, test_idempotencia,
              test_delete_selfarchive_gap, test_ambos_carriles):
        err += [f"{t.__name__}: {e}" for e in t(ahora)]
    if err:
        print("FAIL test_noticias_retencion:")
        for e in err:
            print("  -", e)
        return 1
    print("OK test_noticias_retencion: backup_20d (nota completa, idempotente) | borrado_survive "
          "(garantia archivo incluye-todo-borrado, <30d sobrevive) | boundary_30d | marcador_basura "
          "(fail-safe) | dias_perdidos (sin gaps) | idempotencia | ambos_carriles.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
