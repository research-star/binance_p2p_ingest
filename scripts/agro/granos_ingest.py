#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Builder del dataset de exportaciones agro (tab Agro) — portado de COMEX-Bolivia.

Provenance
----------
Portado desde el repo COMEX-Bolivia (github.com/InvestmentSolutionsDDR/COMEX-Bolivia,
pipeline/granos_ingest.py) el 2026-07-09, con la MISMA logica de ingesta/agregacion.
El snapshot committeado `static/agro_exportaciones.json` es copia byte a byte de
build/granos_data.json de ese repo; este script permite regenerarlo.

Los CRUDOS son los microdatos de exportaciones del INE (serie IneComex):
data/raw/Exportaciones/expYYYY/expYYYY.txt (2017-2026), ~26 MB en total,
sep='|', encoding latin-1. NO se versionan en este repo — viven en el working
tree de COMEX-Bolivia (`C:\\Dev\\Trabajo previo\\Comex\\COMEX-Bolivia\\data\\raw\\Exportaciones`
en la maquina de Diego) y se pasan via --raw-dir. La `fecha_descarga` del meta
NO es la fecha de corrida: viene del config (`meta.fecha_descarga`), que registra
cuando se bajaron los crudos del INE.

Quirks de los crudos (heredados y resueltos): exp2019 viene SIN fila de
encabezado; exp2018/exp2019 traen los campos numericos en formato float
('2018.0'); NANDINA se re-padea a 10 digitos para preservar ceros a la izquierda.

Filtra al universo de granos/agro definido en granos_config.json (match por
PREFIJO NANDINA con exclusion de lineas 'para siembra'), agrega a nivel
semilla x departamento x anio x mes x pais y emite el JSON contrato
{meta, origTotal, nacional, porDepto} que consume el frontend.

FOB en USD (entero), peso en Kg, volumen en Toneladas (Kg/1000),
precio implicito = FOB/Peso_Neto (USD/kg).

Uso:
  python scripts/agro/granos_ingest.py --raw-dir "C:\\...\\data\\raw\\Exportaciones"
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

import pandas as pd

# Raiz del repo (scripts/agro/granos_ingest.py -> parents[2])
REPO = Path(__file__).resolve().parents[2]
DEF_CFG = REPO / "scripts" / "agro" / "granos_config.json"
DEF_OUT = REPO / "static" / "agro_exportaciones.json"

COLS = ["GESTION", "MES", "Departamento", "NANDINA", "des_nandina", "des_Pais",
        "des_Medio_Sal", "des_Via_Sal", "CUCIR3", "GCE", "CIIU3", "CODACT", "TNT",
        "Peso_Bruto_Kg", "Peso_Neto_Kg", "Valor_FOB_Sus"]
# Mapeo oficial de departamento (identico al del repo origen)
DEPTOS = {1: "Chuquisaca", 2: "La Paz", 3: "Cochabamba", 4: "Oruro", 5: "Potosi",
          6: "Tarija", 7: "Santa Cruz", 8: "Beni", 9: "Pando"}


def cargar_config(cfg_path):
    return json.loads(Path(cfg_path).read_text(encoding="utf-8"))


def cargar_raw(raw_dir):
    """Concatena los expYYYY.txt y normaliza tipos/encoding (quirks resueltos)."""
    raw_dir = Path(raw_dir)
    files = sorted(glob.glob(str(raw_dir / "exp20*" / "exp20*.txt")))
    if not files:
        sys.exit(f"[ingest] ERROR: no se encontraron crudos exp20*/exp20*.txt en {raw_dir}")
    frames = []
    for f in files:
        yr = os.path.basename(f)[3:7]
        hdr = 0 if yr != "2019" else None  # exp2019 viene SIN fila de encabezado
        df = pd.read_csv(f, sep="|", encoding="latin-1", dtype=str, header=hdr,
                         names=(COLS if yr == "2019" else None))
        df.columns = [c.strip() for c in df.columns]
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    # to_numeric(coerce) absorbe el formato float de exp2018/exp2019 ('2018.0' -> 2018)
    raw["anio"] = pd.to_numeric(raw["GESTION"], errors="coerce").astype("Int64")
    raw["mes"] = pd.to_numeric(raw["MES"], errors="coerce").astype("Int64")
    raw["dep_cod"] = pd.to_numeric(raw["Departamento"], errors="coerce").astype("Int64")
    # NANDINA defensivo: quitar posible '.0' y re-padear a 10 digitos (preserva ceros)
    raw["nandina"] = (raw["NANDINA"].astype(str).str.strip()
                      .str.replace(r"\.0$", "", regex=True).str.zfill(10))
    raw["fob_usd"] = pd.to_numeric(raw["Valor_FOB_Sus"], errors="coerce").fillna(0.0)
    raw["kg"] = pd.to_numeric(raw["Peso_Neto_Kg"], errors="coerce").fillna(0.0)
    raw["pais"] = raw["des_Pais"].astype(str).str.strip().str.upper()
    raw = raw[raw["anio"].notna() & raw["nandina"].str.fullmatch(r"\d{10}")].copy()
    return raw


