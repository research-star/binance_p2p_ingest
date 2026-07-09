#!/usr/bin/env python3
"""
ingest_agro.py — Harvest de producción agrícola municipal del SIIP (MDPyEP).

El SIIP (Sistema Integrado de Información Productiva) expone un endpoint
JSON sin auth con producción/superficie por cultivo × campaña, a nivel
departamental y municipal:

    POST https://siip.produccion.gob.bo/repSIIP2/JsonAjaxAgricolaMdryt.php
      flag=cultivo&grupo=G                     → catálogo de cultivos del grupo
      flag=nacionalDepartamental&grupo&cultivo&campania
                                               → filas por departamento (INE 1-9)
      flag=departamentalMunicipalJson&grupo&cultivo&departamento&campania
                                               → filas por municipio, o null

Reglas del endpoint (recon 2026-07-09):
  - grupo OBLIGATORIO y debe corresponder al cultivo (códigos GLOBALES 1-73).
  - departamento OBLIGATORIO 1-9 en orden INE.
  - campania válida 2013..2024; fuera de rango → null.
  - null = sin datos O parámetro inválido (ambiguo): se cachea igual.
  - 'municipio' = código INE concatenado SIN zero-padding: len3 → d|p|m,
    len4 → d|pp|m ("111" = Sucre 01-01-01, "2201" = La Paz prov 20 secc 1).
  - Usamos 'produccion' (t) y 'superficie' (ha) crudos; los campos *2 son
    formateados y se ignoran. Rendimiento se deriva client-side (prod/sup).

Comportamiento:
  1. Baja catálogo (7 grupos) y resuelve el filtro --cultivos/--anios.
  2. Por cultivo×año: 1 POST departamental + 9 POST municipales, con CACHE
     en disco (--cache-dir): si el archivo existe NO se re-fetchea
     (resume/idempotente; el null literal también se cachea).
  3. Emite static/agro_produccion.json con el schema consumido por la tab
     Agro del frontend (ver emitir()). Mapeo municipio→GID GADM vía
     scripts/data/agro_municipios.csv; filas sin match van a sin_georef.
  4. Si el JSON supera MAX_BYTES_INDICE, particiona series_mun por grupo en
     static/agro_prod_g<n>.json y deja meta.shards en el índice.

Uso:
    python ingest_agro.py                          # todos los cultivos, 2013-2024
    python ingest_agro.py --cultivos 7,66,73       # solo Quínua, Papa, Chia
    python ingest_agro.py --anios 2020-2024
    python ingest_agro.py --rebuild-mapa "C:/ruta/a/fuentes"
        # reconstruye scripts/data/agro_municipios.csv desde mun_bol_db.xlsx
        # + info_mapas_*.csv (seeds validados) + el cache del harvest.

5xx persistente → aborta ruidoso listando qué combo falló; el cache
preserva lo avanzado y la próxima corrida resume desde ahí.
"""

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Constantes ────────────────────────────────────────────────────────────

SIIP_URL = "https://siip.produccion.gob.bo/repSIIP2/JsonAjaxAgricolaMdryt.php"
SIIP_FORM_URL = "https://siip.produccion.gob.bo/repSIIP2/formulario_mdryt2.php"
USER_AGENT = "FinanzasBo/agro-ingest"

REPO_ROOT = Path(__file__).parent
MAPA_DEFAULT = REPO_ROOT / "scripts" / "data" / "agro_municipios.csv"
OUT_DEFAULT = REPO_ROOT / "static" / "agro_produccion.json"

GRUPOS = {
    1: "Cereales",
    2: "Estimulantes",
    3: "Frutales",
    4: "Hortalizas",
    5: "Industriales",
    6: "Tubérculos",
    7: "Forrajes",
}

# Orden INE 1-9, canon ASCII (el mismo que usa el geojson departamental).
DEPTOS = {
    1: "Chuquisaca",
    2: "La Paz",
    3: "Cochabamba",
    4: "Oruro",
    5: "Potosi",
    6: "Tarija",
    7: "Santa Cruz",
    8: "Beni",
    9: "Pando",
}

# NAME_1 de GADM / seeds → canon ASCII.
DEPTO_CANON = {**{v: v for v in DEPTOS.values()}, "Potosí": "Potosi"}

ANIO_MIN, ANIO_MAX = 2013, 2024

