#!/usr/bin/env python3
"""ingest_bloqueos.py — Bloqueos de carreteras en Bolivia (subsección Macro).

Fuente: dataset abierto de Mauricio Foronda
(github.com/mauforonda/transitabilidad-bolivia), que archiva el registro de
incidentes de la ABC (transitabilidad.abc.gob.bo) cada 2 h. NO re-scrapeamos la
ABC (su API está detrás de captcha): consumimos los archivos derivados que él
publica, con atribución:

  - activos_ahora.json         -> conteo activo {conflicto, no_conflicto}
  - conflictos_coordenadas.csv -> id,latitud,longitud de puntos de conflicto
  - conflictos_tiempo.json     -> [{time, open:[ids]}] cada 6 h (serie histórica)
  - data.csv                   -> maestro (~14 MB); de acá el nombre de tramo (sección) por coord

Produce bloqueos.json (raíz del repo) que dashboard.py inyecta al template.
Solo stdlib.
"""
import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = "https://raw.githubusercontent.com/mauforonda/transitabilidad-bolivia/master"
OUT = Path(__file__).parent / "bloqueos.json"
UA = "FinanzasBo/1.0 (+https://finanzasbo.com)"
SOURCE_REPO = "https://github.com/mauforonda/transitabilidad-bolivia"
TZ = timezone(timedelta(hours=-4))  # GMT-04:00, como la fuente

# Intensidad de bloqueos por punto. La ABC emite un id NUEVO por cada reporte, así
# que un mismo tramo bloqueado por semanas aparece como muchos ids efímeros (días
# por id ~1-2). Para una intensidad con sentido agrupamos por COORDENADA (no por
# id) y contamos los días distintos con ≥1 bloqueo abierto desde INTENSIDAD_DESDE
# (inclusive: los ya abiertos antes cuentan desde esa fecha). Alimenta la opacidad
# del mapa como proxy de la densidad que se ve en QGIS.
INTENSIDAD_DESDE = "2026-05-01"  # ancla fija (episodio actual); cambiar por ventana móvil si se quiere
COORD_DECIMALS = 3               # ~110 m: define "mismo punto"

# Polígonos de departamentos (exportados de QGIS, gadm41, simplificados). Sirven
# para asignar cada bloqueo a su depto vía point-in-polygon (ranking por depto).
DEPTOS_FILE = Path(__file__).parent / "static" / "bolivia_departamentos.json"

# Mapeo curado evento->categoría para el mapa por tipo (ticket Bloqueos-mapa-
# categorias). La causa viene de la columna `evento` de data.csv (NO `estado`,
# que es transitabilidad). Eventos no listados caen en "otro"; "ningun evento"
# se filtra (no es un bloqueo). El diccionario es la fuente de verdad de la
# clasificación: ampliarlo acá reclasifica sin tocar el frontend.
EVENTO_CATEGORIA = {
    "bloqueo por motivos sociales": "conflicto",
    "bloqueo por demandas locales": "conflicto",
    "tramo en construccion": "obras",
    "rehabilitacion": "obras",
    "reposicion de plataforma": "obras",
    "crecida de rio": "clima",
    "no transitar en lluvias": "clima",
    "inundacion": "clima",
    "afectacion de puente": "derrumbe",
    "colapso de puente": "derrumbe",
    "derrumbe": "derrumbe",
    "derrumbes menores": "derrumbe",
    "perdida de plataforma": "derrumbe",
    "trazo en evaluacion": "otro",
    "saturacion de plataforma": "otro",
    "bloqueo": "otro",
}
EVENTO_FILTRAR = {"ningun evento", ""}  # no son bloqueos: no van al mapa