def construir_clasificador(cfg):
    """Devuelve f(nandina)->semilla_key|None (primera semilla cuyo prefijo incluye y no excluye)."""
    sem = cfg["semillas"]

    def clasif(nand):
        for s in sem:
            if (any(nand.startswith(p) for p in s["incluye"])
                    and not any(nand.startswith(p) for p in s.get("excluye", []))):
                return s["key"]
        return None
    return clasif


def _chequear_ambiguedad(cfg, codigos):
    """Reporta NANDINA que matchean >1 semilla (deberia ser 0 con prefijos disjuntos)."""
    sem = cfg["semillas"]
    amb = {}
    for nand in codigos:
        hits = [s["key"] for s in sem
                if any(nand.startswith(p) for p in s["incluye"])
                and not any(nand.startswith(p) for p in s.get("excluye", []))]
        if len(hits) > 1:
            amb[nand] = hits
    return amb


def construir_json(g, cfg):
    """Construye el contrato de datos del frontend a partir del subset de granos `g`."""
    YEARS = sorted(int(y) for y in g["anio"].dropna().unique())
    yidx = {y: i for i, y in enumerate(YEARS)}
    NY = len(YEARS)
    # Eje mensual continuo desde el primer al ultimo (anio,mes) presente
    yms = sorted({(int(a), int(m)) for a, m in zip(g["anio"], g["mes"]) if pd.notna(a) and pd.notna(m)})
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    YM = []
    yy, mm = y0, m0
    while (yy, mm) <= (y1, m1):
        YM.append(f"{yy}-{mm:02d}")
        mm += 1
        if mm > 12:
            mm = 1
            yy += 1
    ymidx = {k: i for i, k in enumerate(YM)}
    M = len(YM)

    def serA_fob(d):
        a = [0] * NY
        for y, v in d.groupby("anio")["fob_usd"].sum().items():
            if pd.notna(y):
                a[yidx[int(y)]] = int(round(float(v)))
        return a

    def serA_ton(d):
        a = [0.0] * NY
        for y, v in d.groupby("anio")["kg"].sum().items():
            if pd.notna(y):
                a[yidx[int(y)]] = round(float(v) / 1000.0, 3)
        return a

    def serM_fob(d):
        a = [0] * M
        for (y, mo), v in d.groupby(["anio", "mes"])["fob_usd"].sum().items():
            if pd.notna(y) and pd.notna(mo):
                k = f"{int(y)}-{int(mo):02d}"
                if k in ymidx:
                    a[ymidx[k]] = int(round(float(v)))
        return a

    def serM_ton(d):
        a = [0.0] * M
        for (y, mo), v in d.groupby(["anio", "mes"])["kg"].sum().items():
            if pd.notna(y) and pd.notna(mo):
                k = f"{int(y)}-{int(mo):02d}"
                if k in ymidx:
                    a[ymidx[k]] = round(float(v) / 1000.0, 3)
        return a

    def dest_obj(d, topn):
        tot = d.groupby("pais")["fob_usd"].sum().sort_values(ascending=False)
        keep = list(tot.index[:topn])
        out = {}
        for p in keep:
            sub = d[d.pais == p]
            out[p] = {"fA": serA_fob(sub), "tA": serA_ton(sub)}
        if len(tot) > topn:
            sub = d[~d.pais.isin(keep)]
            out["OTROS"] = {"fA": serA_fob(sub), "tA": serA_ton(sub)}
        return out

    # Nacional por semilla (todas las del config; ausentes -> ceros)
    nacional = {}
    for key, sub in g.groupby("semilla"):
        nacional[key] = {"fobA": serA_fob(sub), "tonA": serA_ton(sub),
                         "fobM": serM_fob(sub), "tonM": serM_ton(sub),
                         "dest": dest_obj(sub, 15)}
    for s in cfg["semillas"]:
        nacional.setdefault(s["key"], {"fobA": [0] * NY, "tonA": [0.0] * NY,
                                       "fobM": [0] * M, "tonM": [0.0] * M, "dest": {}})

    # Por departamento -> por semilla
    porDepto = {}
    for dep, subd in g.groupby("departamento"):
        sd = {}
        for key, sub in subd.groupby("semilla"):
            sd[key] = {"fobA": serA_fob(sub), "tonA": serA_ton(sub),
                       "fobM": serM_fob(sub), "tonM": serM_ton(sub),
                       "dest": dest_obj(sub, 12)}
        porDepto[dep] = sd

    # Total granos por departamento (para el choropleth del mapa)
    origTotal = {dep: {"fobA": serA_fob(subd), "tonA": serA_ton(subd)}
                 for dep, subd in g.groupby("departamento")}

    meses = {int(y): int(g.loc[g.anio == y, "mes"].dropna().nunique()) for y in YEARS}
    complete = [y for y in YEARS if meses[y] == 12]
    base_year = max(complete) if complete else max(YEARS)
    ytd = [y for y in YEARS if meses[y] < 12]
    present = set(g["semilla"].dropna().unique())
    semillas_meta = [{**s, "estado": ("presente" if s["key"] in present else "ausente")}
                     for s in cfg["semillas"]]

    meta = {**cfg["meta"],
            "deptos": {str(k): v for k, v in DEPTOS.items()},
            "years": YEARS, "ym": YM, "baseYear": base_year, "ytdYears": ytd,
            "mesesPorAnio": {str(k): v for k, v in meses.items()},
            "generado": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "nSemillas": len(present),
            "semillas": semillas_meta,
            "formulas": {"precio": "FOB(USD)/Peso_Neto(Kg)=USD/kg",
                         "toneladas": "Peso_Neto_Kg/1000",
                         "varInteranual": "X_t / X_(t-1) - 1"}}
    return {"meta": meta, "origTotal": origTotal, "nacional": nacional, "porDepto": porDepto}, YEARS, YM


