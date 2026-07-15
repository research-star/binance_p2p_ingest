#!/usr/bin/env python3
"""
test_noticias_funnel_log.py — Aceptación del log de salidas del funnel (PR1).

Verifica, sobre DBs temporales (NUNCA prod), stubs de modelo/scraper:
  A. Poblaciones: no_calificada (con su puntaje), dedupe_inter_dia, evento_absorbida
     (con representante_id). Las insertadas NO dejan fila.
  B. Colisiones de id NO se registran. Dedup por URL: una nota vista 2× deja 1 fila.
  C. Purga TTL idempotente.
  D. penalizado_por atribuido por evaluar (un ×0.3 muere con descartado_por='umbral'
     pero penalizado_por dice la CAUSA real = la categoría).

Uso:  python scripts/test_noticias_funnel_log.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest_noticias
from noticias_ingest import scraper


def _cand(link, titulo, puntaje, tema="General", entidades=None, penal=""):
    return {
        "portal": "El Deber", "link": link, "titulo": titulo,
        "descripcion": "", "cuerpo": "", "tema": tema,
        "puntaje": puntaje, "score_crudo": round(puntaje / 10, 4),
        "score_ajustado": round(puntaje / 10, 4), "image_url": "",
        "entidades": entidades or [], "penalizado_por": penal, "taxonomia_v": 1,
    }


def _rows(conn):
    return list(conn.execute(
        "SELECT url, salida, puntaje, penalizado_por, taxonomia_v, representante_id "
        "FROM noticias_funnel_log"))


def run():
    errores = []
    tmp = Path(tempfile.mkdtemp(prefix="fb_funnel_log_test_"))
    scraper.get_modelo = lambda: SimpleNamespace(disponible=True, motivo_rechazo="")
    scraper.CACHE_DB_PATH = tmp / "cache_urls.db"

    ahora = datetime.now(timezone.utc)
    fecha_bo = ahora.astimezone(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d")

    # ── Escenario A: poblaciones ──────────────────────────────────────────────
    INS = "https://eldeber.com.bo/economia/insertada_1790000000"
    NOCAL = "https://eldeber.com.bo/economia/nocalifico_1790000001"
    DEDUP = "https://eldeber.com.bo/economia/dedupe-loser_1790000002"
    REP = "https://eldeber.com.bo/economia/evento-rep_1790000003"
    ABS = "https://eldeber.com.bo/economia/evento-absorbida_1790000004"
    DUP_TITLE = "Exportaciones de soya crecen 12% segun el IBCE este año"
    EVENTO_T = "YPFB anuncia inversion millonaria en pozos de gas en Tarija"
    cands_A = [
        _cand(INS, "Reservas internacionales del BCB suben tras nuevo credito externo", 8.2),
        _cand(NOCAL, "Nota economica de bajo puntaje sobre tramites varios menores", 4.3),
        _cand(DEDUP, DUP_TITLE, 7.8),
        _cand(REP, EVENTO_T, 7.5, entidades=["YPFB"]),
        _cand(ABS, EVENTO_T + " (ampliacion)", 7.4, entidades=["YPFB"]),
    ]
    scraper.correr_scraper = lambda *a, **k: (cands_A, [], ["El Deber"], [])
    db_a = tmp / "a.db"
    conn = sqlite3.connect(str(db_a))
    ingest_noticias.init_schema(conn)
    args = SimpleNamespace(umbral=6.7, top=10, top_latam=8, dry_run=False)
    res = ingest_noticias.lane_bolivia(conn, args, ahora, fecha_bo,
                                       previos=[(DUP_TITLE, set())])
    log = {r[0]: r for r in _rows(conn)}
    conn.close()

    if res["estado"] != "ok":
        errores.append(f"A: lane estado={res['estado']} detalle={res.get('detalle')}")
    # Insertada NO deja fila
    if INS in log:
        errores.append(f"A: la insertada NO debe estar en el log ({log.get(INS)})")
    # no_calificada CON su puntaje
    if NOCAL not in log or log[NOCAL][1] != "no_calificada":
        errores.append(f"A: no_calificada ausente/mal ({log.get(NOCAL)})")
    elif abs(log[NOCAL][2] - 4.3) > 1e-6:
        errores.append(f"A: no_calificada sin su puntaje real ({log[NOCAL][2]}, esperado 4.3)")
    # dedupe-loser
    if DEDUP not in log or log[DEDUP][1] != "dedupe_inter_dia":
        errores.append(f"A: dedupe_inter_dia ausente/mal ({log.get(DEDUP)})")
    # evento_absorbida con representante_id = id del rep
    rep_id = scraper.hash_link(REP)
    if ABS not in log or log[ABS][1] != "evento_absorbida":
        errores.append(f"A: evento_absorbida ausente/mal ({log.get(ABS)})")
    elif log[ABS][5] != rep_id:
        errores.append(f"A: representante_id={log[ABS][5]!r} (esperado {rep_id!r})")
    # el rep del evento se inserta → NO en el log
    if REP in log:
        errores.append(f"A: el representante del evento NO debe estar en el log ({log.get(REP)})")

    # ── Escenario B: colisiones NO se loguean + dedup por URL ─────────────────
    db_b = tmp / "b.db"
    conn = sqlite3.connect(str(db_b))
    ingest_noticias.init_schema(conn)
    COL = "https://eldeber.com.bo/economia/colision_1790000010"
    RECICLA = "https://eldeber.com.bo/economia/nocal-reciclada_1790000011"
    cands_B = [
        _cand(COL, "El FMI proyecta el deficit fiscal de Bolivia para la gestion 2026", 7.6),
        _cand(RECICLA, "Otra nota de bajo puntaje sobre gestiones administrativas menores", 3.9),
    ]
    scraper.correr_scraper = lambda *a, **k: (cands_B, [], ["El Deber"], [])
    # 1ª corrida: COL se inserta, RECICLA queda no_calificada
    ingest_noticias.lane_bolivia(conn, args, ahora, fecha_bo, previos=[])
    # 2ª corrida (misma data): COL ahora es colisión de id; RECICLA re-evaluada
    ingest_noticias.lane_bolivia(conn, args, ahora, fecha_bo, previos=[])
    log_b = {r[0]: r for r in _rows(conn)}
    n_recicla = sum(1 for r in _rows(conn) if r[0] == RECICLA)
    conn.close()

    if COL in log_b:
        errores.append(f"B: la colisión de id NO debe registrarse ({log_b.get(COL)})")
    if n_recicla != 1:
        errores.append(f"B: dedup por URL falló — RECICLA deja {n_recicla} filas (esperado 1)")

    # ── Escenario C: purga TTL idempotente ────────────────────────────────────
    db_c = tmp / "c.db"
    conn = sqlite3.connect(str(db_c))
    ingest_noticias.init_schema(conn)
    conn.execute(
        "INSERT INTO noticias_funnel_log (url, fecha, hora, portal, titulo, puntaje, "
        "salida, taxonomia_v, created_at_utc) VALUES (?,?,?,?,?,?,?,?,?)",
        ("http://viejo/1", "2020-01-01", "00:00", "X", "vieja", 0, "falta_bolivia", 1, "z"))
    conn.execute(
        "INSERT INTO noticias_funnel_log (url, fecha, hora, portal, titulo, puntaje, "
        "salida, taxonomia_v, created_at_utc) VALUES (?,?,?,?,?,?,?,?,?)",
        ("http://nuevo/1", fecha_bo, "00:00", "X", "nueva", 0, "falta_bolivia", 1, "z"))
    conn.commit()
    borradas1 = ingest_noticias.purgar_funnel_log(conn, fecha_bo, dias=30)
    borradas2 = ingest_noticias.purgar_funnel_log(conn, fecha_bo, dias=30)
    quedan = conn.execute("SELECT COUNT(*) FROM noticias_funnel_log").fetchone()[0]
    conn.close()
    if borradas1 != 1:
        errores.append(f"C: purga debía borrar 1 fila vieja, borró {borradas1}")
    if borradas2 != 0:
        errores.append(f"C: purga NO idempotente — 2ª pasada borró {borradas2} (esperado 0)")
    if quedan != 1:
        errores.append(f"C: debía quedar 1 fila (<30d), quedan {quedan}")

    # ── Escenario E: dedup por URL sobre las 2 poblaciones que RECICLAN ───────
    #    (kills de evaluar + absorbidas por evento): re-evaluadas 2× dejan 1 fila.
    db_e = tmp / "e.db"
    conn = sqlite3.connect(str(db_e))
    ingest_noticias.init_schema(conn)
    KILL = "https://eldeber.com.bo/deportes/champions_1790000020"
    E_REP = "https://eldeber.com.bo/economia/evento2-rep_1790000021"
    E_ABS = "https://eldeber.com.bo/economia/evento2-abs_1790000022"
    E_T = "El BCB sube las reservas internacionales a un nuevo maximo historico"
    descartado = {
        "portal": "Unitel", "titulo": "Champions League: la final",
        "descripcion": "", "link": KILL, "score_crudo": 0.9, "score_ajustado": 0.27,
        "descartado_por": "umbral", "penalizado_por": "deportes", "taxonomia_v": 1,
    }
    cands_E = [
        _cand(E_REP, E_T, 7.5, entidades=["BCB"]),
        _cand(E_ABS, E_T + " segun el informe", 7.4, entidades=["BCB"]),
    ]
    scraper.correr_scraper = lambda *a, **k: (cands_E, [descartado], ["El Deber"], [])
    ingest_noticias.lane_bolivia(conn, args, ahora, fecha_bo, previos=[])
    ingest_noticias.lane_bolivia(conn, args, ahora, fecha_bo, previos=[])
    n_kill = sum(1 for r in _rows(conn) if r[0] == KILL)
    n_abs = sum(1 for r in _rows(conn) if r[0] == E_ABS)
    kill_row = next((r for r in _rows(conn) if r[0] == KILL), None)
    conn.close()
    if n_kill != 1:
        errores.append(f"E: kill reciclado deja {n_kill} filas (esperado 1 — dedup por URL)")
    if kill_row and (kill_row[1] != "umbral_modelo" or kill_row[3] != "deportes"):
        errores.append(f"E: kill mal atribuido salida={kill_row[1]!r} penalizado_por={kill_row[3]!r} "
                       f"(esperado 'umbral_modelo'/'deportes')")
    if n_abs != 1:
        errores.append(f"E: absorbida reciclada deja {n_abs} filas (esperado 1 — dedup por URL)")

    # ── Escenario D: penalizado_por atribuido por evaluar (modelo REAL) ────────
    import importlib
    importlib.reload(scraper)   # restaura get_modelo/correr_scraper reales para el modelo
    if scraper.get_modelo().disponible:
        r = scraper.evaluar("Champions League: la gran final en La Paz, Bolivia", "", "El Deber")
        # descartado_por (idx 7), penalizado_por (idx 8)
        if r[8] != "deportes":
            errores.append(f"D: penalizado_por={r[8]!r} (esperado 'deportes') | descartado_por={r[7]!r}")
        limpia = scraper.evaluar("El BCB informa el nivel de reservas internacionales de Bolivia", "", "El Deber")
        if limpia[8] != "":
            errores.append(f"D: nota limpia debía tener penalizado_por='' (dio {limpia[8]!r})")
    else:
        print("   (D saltado: modelo TF-IDF no disponible localmente)")

    if errores:
        print("FALLÓ test_noticias_funnel_log:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_noticias_funnel_log: A poblaciones (no_calificada+puntaje, dedupe, "
          "evento_absorbida+representante_id, insertada/rep fuera) | B colisión no-logueada "
          "+ dedup-por-URL | C purga TTL idempotente | D penalizado_por atribuido.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