def categoria_evento(ev):
    """Categoría de mapa para un valor de `evento`. None = filtrar (no es bloqueo)."""
    if ev in EVENTO_FILTRAR:
        return None
    return EVENTO_CATEGORIA.get(ev, "otro")


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_data_csv():
    """Una sola descarga del maestro data.csv (~15 MB) que produce dos cosas:

      - secciones: {(lat5,lon5) -> nombre de tramo (sección)} para el hover.
      - eventos_activos: [{lat,lon,cat,evento,estado,sec}] de las filas con
        `fecha_fin` vacío (= activas en la última consulta), categorizadas por
        `categoria_evento` y excluyendo "ningun evento". A diferencia de los
        derivados conflict-only de @mauforonda, acá lat/lon vienen poblados para
        TODOS los tipos (clima/obras/derrumbe), así que el mapa los puede pintar.

    Best-effort: si data.csv falla, devuelve ({}, []) y el resto degrada (hover
    cae a coordenadas; el mapa de categorías queda vacío, no rompe)."""
    try:
        raw = _get(f"{BASE}/data.csv", timeout=120).decode("utf-8", "replace")
    except Exception:
        return {}, []
    sec = {}
    eventos = []
    for row in csv.DictReader(io.StringIO(raw)):
        try:
            lat5 = round(float(row["latitud"]), 5)
            lon5 = round(float(row["longitud"]), 5)
        except (ValueError, KeyError, TypeError):
            continue
        s = (row.get("sección") or "").strip()
        if s:
            sec[(lat5, lon5)] = s  # última aparición (más reciente) gana
        if (row.get("fecha_fin") or "").strip():
            continue  # ya resuelto: no es activo ahora
        ev = (row.get("evento") or "").strip()
        cat = categoria_evento(ev)
        if cat is None:
            continue  # "ningun evento" / vacío: no es bloqueo
        eventos.append({
            "lat": lat5, "lon": lon5, "cat": cat, "evento": ev,
            "estado": (row.get("estado") or "").strip(), "sec": s,
        })
    return sec, eventos


def fetch():
    activos = json.loads(_get(f"{BASE}/activos_ahora.json"))
    coords = {}
    reader = csv.DictReader(
        io.StringIO(_get(f"{BASE}/conflictos_coordenadas.csv").decode("utf-8"))
    )
    for row in reader:
        try:
            coords[row["id"]] = (
                round(float(row["latitud"]), 5),
                round(float(row["longitud"]), 5),
            )
        except (ValueError, KeyError, TypeError):
            continue
    tiempo = json.loads(_get(f"{BASE}/conflictos_tiempo.json"))
    secciones, eventos_activos = fetch_data_csv()
    return activos, coords, tiempo, secciones, eventos_activos


def build_intensidad(coords, tiempo, secciones):
    """Días distintos con bloqueo abierto por coordenada, desde INTENSIDAD_DESDE.
    Cada punto lleva 'sec' = nombre de tramo más frecuente del bucket (~110 m)."""
    buckets = {}    # bucket -> set(días)
    sec_votos = {}  # bucket -> {sección: votos}
    for entry in tiempo:
        day = (entry.get("time") or "")[:10]
        if not day or day < INTENSIDAD_DESDE:
            continue
        for cid in (entry.get("open") or []):
            c = coords.get(str(cid))
            if not c:
                continue
            key = (round(c[0], COORD_DECIMALS), round(c[1], COORD_DECIMALS))
            buckets.setdefault(key, set()).add(day)
            s = secciones.get(c)
            if s:
                v = sec_votos.setdefault(key, {})
                v[s] = v.get(s, 0) + 1
    puntos = []
    for k, dias in buckets.items():
        votos = sec_votos.get(k) or {}
        sec = max(votos, key=votos.get) if votos else ""
        puntos.append({"lat": k[0], "lon": k[1], "dias": len(dias), "sec": sec})
    # Menor intensidad primero: se dibuja debajo, los hotspots quedan arriba.
    puntos.sort(key=lambda p: p["dias"])
    return {
        "desde": INTENSIDAD_DESDE,
        "max_dias": max((p["dias"] for p in puntos), default=0),
        "puntos": puntos,
    }


def _load_deptos():
    try:
        return json.loads(DEPTOS_FILE.read_text(encoding="utf-8")).get("departamentos", [])
    except Exception:
        return []


def _in_ring(lon, lat, ring):
    """Ray casting: ¿(lon,lat) dentro del anillo?"""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _dept_of(lon, lat, deptos):
    for d in deptos:
        if any(_in_ring(lon, lat, r) for r in d.get("polygons") or []):
            return d.get("name")
    return None


