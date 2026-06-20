#!/usr/bin/env python3
"""Aplana un GeoJSON de líneas/polígonos a arrays {lon,lat} con None entre
segmentos, para dibujarlo como una sola traza de líneas en Plotly scattergeo
(mucho más liviano que pasar el GeoJSON completo).

Uso:
    flatten_geo.py <rutas.geojson> <departamentos.geojson> <salida.json>

Salida: {"roads":{"lon":[...],"lat":[...]}, "deptos":{"lon":[...],"lat":[...]}}
Solo stdlib.
"""
import json
import os
import sys


def flatten(features):
    lon, lat = [], []
    for f in features:
        g = (f or {}).get("geometry") or {}
        t, c = g.get("type"), g.get("coordinates")
        if not c:
            continue
        if t == "LineString":
            segs = [c]
        elif t == "MultiLineString":
            segs = c
        elif t == "Polygon":
            segs = c                      # anillos
        elif t == "MultiPolygon":
            segs = [ring for poly in c for ring in poly]
        else:
            continue
        for seg in segs:
            for p in seg:
                lon.append(round(p[0], 3))
                lat.append(round(p[1], 3))
            lon.append(None)              # corte entre segmentos
            lat.append(None)
    return {"lon": lon, "lat": lat}


def main():
    if len(sys.argv) != 4:
        sys.exit("uso: flatten_geo.py <rutas.geojson> <deptos.geojson> <salida.json>")
    rvf_p, dep_p, out_p = sys.argv[1], sys.argv[2], sys.argv[3]
    rvf = json.load(open(rvf_p, encoding="utf-8"))
    dep = json.load(open(dep_p, encoding="utf-8"))
    out = {
        "roads": flatten(rvf.get("features", [])),
        "deptos": flatten(dep.get("features", [])),
    }
    os.makedirs(os.path.dirname(out_p) or ".", exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(
        f"roads pts: {len(out['roads']['lon'])} | "
        f"deptos pts: {len(out['deptos']['lon'])} | "
        f"bytes: {os.path.getsize(out_p)}"
    )


if __name__ == "__main__":
    main()