# Códigos SIIP cuyo desc_mun viene NULL del endpoint (sin nombre que
# matchear). OJO: los códigos SIIP NO siguen el orden de secciones INE en
# Omasuyos (SIIP etiqueta 224='Santiago de Huata'; INE diría 225) — NO se
# infiere el nombre por orden. Estos van a sin_georef hasta que se decida
# una asignación manual verificada (columna ine_codes del CSV vía seeds).
SEEDS_INE_MANUALES: dict[str, str] = {}

# Umbral de sharding del índice (bytes crudos).
MAX_BYTES_INDICE = 1_300_000


# ── Normalización de nombres ──────────────────────────────────────────────

def norm_nombre(s: str) -> str:
    """Clave de match: lower, sin acentos, sin puntuación/espacios, sin
    sufijos SIIP (' GAIOC', ' (PA)' y paréntesis finales)."""
    s = s.strip().lower()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)   # ' (pa)' y similares
    s = re.sub(r"\s+gaioc$", "", s)
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def _num(s):
    """'23134' → 23134 (int si es entero, float si no). Falla ruidoso si el
    formato del SIIP cambia — no queremos poblar el JSON con basura."""
    v = float(s)
    return int(v) if v.is_integer() else v


# ── HTTP con cache en disco ───────────────────────────────────────────────

class FetchError(RuntimeError):
    pass


class SiipClient:
    """POST form-encoded al SIIP con reintentos + cache por-archivo.

    Cada respuesta cruda se guarda en cache_dir con nombre derivado de los
    params (p.ej. mun_g1_c7_d1_2024.json). Si el archivo existe no se
    re-fetchea — el harvest es resumible y el null literal también cuenta.
    """

    def __init__(self, cache_dir: Path, sleep_s: float, timeout_s: int,
                 reintentos: int):
        self.cache_dir = cache_dir
        self.sleep_s = sleep_s
        self.timeout_s = timeout_s
        self.reintentos = reintentos
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.n_http = 0
        self.n_cache = 0

    def _post(self, data: dict) -> str:
        ultimo = None
        for intento in range(self.reintentos):
            try:
                r = self.session.post(SIIP_URL, data=data,
                                      timeout=self.timeout_s)
                if r.status_code == 200:
                    return r.text
                ultimo = f"http={r.status_code}"
            except requests.RequestException as e:
                ultimo = repr(e)
            time.sleep(2 ** intento)  # backoff exponencial 1,2,4...
        raise FetchError(f"POST {data} agotó {self.reintentos} reintentos "
                         f"(último error: {ultimo})")

    def get(self, nombre: str, data: dict):
        """Devuelve el JSON parseado ('null' → None), usando cache."""
        path = self.cache_dir / f"{nombre}.json"
        if path.exists():
            self.n_cache += 1
            texto = path.read_text(encoding="utf-8")
        else:
            texto = self._post(data)
            path.write_text(texto, encoding="utf-8")
            self.n_http += 1
            time.sleep(self.sleep_s)
        texto = texto.strip()
        if not texto:
            return None
        return json.loads(texto)


# ── Catálogo ──────────────────────────────────────────────────────────────

def bajar_catalogo(cli: SiipClient) -> list[dict]:
    """Catálogo global de cultivos: [{codigo, label, grupo}] (grupo = int)."""
    cultivos = []
    vistos = set()
    for g in sorted(GRUPOS):
        rows = cli.get(f"cultivos_g{g}", {"flag": "cultivo", "grupo": g})
        if not rows:
            raise FetchError(f"Catálogo del grupo {g} vino vacío/null")
        for r in rows:
            cod = int(r["codigo"])
            if cod in vistos:
                raise FetchError(f"Código de cultivo {cod} duplicado entre "
                                 f"grupos — el supuesto 'códigos globales' "
                                 f"se rompió")
            vistos.add(cod)
            cultivos.append({"codigo": cod, "label": r["descripcion"],
                             "grupo": g})
    return cultivos


# ── Harvest ───────────────────────────────────────────────────────────────

