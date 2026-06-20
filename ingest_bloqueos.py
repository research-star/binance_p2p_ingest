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


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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
    return activos, coords, tiempo


def build_intensidad(coords, tiempo):
    """Días distintos con bloqueo abierto por coordenada, desde INTENSIDAD_DESDE."""
    buckets = {}  # (lat_r, lon_r) -> set(días)
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
    puntos = [{"lat": k[0], "lon": k[1], "dias": len(v)} for k, v in buckets.items()]
    # Menor intensidad primero: se dibuja debajo, los hotspots quedan arriba.
    puntos.sort(key=lambda p: p["dias"])
    return {
        "desde": INTENSIDAD_DESDE,
        "max_dias": max((p["dias"] for p in puntos), default=0),
        "puntos": puntos,
    }


def build(activos, coords, tiempo):
    # Serie diaria: # de conflictos abiertos por día (última lectura del día gana;
    # las entries vienen en orden cronológico).
    daily = {}
    for entry in tiempo:
        day = (entry.get("time") or "")[:10]
        if not day:
            continue
        daily[day] = len(entry.get("open") or [])
    serie = [{"fecha": d, "abiertos": n} for d, n in sorted(daily.items())]

    # Activos ahora: ids abiertos en la última lectura -> coordenadas.
    activos_pts = []
    ultima_lectura = None
    if tiempo:
        last = tiempo[-1]
        ultima_lectura = last.get("time")
        for cid in (last.get("open") or []):
            c = coords.get(str(cid))
            if c:
                activos_pts.append({"lat": c[0], "lon": c[1]})

    # conflicto = puntos abiertos en la última lectura del timeline (coincide con
    # el mapa y el último punto de la serie). no_conflicto viene del conteo de la
    # fuente (clima/obras: sin coordenadas en los derivados).
    conflicto = len(activos_pts)
    no_conflicto = int(activos.get("no_conflicto", 0) or 0)
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
        "activos": activos_pts,          # puntos de bloqueo por conflicto social, ahora
        "serie_diaria": serie,           # bloqueos por conflicto abiertos por día (histórico)
        "intensidad": build_intensidad(coords, tiempo),  # días bloqueado por punto desde INTENSIDAD_DESDE (mapa)
    }


def main():
    try:
        activos, coords, tiempo = fetch()
        data = build(activos, coords, tiempo)
    except Exception as exc:  # noqa: BLE001 — fail-closed, no escribimos parcial
        sys.exit(f"ingest_bloqueos: error: {exc}")
    OUT.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"OK -> {OUT.name} | activos={len(data['activos'])} | "
        f"serie={len(data['serie_diaria'])} pts | "
        f"intensidad={len(data['intensidad']['puntos'])} pts (max {data['intensidad']['max_dias']}d) | "
        f"resumen={data['resumen']} | ultima_lectura={data['ultima_lectura']}"
    )


if __name__ == "__main__":
    main()