def por_departamento(puntos, deptos):
    """Ranking [{dep, n}] desc: cuántos puntos caen en cada departamento."""
    if not deptos:
        return []
    counts = {}
    for p in puntos:
        dn = _dept_of(p["lon"], p["lat"], deptos)
        if dn:
            counts[dn] = counts.get(dn, 0) + 1
    return [{"dep": k, "n": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


def build(activos, coords, tiempo, secciones, eventos_activos):
    # Serie diaria: # de conflictos abiertos por día (última lectura del día gana;
    # las entries vienen en orden cronológico).
    daily = {}
    for entry in tiempo:
        day = (entry.get("time") or "")[:10]
        if not day:
            continue
        daily[day] = len(entry.get("open") or [])
    serie = [{"fecha": d, "abiertos": n} for d, n in sorted(daily.items())]

    # Activos ahora: ids abiertos en la última lectura -> coordenadas + nombre de tramo.
    activos_pts = []
    ultima_lectura = None
    if tiempo:
        last = tiempo[-1]
        ultima_lectura = last.get("time")
        for cid in (last.get("open") or []):
            c = coords.get(str(cid))
            if c:
                activos_pts.append({"lat": c[0], "lon": c[1], "sec": secciones.get(c, "")})

    # conflicto = puntos abiertos en la última lectura del timeline (coincide con
    # el mapa y el último punto de la serie). no_conflicto viene del conteo de la
    # fuente (clima/obras: sin coordenadas en los derivados).
    conflicto = len(activos_pts)
    no_conflicto = int(activos.get("no_conflicto", 0) or 0)
    deptos = _load_deptos()
    intensidad = build_intensidad(coords, tiempo, secciones)
    intensidad["por_departamento"] = por_departamento(intensidad["puntos"], deptos)
    now = datetime.now(TZ)
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "fuente": SOURCE_REPO,
        "credito": "Datos: ABC (transitabilidad.abc.gob.bo) vía dataset abierto de @mauforonda",
        "ultima_lectura": ultima_lectura,
        "resumen": {
            "conflicto": conflicto,
            "no_conflicto": no_conflicto,
            "total": conflicto + no_conflicto,
        },
        "activos": activos_pts,          # puntos de bloqueo por conflicto social, ahora (legacy)
        "activos_eventos": eventos_activos,  # TODOS los activos por categoría (conflicto/obras/clima/derrumbe/otro) c/lat-lon+sec
        "activos_por_departamento": por_departamento(activos_pts, deptos),  # ranking activos (conflicto, legacy)
        "activos_eventos_por_departamento": por_departamento(eventos_activos, deptos),  # ranking de TODOS los activos por depto
        "serie_diaria": serie,           # bloqueos por conflicto abiertos por día (histórico)
        "intensidad": intensidad,        # días bloqueado por punto desde INTENSIDAD_DESDE + ranking depto
    }


def main():
    try:
        activos, coords, tiempo, secciones, eventos_activos = fetch()
        data = build(activos, coords, tiempo, secciones, eventos_activos)
    except Exception as exc:  # noqa: BLE001 — fail-closed, no escribimos parcial
        sys.exit(f"ingest_bloqueos: error: {exc}")
    OUT.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    top = data["intensidad"]["por_departamento"][:3]
    pts = data["intensidad"]["puntos"]
    con_sec = sum(1 for p in pts if p.get("sec"))
    cat_count = {}
    for e in data["activos_eventos"]:
        cat_count[e["cat"]] = cat_count.get(e["cat"], 0) + 1
    print(
        f"OK -> {OUT.name} | activos={len(data['activos'])} | "
        f"eventos_activos={len(data['activos_eventos'])} por_cat={cat_count} | "
        f"serie={len(data['serie_diaria'])} pts | "
        f"intensidad={len(pts)} pts (max {data['intensidad']['max_dias']}d, {con_sec} c/sección) | "
        f"deptos_top={[(d['dep'], d['n']) for d in top]} | "
        f"resumen={data['resumen']} | ultima_lectura={data['ultima_lectura']}"
    )


if __name__ == "__main__":
    main()
