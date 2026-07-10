#!/usr/bin/env python3
"""
build_agro_geojson.py — GeoJSON municipal liviano para la tab Agro.

FUENTE: geoBoundaries gbOpen BOL ADM3 (339 municipios, licencia **Public
Domain** — "Public Domain; free use and access to information"), cuyo
upstream es GeoBolivia (geo.gob.bo, límites municipales oficiales,
metadata aeeb85a9-23df-48d4-a4e5-dd19e8b206db). Reemplaza al derivado de
GADM 4.1 (licencia no comercial / sin redistribución) desde 2026-07-10.

El ADM3 de geoBoundaries trae solo `shapeName` (sin departamento), así que
el depto se asigna por SPATIAL JOIN contra el ADM1 de la misma fuente
(representative_point ∈ polígono departamental) — necesario porque hay 15
nombres de municipio duplicados entre departamentos.

CROSSWALK a nuestros gid: cada feature se matchea contra
scripts/data/agro_municipios.csv por (nombre normalizado, depto), con
fallback a los alias del CSV y a prefijo-único (el shapeName de
"La (Marka) San Andrés de Machaca" viene truncado en origen). Los gid se
conservan como CLAVES OPACAS del join con agro_produccion.json — su formato
GADM-oide es legado del fixture, no implica geometría GADM.

EXCLUSIÓN DOCUMENTADA: los 5 registros "Lago Titicaca" del CSV son
pseudo-unidades de agua heredadas de la tabla GADM (sin código INE, sin
data SIIP posible); geoBoundaries no las trae como municipios y la salida
tampoco. Features de salida esperadas: 344 - 5 = 339.

Las propiedades de salida son {gid, nombre, depto} — nombre/depto salen del
CSV (nombres bonitos, depto en canon ASCII), NO del shapeName.

Calibración: si no se pasa --tolerancia, prueba 0.002 / 0.005 / 0.01 y se
queda con la MENOR tolerancia (mayor calidad) cuyo output pese <--max-kb.

Uso:
    python scripts/build_agro_geojson.py                     # descarga la fuente
    python scripts/build_agro_geojson.py --fuente gb_ADM3.geojson --adm1 gb_ADM1.geojson
    python scripts/build_agro_geojson.py --departamental "<path>/bolivia_departamentos.geojson"
        # además copia VERBATIM el geojson departamental (Comex) a
        # static/agro_geo_departamental.json y lo verifica (9 features).
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests
from shapely.geometry import mapping, shape
from shapely.validation import make_valid
import shapely

REPO_ROOT = Path(__file__).parent.parent
MAPA_DEFAULT = REPO_ROOT / "scripts" / "data" / "agro_municipios.csv"
OUT_DEFAULT = REPO_ROOT / "static" / "agro_geo_municipal.json"
DEP_OUT_DEFAULT = REPO_ROOT / "static" / "agro_geo_departamental.json"

# Release pineado de geoBoundaries (commit 9469f09; ver
# https://www.geoboundaries.org/api/current/gbOpen/BOL/ADM3/).
GB_ADM3_URL = ("https://github.com/wmgeolab/geoBoundaries/raw/9469f09/"
               "releaseData/gbOpen/BOL/ADM3/geoBoundaries-BOL-ADM3.geojson")
GB_ADM1_URL = ("https://github.com/wmgeolab/geoBoundaries/raw/9469f09/"
               "releaseData/gbOpen/BOL/ADM1/geoBoundaries-BOL-ADM1.geojson")

TOLERANCIAS_CANDIDATAS = [0.002, 0.005, 0.01]

DEPTOS_CANON = ["Chuquisaca", "La Paz", "Cochabamba", "Oruro", "Potosi",
                "Tarija", "Santa Cruz", "Beni", "Pando"]

# Registros del CSV sin municipio real detrás (ver docstring).
NOMBRE_EXCLUIDO = "Lago Titicaca"
EXCLUIDOS_ESPERADOS = 5


def _norm(s: str) -> str:
    """lower + sin acentos + solo [a-z0-9] — misma normalización que el
    mapeo INE→gid de ingest_agro.py."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def cargar_geojson(origen: str) -> dict:
    """FeatureCollection desde path local o URL."""
    if origen.startswith("http://") or origen.startswith("https://"):
        r = requests.get(origen, timeout=180)
        r.raise_for_status()
        return json.loads(r.content.decode("utf-8"))
    return json.loads(Path(origen).read_text(encoding="utf-8"))