def main():
    ap = argparse.ArgumentParser(
        description="Regenera static/agro_exportaciones.json desde los crudos INE IneComex.")
    ap.add_argument("--raw-dir", required=True,
                    help="Directorio con los crudos INE expYYYY/expYYYY.txt (NO versionados en este repo)")
    ap.add_argument("--config", default=str(DEF_CFG),
                    help=f"Config de semillas NANDINA (default: {DEF_CFG})")
    ap.add_argument("--out", default=str(DEF_OUT),
                    help=f"JSON de salida (default: {DEF_OUT})")
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    raw = cargar_raw(args.raw_dir)
    print(f"[ingest] filas crudas validas: {len(raw):,}", file=sys.stderr)

    clasif = construir_clasificador(cfg)
    raw["semilla"] = raw["nandina"].map(clasif)
    g = raw[raw["semilla"].notna()].copy()

    # Chequeo de ambiguedad (doble match)
    amb = _chequear_ambiguedad(cfg, g["nandina"].unique())
    print(f"[ingest] NANDINA con doble-match (ambiguo): {len(amb)} "
          + (str(amb) if amb else "(ok, prefijos disjuntos)"), file=sys.stderr)

    sem_meta = {s["key"]: s for s in cfg["semillas"]}
    g["grupo"] = g["semilla"].map(lambda k: sem_meta[k]["grupo"])
    g["semilla_label"] = g["semilla"].map(lambda k: sem_meta[k]["label"])
    g["departamento"] = g["dep_cod"].map(lambda c: DEPTOS.get(int(c)) if pd.notna(c) else None)
    g = g[g["departamento"].notna()].copy()

    # ---------------- JSON contrato frontend ----------------
    data, YEARS, YM = construir_json(g, cfg)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    sz = os.path.getsize(out_path)

    # ---------------- Diagnostico (DoD) ----------------
    present = sorted(set(g["semilla"].unique()))
    ausentes = [s["key"] for s in cfg["semillas"] if s["key"] not in present]
    deptos = sorted(g["departamento"].unique())
    top = (g.groupby(["nandina"]).agg(fob=("fob_usd", "sum"))
             .sort_values("fob", ascending=False).head(10))
    desc = g.groupby("nandina")["des_nandina"].agg(
        lambda s: s.astype(str).str.strip().value_counts().index[0])
    por_dep = g.groupby("departamento")["fob_usd"].sum().sort_values(ascending=False)
    print(f"[ingest] anios: {YEARS[0]}-{YEARS[-1]} ({len(YEARS)})  meses: {YM[0]}..{YM[-1]} ({len(YM)})", file=sys.stderr)
    print(f"[ingest] semillas presentes ({len(present)}): {present}", file=sys.stderr)
    print(f"[ingest] semillas ausentes  ({len(ausentes)}): {ausentes}", file=sys.stderr)
    print(f"[ingest] departamentos ({len(deptos)}): {deptos}", file=sys.stderr)
    print(f"[ingest] granos JSON: {sz/1e6:.2f} MB -> {out_path}", file=sys.stderr)
    print("[ingest] TOP-10 NANDINA por FOB capturadas:", file=sys.stderr)
    for nd, row in top.iterrows():
        sk = clasif(nd)
        print(f"         {nd}  FOB={row.fob/1e6:8.2f}M  [{sk}]  {desc[nd][:42]}", file=sys.stderr)
    print("[ingest] FOB granos acumulado por departamento (USD):", file=sys.stderr)
    for dep, v in por_dep.items():
        print(f"         {dep:<13} {v/1e6:9.2f}M", file=sys.stderr)


if __name__ == "__main__":
    main()