def harvest(cli: SiipClient, seleccion: list[dict], anios: list[int]):
    """Baja (o lee del cache) todos los combos cultivo×año del filtro.

    Devuelve (rows_dep, rows_mun):
      rows_dep: (codigo, anio, depto_ine, sup_ha, prod_tm)
      rows_mun: (codigo, anio, depto_ine, cod_ine_crudo, desc_mun, sup, prod)
    """
    rows_dep, rows_mun = [], []
    combos = [(c, a) for c in seleccion for a in anios]
    for i, (cul, anio) in enumerate(combos):
        g, c = cul["grupo"], cul["codigo"]
        try:
            dep = cli.get(f"dep_g{g}_c{c}_{anio}", {
                "flag": "nacionalDepartamental", "grupo": g,
                "cultivo": c, "campania": anio})
            if dep:
                for r in dep:
                    rows_dep.append((c, anio, int(r["cod_dep"]),
                                     _num(r["superficie"]),
                                     _num(r["produccion"])))
            for d in sorted(DEPTOS):
                mun = cli.get(f"mun_g{g}_c{c}_d{d}_{anio}", {
                    "flag": "departamentalMunicipalJson", "grupo": g,
                    "cultivo": c, "departamento": d, "campania": anio})
                if mun:
                    for r in mun:
                        rows_mun.append((c, anio, d, str(r["municipio"]),
                                         r["desc_mun"] or "",
                                         _num(r["superficie"]),
                                         _num(r["produccion"])))
        except FetchError as e:
            faltan = len(combos) - i
            print(f"[agro] mode=error stage=harvest cultivo={c} anio={anio} "
                  f"detail={e}", file=sys.stderr)
            print(f"[agro] combos pendientes (incluido el fallido): {faltan} "
                  f"de {len(combos)} — el cache preserva lo avanzado, "
                  f"re-ejecutá con los mismos params para resumir",
                  file=sys.stderr)
            sys.exit(1)
    return rows_dep, rows_mun


# ── Mapa INE→GADM (scripts/data/agro_municipios.csv) ──────────────────────

