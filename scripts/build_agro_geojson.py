#!/usr/bin/env python3
"""
build_agro_geojson.py — GeoJSON municipal liviano para la tab Agro.

Toma el nivel 3 de GADM 4.1 para Bolivia (344 municipios, MultiPolygon),
lo simplifica con shapely (preserve_topology) y redondea coordenadas para
bajar de ~1.9 MB a <800 KB crudo, manteniendo las 344 features válidas.

Las propiedades de salida son {gid, nombre, depto} — nombre/depto salen de
scripts/data/agro_municipios.csv (nombres bonitos con espacios/acentos y
depto en canon ASCII), NO del GADM .json (que trae nombres sin espacios,
artefacto del export).

Calibración: si no se pasa --tolerancia, prueba 0.002 / 0.005 / 0.01 y se
queda con la MENOR tolerancia (mayor calidad) cuyo output pese <--max-kb.

Uso:
    python scripts/build_agro_geojson.py --gadm <path o URL del .json[.zip]>
    python scripts/build_agro_geojson.py --gadm gadm41_BOL_3.json \
        --departamental "<path>/bolivia_departamentos.geojson"
        # además copia VERBATIM el geojson departamental (Comex) a
        # static/agro_geo_departamental.json y lo verifica (9 features).
"""

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import requests
from shapely.geometry import mapping, shape
from shapely.validation import make_valid
import shapely

REPO_ROOT = Path(__file__).parent.parent
MAPA_DEFAULT = REPO_ROOT / "scripts" / "data" / "agro_municipios.csv"
OUT_DEFAULT = REPO_ROOT / "static" / "agro_geo_municipal.json"
DEP_OUT_DEFAULT = REPO_ROOT / "static" / "agro_geo_departamental.json"

GADM_URL = ("https://geodata.ucdavis.edu/gadm/gadm4.1/json/"
            "gadm41_BOL_3.json.zip")

TOLERANCIAS_CANDIDATAS = [0.002, 0.005, 0.01]

DEPTOS_CANON = ["Chuquisaca", "La Paz", "Cochabamba", "Oruro", "Potosi",
                "Tarija", "Santa Cruz", "Beni", "Pando"]


def cargar_gadm(origen: str) -> dict:
    """Lee el FeatureCollection GADM desde path local o URL (.json o .zip)."""
    if origen.startswith("http://") or origen.startswith("https://"):
        r = requests.get(origen, timeout=120)
        r.raise_for_status()
        contenido = r.content
        if origen.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                nombre = next(n for n in z.namelist() if n.endswith(".json"))
                contenido = z.read(nombre)
        return json.loads(contenido.decode("utf-8"))
    path = Path(origen)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            nombre = next(n for n in z.namelist() if n.endswith(".json"))
            return json.loads(z.read(nombre).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def cargar_mapa(path: Path) -> dict:
    """agro_municipios.csv → {gid: (nombre, depto)}."""
    import csv
    out = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["gid"]] = (row["nombre"], row["depto"])
    if not out:
        raise RuntimeError(f"Mapa {path} vacío")
    return out


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


def construir(features: list, mapa: dict, tolerancia: float, dec: int):
    """FeatureCollection de salida + stats (vertices in/out, bbox)."""
    out_features = []
    v_in = v_out = 0
    bbox = [180.0, 90.0, -180.0, -90.0]
    for f in features:
        gid = f["properties"]["GID_3"]
        if gid not in mapa:
            raise RuntimeError(f"GID {gid} del GADM no está en el mapa CSV")
        nombre, depto = mapa[gid]
        geom_in = shape(f["geometry"])
        v_in += _contar_vertices(f["geometry"])
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
    """Asserts post-build: 344 features, gids completos, geometrías sanas."""
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
        description="GeoJSON municipal simplificado para la tab Agro")
    parser.add_argument("--gadm", required=True,
                        help=f"Path local o URL del GADM nivel 3 "
                             f"(.json o .json.zip; ej. {GADM_URL})")
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

    gadm = cargar_gadm(args.gadm)
    features = gadm["features"]
    mapa = cargar_mapa(args.mapa)
    print(f"[agro-geo] GADM features={len(features)} mapa gids={len(mapa)}")

    candidatas = ([args.tolerancia] if args.tolerancia is not None
                  else TOLERANCIAS_CANDIDATAS)
    elegido = None
    for tol in candidatas:
        fc, stats = construir(features, mapa, tol, args.decimales)
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