def cargar_mapa(path: Path) -> tuple[dict, set]:
    """agro_municipios.csv → ({gid: (nombre, depto, [alias])}, gids_excluidos).

    Los registros 'Lago Titicaca' (pseudo-unidades de agua sin INE) se
    devuelven aparte como exclusión documentada.
    """
    mapa, excluidos = {}, set()
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["nombre"] == NOMBRE_EXCLUIDO:
                if row.get("ine_codes"):
                    raise RuntimeError(
                        f"{row['gid']} '{NOMBRE_EXCLUIDO}' tiene ine_codes — "
                        "la exclusión asume que es pseudo-unidad sin data")
                excluidos.add(row["gid"])
                continue
            alias = [a for a in (row.get("alias") or "").split(";") if a]
            mapa[row["gid"]] = (row["nombre"], row["depto"], alias)
    if not mapa:
        raise RuntimeError(f"Mapa {path} vacío")
    if len(excluidos) != EXCLUIDOS_ESPERADOS:
        raise RuntimeError(f"Excluidos '{NOMBRE_EXCLUIDO}'={len(excluidos)} "
                           f"!= {EXCLUIDOS_ESPERADOS} esperados — revisar CSV")
    return mapa, excluidos


def asignar_deptos(features: list, adm1: dict) -> list:
    """Depto canon por spatial join (representative_point ∈ ADM1)."""
    depts = []
    for ft in adm1["features"]:
        nm = _norm(ft["properties"]["shapeName"])
        canon = next((c for c in DEPTOS_CANON if _norm(c) == nm
                      or nm.startswith(_norm(c))), None)
        if canon is None:
            raise RuntimeError(f"ADM1 no mapea a canon: "
                               f"{ft['properties']['shapeName']}")
        depts.append((canon, shape(ft["geometry"])))
    if len(depts) != 9:
        raise RuntimeError(f"ADM1 features={len(depts)} != 9")
    out = []
    for ft in features:
        geom = shape(ft["geometry"])
        rp = geom.representative_point()
        dep = next((d for d, poly in depts if poly.contains(rp)), None)
        if dep is None:
            raise RuntimeError(f"Sin depto: {ft['properties']['shapeName']}")
        out.append({"nombre_gb": ft["properties"]["shapeName"],
                    "dep": dep, "geom": geom})
    return out


def crosswalk(gb_feats: list, mapa: dict) -> dict:
    """{gid: geometría} matcheando (nombre normalizado, depto).

    Orden de resolución: exacto → alias del CSV → prefijo único (shapeName
    truncado en origen, ej. 'La (Marka) San Andrés de Mach'). Falla ruidoso
    si un feature no matchea, matchea ambiguo, o un gid queda con dos
    geometrías.
    """
    idx = {}
    for gid, (nombre, depto, alias) in mapa.items():
        for n in [nombre] + alias:
            idx.setdefault((_norm(n), depto), set()).add(gid)

    asignado, sin_match = {}, []
    for f in gb_feats:
        key = (_norm(f["nombre_gb"]), f["dep"])
        gids = idx.get(key)
        if not gids:  # fallback: prefijo único dentro del depto
            cand = {g for (n, d), gs in idx.items() if d == f["dep"]
                    and n.startswith(key[0]) for g in gs}
            if len(cand) == 1:
                gids = cand
                print(f"[agro-geo] prefijo-único: '{f['nombre_gb']}' "
                      f"({f['dep']}) → {next(iter(cand))}")
        if not gids:
            sin_match.append((f["nombre_gb"], f["dep"]))
            continue
        if len(gids) > 1:
            raise RuntimeError(f"Ambiguo: {f['nombre_gb']} ({f['dep']}) "
                               f"→ {sorted(gids)}")
        gid = next(iter(gids))
        if gid in asignado:
            raise RuntimeError(f"gid {gid} con dos geometrías "
                               f"({f['nombre_gb']})")
        asignado[gid] = f["geom"]
    if sin_match:
        raise RuntimeError(f"Features de la fuente sin match: {sin_match}")
    faltan = set(mapa) - set(asignado)
    if faltan:
        raise RuntimeError(f"GIDs del CSV sin geometría: {sorted(faltan)}")
    return asignado