def _leer_gadm_xlsx(path: Path) -> dict:
    """mun_bol_db.xlsx hoja municipios_bolivia (GADM 4.1, 344 filas) →
    {gid: {nombre, depto}} con depto en canon ASCII."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        ws = wb["municipios_bolivia"]
        rows = ws.iter_rows(values_only=True)
        hdr = list(next(rows))
        i_gid, i_dep, i_nom = hdr.index("GID_3"), hdr.index("NAME_1"), hdr.index("NAME_3")
        base = {}
        for r in rows:
            if not r or not r[i_gid]:
                continue
            depto = DEPTO_CANON.get(str(r[i_dep]).strip())
            if depto is None:
                raise RuntimeError(f"Depto GADM desconocido: {r[i_dep]!r}")
            base[str(r[i_gid]).strip()] = {
                "nombre": str(r[i_nom]).strip(), "depto": depto}
        return base
    finally:
        wb.close()


def _leer_seeds(fuentes_dir: Path):
    """Seeds validados (info_mapas_*.csv, pipe-delimited, BOM utf-8) →
    {(depto_canon, nombre_norm): gid} + variantes de nombre por gid.

    Quirks del export: algunas líneas vienen ENTERAS entre comillas con las
    comillas internas duplicadas (Caiza ""D"") — se desenvuelven a mano.
    Filas con municipio literal 'None' o gid vacío se descartan.
    """
    seed_lookup: dict[tuple, str] = {}
    alias_por_gid: dict[str, set] = defaultdict(set)
    descartadas = 0
    archivos = sorted(fuentes_dir.glob("info_mapas_*.csv"))
    if not archivos:
        raise RuntimeError(f"No hay info_mapas_*.csv en {fuentes_dir}")
    for f in archivos:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            lineas = [ln.rstrip("\r\n") for ln in fh]
        for n, ln in enumerate(lineas):
            if n == 0 or not ln.strip():
                continue  # header
            if ln.startswith('"') and ln.endswith('"'):
                ln = ln[1:-1].replace('""', '"')
            campos = ln.split("|")
            # grupo|anio|cultivo|departamento|cod_dpto_ine|gid_dpto|
            # municipio|gid_municipio|provincia|sup|prod|rend
            municipio, gid = campos[6], campos[7]
            if municipio == "None" or not gid:
                descartadas += 1
                continue
            depto = DEPTO_CANON.get(campos[3].strip())
            if depto is None:
                raise RuntimeError(f"{f.name}: depto desconocido {campos[3]!r}")
            clave = (depto, norm_nombre(municipio))
            previo = seed_lookup.get(clave)
            if previo is not None and previo != gid:
                raise RuntimeError(f"{f.name}: seed conflictivo {clave} → "
                                   f"{previo} vs {gid}")
            seed_lookup[clave] = gid
            alias_por_gid[gid].add(municipio.strip())
    return seed_lookup, alias_por_gid, descartadas


def _codigos_desde_cache(cache_dir: Path):
    """Escanea TODO el cache municipal → [(depto_canon, cod_ine, desc_mun)].
    Usa todos los mun_*.json presentes (no solo el filtro de esta corrida)
    para que el mapa acumule códigos a medida que el harvest crece."""
    pares = []
    pat = re.compile(r"mun_g\d+_c\d+_d(\d)_(\d{4})\.json$")
    for f in sorted(cache_dir.glob("mun_g*_c*_d*_*.json")):
        m = pat.search(f.name)
        if not m:
            continue
        depto = DEPTOS[int(m.group(1))]
        data = json.loads(f.read_text(encoding="utf-8") or "null")
        if not data:
            continue
        for r in data:
            pares.append((depto, str(r["municipio"]), r["desc_mun"] or ""))
    return pares


def rebuild_mapa(fuentes_dir: Path, cache_dir: Path, out_csv: Path) -> None:
    """Reconstruye scripts/data/agro_municipios.csv (fuente de verdad del
    join INE→GADM): base GADM 4.1 + seeds validados + códigos del cache."""
    base = _leer_gadm_xlsx(fuentes_dir / "mun_bol_db.xlsx")
    seed_lookup, alias_por_gid, descartadas = _leer_seeds(fuentes_dir)

    huerfanos = sorted(g for g in alias_por_gid if g not in base)
    if huerfanos:
        raise RuntimeError(f"Seeds con gid fuera de GADM 344: {huerfanos}")

    # Lookup por nombre GADM, restringido a depto; claves ambiguas se anulan.
    name_lookup: dict[tuple, str | None] = {}
    for gid, info in base.items():
        clave = (info["depto"], norm_nombre(info["nombre"]))
        name_lookup[clave] = None if clave in name_lookup else gid

    ine_codes: dict[str, set] = defaultdict(set)
    sin_match: dict[tuple, set] = {}
    conflictos = []
    for depto, code, desc in _codigos_desde_cache(cache_dir):
        clave = (depto, norm_nombre(desc))
        gid = (SEEDS_INE_MANUALES.get(code) or seed_lookup.get(clave)
               or name_lookup.get(clave))
        if gid:
            for otro, codes in ine_codes.items():
                if code in codes and otro != gid:
                    conflictos.append((code, otro, gid))
            ine_codes[gid].add(code)
            if norm_nombre(desc) != norm_nombre(base[gid]["nombre"]):
                alias_por_gid[gid].add(re.sub(r"\s+GAIOC$", "", desc).strip())
        else:
            sin_match.setdefault((desc, depto), set()).add(code)
    if conflictos:
        raise RuntimeError(f"Código INE apuntando a dos gids: {conflictos}")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["gid", "nombre", "depto", "ine_codes", "alias"])
        for gid in sorted(base):
            info = base[gid]
            codes = ";".join(sorted(ine_codes.get(gid, ()), key=int))
            alias = ";".join(sorted(
                a for a in alias_por_gid.get(gid, ())
                if norm_nombre(a) != norm_nombre(info["nombre"])))
            w.writerow([gid, info["nombre"], info["depto"], codes, alias])

    con_codigo = sum(1 for g in base if ine_codes.get(g))
    print(f"[agro] mapa reconstruido → {out_csv} gids={len(base)} "
          f"con_ine_codes={con_codigo} seeds_descartadas={descartadas} "
          f"sin_match={len(sin_match)}")
    for (desc, depto), codes in sorted(sin_match.items()):
        print(f"[agro]   SIN MATCH: {desc!r} ({depto}) "
              f"codigos={sorted(codes, key=int)}", file=sys.stderr)


def cargar_mapa(path: Path):
    """CSV del mapa → (por_gid, por_ine, por_nombre)."""
    if not path.exists():
        raise RuntimeError(f"Mapa {path} no existe — corré --rebuild-mapa "
                           f"o committeá scripts/data/agro_municipios.csv")
    por_gid, por_ine, por_nombre = {}, {}, {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            gid = row["gid"]
            depto = row["depto"]
            por_gid[gid] = {"nombre": row["nombre"], "depto": depto}
            for code in filter(None, row["ine_codes"].split(";")):
                por_ine[code] = gid
            claves = {norm_nombre(row["nombre"])}
            claves.update(norm_nombre(a)
                          for a in filter(None, row["alias"].split(";")))
            for k in claves:
                clave = (depto, k)
                # Ambigüedad dentro del depto → se anula la clave.
                por_nombre[clave] = (None if clave in por_nombre
                                     and por_nombre[clave] != gid else gid)
    return por_gid, por_ine, por_nombre


# ── Emisión ───────────────────────────────────────────────────────────────

def emitir(out_path: Path, catalogo, seleccion, anios,
           rows_dep, rows_mun, mapa) -> dict:
    """Construye y escribe el JSON del schema de la tab Agro.

    Devuelve stats {filas_mun, matcheadas, sin_georef, bytes, shards}.
    """
    por_gid, por_ine, por_nombre = mapa

    # Resolución gid por fila municipal (código INE primero, nombre después).
    resueltas = []   # (codigo, anio, gid, sup, prod)
    sin_georef: dict = {}
    gids_usados = set()
    for c, anio, d, code, desc, sup, prod in rows_mun:
        depto = DEPTOS[d]
        gid = por_ine.get(code)
        if gid is None:
            gid = por_nombre.get((depto, norm_nombre(desc)))
        if gid:
            resueltas.append((c, anio, gid, sup, prod))
            gids_usados.add(gid)
        else:
            (sin_georef.setdefault(str(c), {})
                       .setdefault(str(anio), [])
                       .append([desc, depto, sup, prod]))

    # municipios[]: solo los que aparecen en data, orden estable
    # (depto INE, nombre) — munIdx = índice en esta lista.
    orden_depto = {v: k for k, v in DEPTOS.items()}
    municipios = sorted(
        ({"gid": g, "nombre": por_gid[g]["nombre"],
          "depto": por_gid[g]["depto"]} for g in gids_usados),
        key=lambda m: (orden_depto[m["depto"]], m["nombre"]))
    idx = {m["gid"]: i for i, m in enumerate(municipios)}

    series_mun: dict = {}
    for c, anio, gid, sup, prod in resueltas:
        (series_mun.setdefault(str(c), {})
                   .setdefault(str(anio), [])
                   .append([idx[gid], sup, prod]))

    series_dep: dict = {}
    for c, anio, d, sup, prod in rows_dep:
        (series_dep.setdefault(str(c), {})
                   .setdefault(str(anio), {}))[DEPTOS[d]] = [sup, prod]

    grupo_por_codigo = {cu["codigo"]: cu["grupo"] for cu in catalogo}
    cultivos_emitidos = sorted(
        ({"codigo": cu["codigo"], "label": cu["label"],
          "grupo": GRUPOS[cu["grupo"]]} for cu in seleccion),
        key=lambda cu: (cu["grupo"], cu["label"]))

    parcial = {cu["codigo"] for cu in seleccion} != \
              {cu["codigo"] for cu in catalogo} or \
              set(anios) != set(range(ANIO_MIN, ANIO_MAX + 1))

    doc = {
        "meta": {
            "fuente": ("SIIP - MDPyEP, Informacion agricola a nivel "
                       "municipal (JsonAjaxAgricolaMdryt.php)"),
            "url": SIIP_FORM_URL,
            "generado": datetime.now(timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "anios": anios,
            "unidades": {"superficie": "ha", "produccion": "t"},
            "parcial": parcial,
            "deptos": [DEPTOS[i] for i in sorted(DEPTOS)],
        },
        "cultivos": cultivos_emitidos,
        "municipios": municipios,
        "series_mun": series_mun,
        "series_dep": series_dep,
    }
    if sin_georef:
        doc["sin_georef"] = sin_georef

    def _dumps(o):
        return json.dumps(o, separators=(",", ":"), ensure_ascii=False)

    shards = {}
    cuerpo = _dumps(doc)
    if len(cuerpo.encode("utf-8")) > MAX_BYTES_INDICE:
        # Particionar series_mun por grupo → static/agro_prod_g<n>.json.
        por_grupo: dict[int, dict] = defaultdict(dict)
        for cod_str, series in series_mun.items():
            por_grupo[grupo_por_codigo[int(cod_str)]][cod_str] = series
        for g, sub in sorted(por_grupo.items()):
            shard_name = f"agro_prod_g{g}.json"
            shard_path = out_path.parent / shard_name
            shard_path.write_text(_dumps(sub), encoding="utf-8")
            shards[str(g)] = shard_name
        doc["meta"]["shards"] = shards
        doc["series_mun"] = {}
        cuerpo = _dumps(doc)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(cuerpo, encoding="utf-8")

    n_sin = sum(len(v) for c in sin_georef.values() for v in c.values())
    return {"filas_mun": len(rows_mun), "matcheadas": len(resueltas),
            "sin_georef": n_sin, "bytes": len(cuerpo.encode("utf-8")),
            "shards": shards, "municipios": len(municipios)}


# ── CLI ───────────────────────────────────────────────────────────────────

def parse_anios(spec: str) -> list[int]:
    """'2013-2024' o '2019,2021' → lista ordenada validada al rango SIIP."""
    if "-" in spec:
        a, b = spec.split("-", 1)
        anios = list(range(int(a), int(b) + 1))
    else:
        anios = sorted({int(x) for x in spec.split(",") if x.strip()})
    fuera = [a for a in anios if not ANIO_MIN <= a <= ANIO_MAX]
    if fuera or not anios:
        raise SystemExit(f"[agro] años fuera del rango SIIP "
                         f"{ANIO_MIN}-{ANIO_MAX}: {fuera or spec}")
    return anios


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Harvest SIIP de producción agrícola municipal")
    parser.add_argument("--cache-dir", type=Path, default=Path("agro_cache"),
                        help="Dir de cache crudo (default: agro_cache/)")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT,
                        help=f"JSON de salida (default: {OUT_DEFAULT})")
    parser.add_argument("--sleep", type=float, default=0.4,
                        help="Pausa entre requests reales, s (default 0.4)")
    parser.add_argument("--cultivos", default="",
                        help="Códigos separados por coma (default: todos)")
    parser.add_argument("--anios", default=f"{ANIO_MIN}-{ANIO_MAX}",
                        help="Rango '2013-2024' o lista '2019,2021'")
    parser.add_argument("--timeout", type=int, default=45,
                        help="Timeout HTTP, s (default 45)")
    parser.add_argument("--reintentos", type=int, default=3,
                        help="Reintentos con backoff exponencial (default 3)")
    parser.add_argument("--mapa", type=Path, default=MAPA_DEFAULT,
                        help=f"CSV mapeo INE→GADM (default: {MAPA_DEFAULT})")
    parser.add_argument("--rebuild-mapa", type=Path, metavar="DIR",
                        help="Reconstruye --mapa desde DIR (mun_bol_db.xlsx "
                             "+ info_mapas_*.csv) + el cache, antes de emitir")
    args = parser.parse_args()

    t0 = time.time()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    cli = SiipClient(args.cache_dir, args.sleep, args.timeout,
                     args.reintentos)

    try:
        catalogo = bajar_catalogo(cli)
    except FetchError as e:
        print(f"[agro] mode=error stage=catalogo detail={e}", file=sys.stderr)
        return 1

    if args.cultivos.strip():
        pedidos = {int(x) for x in args.cultivos.split(",") if x.strip()}
        conocidos = {c["codigo"] for c in catalogo}
        if pedidos - conocidos:
            print(f"[agro] mode=error stage=filtro "
                  f"cultivos_desconocidos={sorted(pedidos - conocidos)}",
                  file=sys.stderr)
            return 1
        seleccion = [c for c in catalogo if c["codigo"] in pedidos]
    else:
        seleccion = list(catalogo)
    anios = parse_anios(args.anios)

    rows_dep, rows_mun = harvest(cli, seleccion, anios)

    if args.rebuild_mapa:
        rebuild_mapa(args.rebuild_mapa, args.cache_dir, args.mapa)

    mapa = cargar_mapa(args.mapa)
    stats = emitir(args.out, catalogo, seleccion, anios,
                   rows_dep, rows_mun, mapa)

    print(f"[agro] mode=ok cultivos={len(seleccion)}/{len(catalogo)} "
          f"anios={anios[0]}-{anios[-1]} "
          f"http={cli.n_http} cacheados={cli.n_cache} "
          f"filas_dep={len(rows_dep)} filas_mun={stats['filas_mun']} "
          f"mun_match={stats['matcheadas']} sin_georef={stats['sin_georef']} "
          f"municipios={stats['municipios']} bytes={stats['bytes']} "
          f"shards={sorted(stats['shards']) or '-'} "
          f"duration_s={time.time()-t0:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
