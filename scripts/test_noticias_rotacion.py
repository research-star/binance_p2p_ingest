#!/usr/bin/env python3
"""
test_noticias_rotacion.py — Test del ranking ROTATIVO intra-día (cupo top-50, PR B).

Verifica el compare-and-evict que reemplaza al budget aditivo: con el cupo lleno,
una candidata de MAYOR score EVICTA (DELETE físico) a la de menor score del DÍA, y
solo entonces se inserta. Cubre las invariantes críticas del PRIMER borrado físico
de la tabla noticias, incluidas las dos rutas de fallo que halló la revisión
adversarial (colisión de PK cross-día net-negativa; orden roto por agrupar_eventos):

  A (rotación)   — la ganadora evicta a la de menor score; la evictada DESAPARECE y
                   queda vista; otro-día y Latam intactos; perdedora-por-mínimo
                   reconsiderable; resumen_ia SOLO se invoca sobre las insertadas.
  B (aditivo)    — con lugar en el cupo (< top) no evicta nada.
  C (colisión)   — candidata cuya URL ya existe en OTRO día NO dispara evicción
                   (nada de borrar-sin-reemplazo); el cupo del día no baja.
  D (orden)      — con agrupar_eventos reordenando por gmax, la candidata de mayor
                   puntaje-representante igual evicta (no se pierde por un break
                   prematuro ni provoca un DELETE de un id no commiteado).

Corre sobre DBs temporales (NUNCA la prod). No toca red ni el modelo real (stubs).
Uso:  python scripts/test_noticias_rotacion.py
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
from noticias_ingest import scraper, resumen_ia
from noticias_ingest.transform import build_nota


def _cand(link, titulo, puntaje, portal="El Deber"):
    return {
        "portal": portal, "link": link, "titulo": titulo,
        "descripcion": "", "cuerpo": "", "tema": "General",
        "puntaje": puntaje, "score_crudo": None, "score_ajustado": None,
        "image_url": "",
    }


def _seed(conn, ahora, link, titulo, puntaje, *, date=None, carril="bolivia", portal="El Deber"):
    """Inserta una nota-semilla directamente (simula corridas previas)."""
    nota = build_nota(_cand(link, titulo, puntaje, portal), ahora)
    if date is not None:
        nota["date"] = date
    nota["carril"] = carril
    ingest_noticias.insertar_notas(conn, [nota])
    return nota["id"]


def _fechas(ahora):
    bo = ahora.astimezone(timezone(timedelta(hours=-4)))
    return bo.strftime("%Y-%m-%d"), (bo - timedelta(days=1)).strftime("%Y-%m-%d")


def _bo_hoy_count(conn, fecha_bo):
    return conn.execute(
        f"SELECT COUNT(*) FROM noticias WHERE date = ? AND {ingest_noticias.CARRIL_SQL} != 'latam'",
        (fecha_bo,)).fetchone()[0]


def _exists(conn, nid):
    return conn.execute("SELECT 1 FROM noticias WHERE id = ?", (nid,)).fetchone() is not None


def _newdb(prefix):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    scraper.CACHE_DB_PATH = tmp / "cache_urls.db"
    conn = sqlite3.connect(str(tmp / "test.db"))
    ingest_noticias.init_schema(conn)
    return conn, tmp


def _vistas(cache_path):
    c = sqlite3.connect(str(cache_path)); v = {r[0] for r in c.execute("SELECT url FROM urls_vistas").fetchall()}
    c.close(); return v


def _run_stub_scraper(cands):
    scraper.correr_scraper = lambda *a, **k: (cands, [], ["El Deber"], [])


# ── A: rotación + controles + spy de resumen ─────────────────────────────────
def test_rotacion_y_resumen(ahora, fecha_bo, ayer):
    err = []
    scraper.get_modelo = lambda: SimpleNamespace(disponible=True, motivo_rechazo="")
    conn, tmp = _newdb("fb_rot_A_")

    URL_9 = "https://eldeber.com.bo/economia/alta_1000000001"
    URL_8 = "https://eldeber.com.bo/economia/media_1000000002"
    URL_7 = "https://eldeber.com.bo/economia/minima_1000000003"   # ← menor score (evictable)
    URL_AYER = "https://eldeber.com.bo/economia/ayer_1000000004"
    URL_LATAM = "https://eldeber.com.bo/economia/latam_1000000005"
    _seed(conn, ahora, URL_9, "Reservas del BCB suben tras credito multilateral", 9.0)
    _seed(conn, ahora, URL_8, "El FMI proyecta el deficit fiscal de Bolivia 2026", 8.0)
    id7 = _seed(conn, ahora, URL_7, "Aduana reporta variacion en recaudacion trimestral", 7.0)
    id_ayer = _seed(conn, ahora, URL_AYER, "Nota vieja de bajo score del dia anterior", 1.0, date=ayer)
    id_latam = _seed(conn, ahora, URL_LATAM, "Nota internacional de Bloomberg Latam", 0.0, carril="latam")

    URL_WIN = "https://eldeber.com.bo/economia/ganadora_1000000006"
    URL_LOSE = "https://eldeber.com.bo/economia/perdedora_1000000007"
    cands = [
        _cand(URL_WIN, "YPFB anuncia nuevo contrato de exportacion de gas", 8.5),
        _cand(URL_LOSE, "Tramites municipales varios sin impacto mayor", 6.8),
    ]
    _run_stub_scraper(cands)
    id_win = build_nota(cands[0], ahora)["id"]
    id_lose = build_nota(cands[1], ahora)["id"]

    # Spy: registra sobre qué notas se invoca resumen_ia (no-op real, no gasta API).
    spied = {"urls": None}
    orig = resumen_ia.aplicar
    def _spy(notas, **kw):
        spied["urls"] = [n["url"] for n in notas]
        return 0
    ingest_noticias.resumen_ia.aplicar = _spy
    try:
        res = ingest_noticias.lane_bolivia(conn, SimpleNamespace(umbral=6.7, top=3, top_latam=8, dry_run=False),
                                           ahora, fecha_bo, previos=[])
    finally:
        ingest_noticias.resumen_ia.aplicar = orig

    if res["insertadas"] != 1: err.append(f"A: insertadas={res['insertadas']} (esp 1)")
    if res["evictadas"] != 1: err.append(f"A: evictadas={res['evictadas']} (esp 1)")
    if _exists(conn, id7): err.append("A: la de menor score (7.0) debia ser EVICTADA")
    if not _exists(conn, id_win): err.append("A: la ganadora debia insertarse")
    if _exists(conn, id_lose): err.append("A: la perdedora-por-minimo NO debia insertarse")
    if _bo_hoy_count(conn, fecha_bo) != 3: err.append(f"A: BO-hoy={_bo_hoy_count(conn, fecha_bo)} (esp 3)")
    if not _exists(conn, id_ayer): err.append("A: BUG CRITICO: se borro nota de OTRO DIA")
    if not _exists(conn, id_latam): err.append("A: BUG CRITICO: se borro nota LATAM")
    # Spy: resumen SOLO sobre la ganadora insertada, NUNCA sobre la perdedora-por-minimo.
    if spied["urls"] != [URL_WIN]:
        err.append(f"A: resumen_ia recibio {spied['urls']} (esp solo la ganadora {URL_WIN})")
    v = _vistas(scraper.CACHE_DB_PATH)
    if URL_WIN not in v: err.append("A: la ganadora debia estar vista")
    if URL_7 not in v: err.append("A: la EVICTADA debia marcarse vista")
    if URL_LOSE in v: err.append("A: BUG: la perdedora-por-minimo quedo vista (no reconsiderable)")
    conn.close()
    return err


# ── B: aditivo (con lugar no evicta) ─────────────────────────────────────────
def test_aditivo(ahora, fecha_bo):
    err = []
    scraper.get_modelo = lambda: SimpleNamespace(disponible=True, motivo_rechazo="")
    conn, tmp = _newdb("fb_rot_B_")
    cands = [
        _cand("https://eldeber.com.bo/economia/a_1", "Exportaciones de soya crecen segun el IBCE", 8.0),
        _cand("https://eldeber.com.bo/economia/b_2", "Inversion en infraestructura vial anunciada", 7.5),
        _cand("https://eldeber.com.bo/economia/c_3", "CAINCO proyecta crecimiento del PIB regional", 7.2),
    ]
    _run_stub_scraper(cands)
    res = ingest_noticias.lane_bolivia(conn, SimpleNamespace(umbral=6.7, top=50, top_latam=8, dry_run=False),
                                       ahora, fecha_bo, previos=[])
    if res["insertadas"] != 3: err.append(f"B: insertadas={res['insertadas']} (esp 3)")
    if res["evictadas"] != 0: err.append(f"B: evictadas={res['evictadas']} (esp 0, con lugar no evicta)")
    conn.close()
    return err


# ── C: colisión de id cross-día (regresión del blocker net-negativo) ─────────
def test_colision_cross_dia(ahora, fecha_bo, ayer):
    err = []
    scraper.get_modelo = lambda: SimpleNamespace(disponible=True, motivo_rechazo="")
    conn, tmp = _newdb("fb_rot_C_")
    # Cupo lleno HOY (cap=2), min=7.0.
    _seed(conn, ahora, "https://eldeber.com.bo/economia/hoy-a_2000000001", "Nota alta del dia de hoy uno", 8.0)
    id_min = _seed(conn, ahora, "https://eldeber.com.bo/economia/hoy-b_2000000002", "Nota minima del dia de hoy dos", 7.0)
    # Nota de AYER con una URL específica; la candidata de HOY comparte ESA URL (mismo id).
    URL_X = "https://eldeber.com.bo/economia/colision_2000000003"
    id_ayer = _seed(conn, ahora, URL_X, "Nota de ayer que reaparece hoy con mismo enlace", 2.0, date=ayer)
    cands = [_cand(URL_X, "Titulo nuevo hoy pero MISMA url que la de ayer", 9.0)]  # score alto, colisiona por id
    _run_stub_scraper(cands)

    res = ingest_noticias.lane_bolivia(conn, SimpleNamespace(umbral=6.7, top=2, top_latam=8, dry_run=False),
                                       ahora, fecha_bo, previos=[])
    if res["evictadas"] != 0:
        err.append(f"C: evictadas={res['evictadas']} (esp 0: una colision NO debe evictar)")
    if res["insertadas"] != 0:
        err.append(f"C: insertadas={res['insertadas']} (esp 0: id ya existe → INSERT OR IGNORE)")
    if not _exists(conn, id_min):
        err.append("C: BUG CRITICO net-negativo: se borro la fila de menor score sin reemplazo")
    if not _exists(conn, id_ayer):
        err.append("C: la nota de ayer (mismo id) no debia tocarse")
    if _bo_hoy_count(conn, fecha_bo) != 2:
        err.append(f"C: BO-hoy={_bo_hoy_count(conn, fecha_bo)} (esp 2: el cupo NO debe encoger)")
    conn.close()
    return err


# ── D: orden tras agrupar_eventos (regresión del break/DELETE-fantasma) ──────
def test_orden_post_agrupar(ahora, fecha_bo):
    err = []
    scraper.get_modelo = lambda: SimpleNamespace(disponible=True, motivo_rechazo="")
    conn, tmp = _newdb("fb_rot_D_")
    # Cupo lleno HOY (cap=2), min=7.0.
    _seed(conn, ahora, "https://eldeber.com.bo/economia/d-alta_3000000001", "Nota alta ocho del dia", 8.0)
    id_min = _seed(conn, ahora, "https://eldeber.com.bo/economia/d-min_3000000002", "Nota minima siete del dia", 7.0)
    # A y B agrupan (mismo titulo); rep = El Deber (tier 2 < Unitel tier 3) con puntaje BAJO 6.9,
    # gmax del grupo = 9.0 → agrupar_eventos lo ordena ARRIBA por gmax pese a rep-puntaje 6.9.
    TIT = "Gobierno y gremios firman acuerdo sobre combustibles en La Paz"
    A = _cand("https://eldeber.com.bo/economia/grupo-a_3000000003", TIT, 6.9, portal="El Deber")
    B = _cand("https://unitel.bo/economia/grupo-b_3000000004", TIT, 9.0, portal="Unitel")
    # C standalone, puntaje 7.5 (> min 7.0): DEBE evictar al 7.0 pese a ordenar detras por gmax.
    URL_C = "https://eldeber.com.bo/economia/standalone-c_3000000005"
    C = _cand(URL_C, "Banco Central publica nuevas cifras de reservas internacionales", 7.5)
    _run_stub_scraper([A, B, C])
    id_c = build_nota(C, ahora)["id"]

    res = ingest_noticias.lane_bolivia(conn, SimpleNamespace(umbral=6.7, top=2, top_latam=8, dry_run=False),
                                       ahora, fecha_bo, previos=[])
    # Con el fix (re-sort por -puntaje tras agrupar), C@7.5 evicta al 7.0; sin el fix,
    # el rep@6.9 ordena primero, rompe el break y C se pierde (insertadas=0).
    if res["insertadas"] != 1:
        err.append(f"D: insertadas={res['insertadas']} (esp 1: C@7.5 debe entrar pese al orden por gmax)")
    if res["evictadas"] != 1:
        err.append(f"D: evictadas={res['evictadas']} (esp 1)")
    if not _exists(conn, id_c):
        err.append("D: la standalone C@7.5 debia insertarse (evictando al 7.0)")
    if _exists(conn, id_min):
        err.append("D: el 7.0 debia ser evictado por C@7.5")
    conn.close()
    return err


def run():
    ahora = datetime.now(timezone.utc)
    fecha_bo, ayer = _fechas(ahora)
    errores = []
    errores += test_rotacion_y_resumen(ahora, fecha_bo, ayer)
    errores += test_aditivo(ahora, fecha_bo)
    errores += test_colision_cross_dia(ahora, fecha_bo, ayer)
    errores += test_orden_post_agrupar(ahora, fecha_bo)

    if errores:
        print("FAIL test_noticias_rotacion:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_noticias_rotacion: A rotacion+resumen-spy | B aditivo | "
          "C colision-cross-dia (net-negativo cerrado) | D orden-post-agrupar. "
          "otro-dia y Latam intactos; DELETE por id exacto.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