def _contar_vertices(geom_json: dict) -> int:
    coords = geom_json["coordinates"]
    if geom_json["type"] == "Polygon":
        return sum(len(r) for r in coords)
    return sum(len(r) for poly in coords for r in poly)


def _redondear(obj, dec: int):
    """Redondeo recursivo de coordenadas (limpia el repr float post-GEOS)."""
    if isinstance(obj, (list, tuple)):
        return [_redondear(x, dec) for x in obj]
    return round(obj, dec)


def simplificar_feature(geom, tolerancia: float, dec: int):
    """simplify + snap a grilla de 10^-dec con salida válida garantizada.

    set_precision (GEOS) colapsa vértices duplicados y repara la topología
    que el redondeo podría romper. Si la simplificación vacía la geometría
    (no debería con preserve_topology), cae a la original sin simplificar.
    """
    if not geom.is_valid:
        geom = make_valid(geom)
    simple = geom.simplify(tolerancia, preserve_topology=True)
    if simple.is_empty:
        simple = geom
    grid = 10 ** -dec
    ajustada = shapely.set_precision(simple, grid_size=grid)
    if ajustada.is_empty or not ajustada.is_valid:
        ajustada = shapely.set_precision(make_valid(simple), grid_size=grid)
    if ajustada.is_empty:
        raise RuntimeError("Geometría vacía tras set_precision")
    return ajustada


def construir(asignado: dict, mapa: dict, tolerancia: float, dec: int):
    """FeatureCollection de salida + stats (vertices in/out, bbox)."""
    out_features = []
    v_in = v_out = 0
    bbox = [180.0, 90.0, -180.0, -90.0]
    for gid in sorted(asignado):
        nombre, depto, _ = mapa[gid]
        geom_in = asignado[gid]
        v_in += _contar_vertices(mapping(geom_in))
        geom = simplificar_feature(geom_in, tolerancia, dec)
        gj = mapping(geom)
        gj = {"type": gj["type"],
              "coordinates": _redondear(gj["coordinates"], dec)}
        if gj["type"] == "Polygon":   # normalizar: salida homogénea
            gj = {"type": "MultiPolygon", "coordinates": [gj["coordinates"]]}
        if gj["type"] != "MultiPolygon":
            raise RuntimeError(f"{gid}: tipo inesperado {gj['type']} "
                               f"tras simplificar")
        v_out += _contar_vertices(gj)
        minx, miny, maxx, maxy = geom.bounds
        bbox = [min(bbox[0], minx), min(bbox[1], miny),
                max(bbox[2], maxx), max(bbox[3], maxy)]
        out_features.append({"type": "Feature",
                             "properties": {"gid": gid, "nombre": nombre,
                                            "depto": depto},
                             "geometry": gj})
    fc = {"type": "FeatureCollection", "features": out_features}
    return fc, {"v_in": v_in, "v_out": v_out, "bbox": [round(b, 3) for b in bbox]}


def validar(fc: dict, mapa: dict):
    """Asserts post-build: features == gids del mapa (sin excluidos),
    gids completos, geometrías sanas."""
    feats = fc["features"]
    if len(feats) != len(mapa):
        raise RuntimeError(f"features={len(feats)} != mapa={len(mapa)}")
    gids = {f["properties"]["gid"] for f in feats}
    faltan = set(mapa) - gids
    if faltan:
        raise RuntimeError(f"GIDs del CSV ausentes en el geojson: {sorted(faltan)[:5]}")
    for f in feats:
        g = shape(f["geometry"])
        if g.is_empty:
            raise RuntimeError(f"{f['properties']['gid']}: geometría vacía")
        if not g.is_valid:
            raise RuntimeError(f"{f['properties']['gid']}: geometría inválida")


def copiar_departamental(src: Path, dst: Path):
    """Copia VERBATIM (byte a byte) el geojson departamental de Comex y
    verifica 9 features con properties.name == canon ASCII de 9 deptos."""
    raw = src.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    nombres = sorted(f["properties"]["name"] for f in doc["features"])
    if len(doc["features"]) != 9 or nombres != sorted(DEPTOS_CANON):
        raise RuntimeError(f"Departamental inesperado: n={len(doc['features'])} "
                           f"names={nombres}")
    dst.write_bytes(raw)
    if dst.read_bytes() != raw:
        raise RuntimeError("Copia departamental no es byte-a-byte")
    print(f"[agro-geo] departamental copiado verbatim → {dst} "
          f"({len(raw)} bytes, 9 features OK)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GeoJSON municipal simplificado para la tab Agro "
                    "(fuente geoBoundaries/GeoBolivia, Public Domain)")
    parser.add_argument("--fuente", default=GB_ADM3_URL,
                        help="Path local o URL del ADM3 de geoBoundaries "
                             f"(default: {GB_ADM3_URL})")
    parser.add_argument("--adm1", default=GB_ADM1_URL,
                        help="Path local o URL del ADM1 (spatial join de "
                             f"deptos; default: {GB_ADM1_URL})")
    parser.add_argument("--mapa", type=Path, default=MAPA_DEFAULT,
                        help=f"CSV de nombres bonitos (default {MAPA_DEFAULT})")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT,
                        help=f"Salida (default {OUT_DEFAULT})")
    parser.add_argument("--tolerancia", type=float, default=None,
                        help="Tolerancia simplify; default: calibra "
                             f"{TOLERANCIAS_CANDIDATAS} y elige la menor "
                             "que cumpla --max-kb")
    parser.add_argument("--decimales", type=int, default=3,
                        help="Decimales de coordenadas (default 3, ~111 m)")
    parser.add_argument("--max-kb", type=int, default=800,
                        help="Presupuesto de peso crudo en KB (default 800)")
    parser.add_argument("--departamental", type=Path, default=None,
                        help="Si se pasa: copia VERBATIM ese geojson a "
                             f"{DEP_OUT_DEFAULT} y lo verifica")
    args = parser.parse_args()

    adm3 = cargar_geojson(args.fuente)
    adm1 = cargar_geojson(args.adm1)
    mapa, excluidos = cargar_mapa(args.mapa)
    print(f"[agro-geo] fuente ADM3 features={len(adm3['features'])} "
          f"mapa gids={len(mapa)} (+{len(excluidos)} excluidos "
          f"'{NOMBRE_EXCLUIDO}')")

    gb_feats = asignar_deptos(adm3["features"], adm1)
    asignado = crosswalk(gb_feats, mapa)
    print(f"[agro-geo] crosswalk: {len(asignado)}/{len(mapa)} gids con "
          f"geometría")

    candidatas = ([args.tolerancia] if args.tolerancia is not None
                  else TOLERANCIAS_CANDIDATAS)
    elegido = None
    for tol in candidatas:
        fc, stats = construir(asignado, mapa, tol, args.decimales)
        cuerpo = json.dumps(fc, separators=(",", ":"), ensure_ascii=False)
        peso = len(cuerpo.encode("utf-8"))
        print(f"[agro-geo] tolerancia={tol} vertices={stats['v_in']}→"
              f"{stats['v_out']} bytes={peso} bbox={stats['bbox']}")
        if peso < args.max_kb * 1024:
            elegido = (tol, fc, cuerpo, peso, stats)
            break
    if elegido is None:
        print(f"[agro-geo] mode=error detail=ninguna tolerancia de "
              f"{candidatas} baja de {args.max_kb} KB", file=sys.stderr)
        return 1

    tol, fc, cuerpo, peso, stats = elegido
    validar(fc, mapa)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(cuerpo, encoding="utf-8")
    print(f"[agro-geo] mode=ok tolerancia={tol} features={len(fc['features'])} "
          f"vertices={stats['v_in']}→{stats['v_out']} bytes={peso} "
          f"bbox={stats['bbox']} out={args.out}")

    if args.departamental:
        copiar_departamental(args.departamental, DEP_OUT_DEFAULT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
