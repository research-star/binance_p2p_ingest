#!/usr/bin/env python3
"""
ingest_bcb_tco.py — Scraper del Tipo de Cambio Oficial (TCO) del BCB.

Desde la RD N° 88/2026 (26-jun-2026, deja sin efecto el Reglamento de 2013) el
BCB publica un **Tipo de Cambio Oficial (TCO)** que reemplaza al tipo de cambio
fijo (6,86 compra / 6,96 venta). Definición (Anexo II de la RD 88/2026):

  - El TCO es el **promedio ponderado de las operaciones de COMPRA de USD** de
    los Bancos Múltiples, Bancos PyME y el Banco Público con sus clientes, entre
    00:00 y 17:00 de cada día hábil, ponderado por el monto en USD de cada
    operación. Excluye operaciones entre entidades financieras.
  - Se publica cada día hábil a las **20:00** y es **vigente al día siguiente**.
  - Redondeado a 2 decimales. Sáb/dom/feriados = TCO del último día hábil.
  - El valor referencial de venta = TCO + 0,10 Bs.

Fuentes (dos, ver `--via`):

  1. PORTADA (default, `--via portada`) — https://www.bcb.gob.bo/
     Card "Tipo de cambio oficial" (server-rendered) con HOY y MAÑANA. Es la
     fuente PRIMARIA porque va por DELANTE del detalle histórico, que tiene
     rezago: la portada ya muestra el TCO de MAÑANA cuando el detalle todavía no
     lo publicó. Parser: `parse_homepage_tco`.

  2. HISTÓRICO (`--via historico`, forzado por `--backfill`) — reporte detallado:
     https://www.bcb.gob.bo/tco_reporte_detalle_historico.php

El CSV exportado (delimitado por `;`) trae, por día, el DETALLE de operaciones
(por banco: N° de transacciones y monto USD, por nivel de precio) y al final una
fila `TOTAL` y una fila `TCO`. La columna `TOTAL BANCOS` de la fila `TCO` es el
**TCO oficial del día, ya calculado por el BCB** (no lo inventamos: lo leemos).
Como verificación, el parser recalcula el promedio ponderado por monto del
detalle (fórmula del Anexo II) y avisa si difiere del publicado. Formato
verificado contra muestra real del 2026-06-29 (publicado 9.73 = recalculado 9.73).

──────────────────────────────────────────────────────────────────────────────
NOTA DE DESARROLLO: el FORMATO del CSV ya está confirmado (ver arriba). Lo que
falta resolver en el VPS es la **URL/params exactos de descarga** del CSV: la
página es un formulario con rango de fechas (el archivo de muestra se llamaba
`TCO_<desde>_al_<hasta>.csv`), así que `fetch()` del .php base puede devolver el
HTML del formulario, no el CSV. Bucle de iteración en el VPS (sí alcanza BCB):

    python3 ingest_bcb_tco.py --debug          # vuelca lo que devuelve la URL a bcb_tco_raw.html
    python3 ingest_bcb_tco.py --from-file ARCHIVO.csv --dry-run   # parsea offline (ya verde)

Cuando se conozca el endpoint de export, ajustar URL_TCO (o pasar --url con los
params). Si el parser no encuentra filas, sale con código ≠0 y deja el crudo en
disco para inspección.
──────────────────────────────────────────────────────────────────────────────

Uso:
    python3 ingest_bcb_tco.py                       # portada (HOY+MAÑANA) → guarda
    python3 ingest_bcb_tco.py --dry-run             # imprime sin escribir
    python3 ingest_bcb_tco.py --via historico       # detalle CSV (verificación)
    python3 ingest_bcb_tco.py --backfill            # serie completa (detalle, fuerza historico)
    python3 ingest_bcb_tco.py --from-file ARCHIVO   # parsea un archivo local (offline)
    python3 ingest_bcb_tco.py --debug               # vuelca el crudo a bcb_tco_raw.html
    python3 ingest_bcb_tco.py --url OTRA_URL        # override del endpoint
    python3 ingest_bcb_tco.py --manual --fecha 2026-06-26 --tco 9.76
"""

import argparse
import csv
import io
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from config import BCB_TCO_JSON

URL_HOME = "https://www.bcb.gob.bo/"  # portada: card TCO con HOY+MAÑANA (fuente primaria)
URL_TCO = "https://www.bcb.gob.bo/tco_reporte_detalle_historico.php"
# Endpoint del botón "Descargar CSV" (GET ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD),
# confirmado leyendo el <form class="vrd-export"> de la página (2026-06-29).
CSV_ENDPOINT = "tco_tcreferencial_descargar_csv.php"
OUTPUT = BCB_TCO_JSON
RAW_DUMP = Path("bcb_tco_raw.html")
HEADERS = {"User-Agent": "Mozilla/5.0 (binance_p2p_ingest)"}

# Rango plausible de un TCO BOB/USD. Acota candidatos numéricos para no confundir
# años (2026), montos o IDs con la cotización. El TCO arrancó ~6.9 y flota; un
# techo holgado (30) tolera deslizamientos futuros sin capturar basura.
TCO_MIN, TCO_MAX = 4.0, 30.0

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MONTH_ABBR = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}


# ── Fetch ────────────────────────────────────────────────────────────────────

def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def fetch(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as r:
        return _decode(r.read())


def _looks_like_tco_csv(text: str) -> bool:
    """¿El texto es el CSV del reporte (y NO el HTML del formulario, que también
    contiene 'TOTAL BANCOS' como encabezado de columna)?"""
    head = text.lstrip()[:400].lower()
    if head[:1] == "<" or any(t in head for t in (
            "<!doctype", "<html", "<section", "<style", "<form", "<div", "<script")):
        return False
    return ";" in text and "total bancos" in text.lower()


def _attr_val(tag: str, name: str) -> str | None:
    m = (re.search(name + r'\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
         or re.search(name + r"\s*=\s*'([^']*)'", tag, re.IGNORECASE))
    return m.group(1) if m else None


def _collect_fields(form_body: str) -> list[tuple]:
    """(name, value, type) de cada input/select/button del formulario."""
    out = []
    for tag in re.findall(r"<(?:input|select|button)\b[^>]*>", form_body, re.IGNORECASE):
        name = _attr_val(tag, "name")
        value = _attr_val(tag, "value")
        typ = (_attr_val(tag, "type")
               or ("select" if tag.lower().lstrip("<").startswith("select") else "text")).lower()
        out.append((name, value, typ))
    return out


def _submit(url: str, method: str, params: dict) -> str:
    if method == "post":
        req = Request(url, data=urlencode(params).encode(), headers=HEADERS)
    else:
        sep = "&" if "?" in url else "?"
        req = Request(url + sep + urlencode(params), headers=HEADERS)
    with urlopen(req, timeout=30) as r:
        return _decode(r.read())


def fetch_report(base_url: str, desde: str, hasta: str) -> str:
    """Obtiene el CSV del reporte TCO para el rango [desde, hasta] (YYYY-MM-DD).

    La página `tco_reporte_detalle_historico.php` es un FORMULARIO con dos date
    pickers y un botón "Descargar CSV". Estrategia, en orden:
      1) GET de base_url: si ya devuelve el CSV, listo.
      2) Introspección: lee el <form>, mapea los campos de fecha a desde/hasta,
         incluye el submit de CSV, y lo envía con el method/action reales (así no
         adivino los nombres de los params: los leo de la página).
      3) Fallback: GET con nombres de parámetros comunes + flag de export.
    Devuelve el texto del CSV. Lanza RuntimeError si nada rinde el CSV (con
    --debug el crudo queda en disco para fijar el endpoint a mano)."""
    # (0) Endpoint directo del botón "Descargar CSV" (camino confiable). La
    #     introspección queda como respaldo si el BCB renombra el endpoint.
    try:
        resp = _submit(urljoin(base_url, CSV_ENDPOINT), "get", {"desde": desde, "hasta": hasta})
        if _looks_like_tco_csv(resp):
            return resp
    except Exception as e:  # noqa: BLE001
        print(f"  (endpoint directo de CSV falló: {e})", file=sys.stderr)

    page = fetch(base_url)
    if _looks_like_tco_csv(page):
        return page

    # (2) Introspección de formularios
    for m in re.finditer(r"<form\b([^>]*)>(.*?)</form>", page, re.DOTALL | re.IGNORECASE):
        attrs, body = m.group(1), m.group(2)
        fields = _collect_fields(body)
        date_names = [n for n, v, t in fields
                      if n and (t == "date" or re.search(r"fecha|desde|hasta|inicio|\bfin\b|\bini\b",
                                                          n, re.IGNORECASE))]
        if not date_names:
            continue
        params = {n: (v or "") for n, v, t in fields if n and t not in ("submit", "button", "reset")}
        # Mapear el RANGO: preferir nombres explícitos (desde/hasta) sobre un
        # campo de fecha suelto (el de "Ver datos"). Si no hay nombres claros,
        # caer a los primeros dos date inputs en orden de documento.
        start_f = next((n for n in date_names if re.search(r"desde|inicio|\bini\b|from|start", n, re.I)), None)
        end_f = next((n for n in date_names if re.search(r"hasta|\bfin\b|to|end", n, re.I)), None)
        if start_f and end_f:
            params[start_f], params[end_f] = desde, hasta
        elif len(date_names) >= 2:
            params[date_names[0]], params[date_names[1]] = desde, hasta
        else:
            params[date_names[0]] = hasta
        # Incluir el submit que dispara la descarga de CSV (no el de "Ver datos")
        for n, v, t in fields:
            blob = f"{n or ''} {v or ''}".lower()
            if t in ("submit", "button") and ("csv" in blob or "descargar" in blob) and n:
                params[n] = v or ""
        action = urljoin(base_url, _attr_val(attrs, "action") or base_url)
        method = (_attr_val(attrs, "method") or "get").lower()
        try:
            resp = _submit(action, method, params)
            if _looks_like_tco_csv(resp):
                return resp
        except Exception as e:  # noqa: BLE001 — probamos el siguiente form
            print(f"  (intento de form falló: {e})", file=sys.stderr)

    # (3) Fallback: nombres comunes + flag de export
    for a, b in (("desde", "hasta"), ("fecha_ini", "fecha_fin"),
                 ("fechaInicio", "fechaFin"), ("inicio", "fin")):
        for extra in ({}, {"csv": "1"}, {"export": "csv"}, {"descargar": "csv"}):
            try:
                resp = _submit(base_url, "get", {a: desde, b: hasta, **extra})
                if _looks_like_tco_csv(resp):
                    return resp
            except Exception:  # noqa: BLE001
                pass

    raise RuntimeError(
        "no pude obtener el CSV del reporte (la página devolvió el formulario, no "
        "el CSV). Corré con --debug y revisá bcb_tco_raw.html para fijar el "
        "endpoint/params exactos del botón 'Descargar CSV'.")


# ── Parsers de fecha / número ────────────────────────────────────────────────

def parse_fecha(s: str) -> str | None:
    """Devuelve 'YYYY-MM-DD' o None. Tolera los formatos que suele usar el BCB:
        2026-06-26 · 26/06/2026 · 26-06-2026 · 26 de junio de 2026 · 26-jun-2026
    """
    if not s:
        return None
    s = s.strip()

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        y, mo, d = map(int, m.groups())
        if 2020 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", s, re.IGNORECASE)
    if m:
        mo = SPANISH_MONTHS.get(m.group(2).lower())
        if mo:
            return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(1)):02d}"

    m = re.search(r"\b(\d{1,2})[-\s]([a-z]{3})[-\s.]*(\d{4})\b", s, re.IGNORECASE)
    if m:
        mo = MONTH_ABBR.get(m.group(2).lower())
        if mo:
            return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(1)):02d}"

    return None


def parse_rate(s: str) -> float | None:
    """Devuelve el TCO como float si el token PARECE una cotización (tiene
    decimales y cae en el rango plausible), o None. Exigir el separador decimal
    evita capturar días/años/enteros sueltos."""
    if not s:
        return None
    m = re.search(r"\d{1,2}[.,]\d{1,4}", s.strip())
    if not m:
        return None
    token = m.group(0)
    try:
        # "1.234,56" → 1234.56 ; "9,76" → 9.76 ; "9.76" → 9.76
        if "," in token:
            val = float(token.replace(".", "").replace(",", "."))
        else:
            val = float(token)
    except ValueError:
        return None
    return val if TCO_MIN <= val <= TCO_MAX else None


# ── Parser de la PORTADA (https://www.bcb.gob.bo/) ───────────────────────────
# La portada trae un card "Tipo de cambio oficial" (clase is-tc-oficial) con HOY
# y MAÑANA, y va por DELANTE del detalle histórico (tco_reporte_detalle_*), que
# tiene rezago: la portada ya muestra MAÑANA cuando el detalle aún no la publicó.
# Por eso es la fuente primaria. Server-rendered (validado 2026-06-30): los
# valores están en el HTML, no se cargan por JS. Estructura:
#   <article class="bcb-kpi2-card is-tc-oficial">
#     <time datetime="2026-06-29">LUNES 29 ... / MARTES 30 ...</time>
#     <div class="bcb-tco-duo-label">Hoy <span>Hasta 00:00</span></div>
#     <div class="bcb-tco-duo-num">9,73</div>
#     <div class="bcb-tco-duo-label">Mañana <span>MARTES 30 DE JUNIO, 2026</span></div>
#     <div class="bcb-tco-duo-num">9,76</div>

def _parse_es_date_home(text: str) -> str | None:
    """'MARTES 30 DE JUNIO, 2026' → '2026-06-30'. None si no parsea."""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s+DE\s+([A-Za-zÁÉÍÓÚáéíóúÑñ]+)[,]?\s+(\d{4})", text)
    if not m:
        return None
    dia, mes, anio = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    mm = SPANISH_MONTHS.get(mes)
    if not mm:
        return None
    try:
        return date(anio, mm, dia).isoformat()
    except ValueError:
        return None


def parse_homepage_tco(html: str) -> list[dict]:
    """Extrae [HOY, MAÑANA] del card 'Tipo de cambio oficial' de la portada.

    Devuelve [{fecha, tco}] (0, 1 o 2 entradas). Robusto: se acota al card
    is-tc-oficial (evita falsos positivos como el color CSS rgba(8,49,76,…)) y
    valida cada número con parse_rate (exige decimal + rango plausible). HOY toma
    la fecha del <time datetime>; MAÑANA, la del primer <span> del card que
    parsea como fecha ('Hasta 00:00' no parsea)."""
    # Anclar en el PRIMER bcb-tco-duo-num REAL (markup con valor: ...num">9,73<).
    # NO usar html.find("is-tc-oficial"): esa clase también aparece ARRIBA en el
    # <style> de la página (regla .bcb-kpi2-card.is-tc-oficial{…}), muy lejos del
    # markup, y la ventana caería sobre el CSS sin los valores. El CSS de la clase
    # `.bcb-tco-duo-num{…}` lleva `{`, no `">`, así que el regex la ignora.
    anchor = re.search(r'bcb-tco-duo-num"[^>]*>\s*[\d.]*\d[,.]\d', html)
    if not anchor:
        return []
    a = anchor.start()
    seg = html[a:a + 3000]  # ventana hacia adelante: ambos valores + span de MAÑANA
    nums = re.findall(r'bcb-tco-duo-num"[^>]*>\s*([\d.]*\d[,.]\d+)\s*<', seg)
    # HOY: el <time datetime> más cercano ANTES del anchor (el del card TCO).
    times = re.findall(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})"', html[:a])
    hoy = times[-1] if times else None
    # MAÑANA: primer <span> con fecha DESPUÉS del anchor ("Hasta 00:00" no parsea).
    manana = None
    for s in re.findall(r"<span>([^<]+)</span>", seg):
        d = _parse_es_date_home(s)
        if d:
            manana = d
            break
    out = []
    if hoy and len(nums) >= 1:
        v = parse_rate(nums[0])
        if v is not None:
            out.append({"fecha": hoy, "tco": v})
    if manana and len(nums) >= 2:
        v = parse_rate(nums[1])
        if v is not None:
            out.append({"fecha": manana, "tco": v})
    return out


# ── Parsers de contenido ─────────────────────────────────────────────────────

def _strip_tags(cell: str) -> str:
    return re.sub(r"<[^>]+>", " ", cell).strip()


def _csv_num(s: str) -> float | None:
    """Número del CSV del BCB: decimal con coma, miles con punto.
    '9,7300' → 9.73 ; '17.323.468' → 17323468.0 ; '' / '-' → None."""
    s = (s or "").strip()
    if s in ("", "-"):
        return None
    try:
        if "," in s:
            return float(s.replace(".", "").replace(",", "."))
        return float(s.replace(".", ""))
    except ValueError:
        return None


def parse_tco_csv(text: str) -> list[dict]:
    """Parser del CSV oficial del BCB (`tco_reporte_detalle_historico.php`).

    Formato real (verificado 2026-06-29): delimitado por `;`. Por día hay N filas
    de detalle (una por nivel de precio: `Fecha; TC; <por banco: N°, Monto>...;
    TOTAL BANCOS N°, Monto`), una fila `TOTAL` y una fila `TCO` con el promedio
    ponderado ya calculado por el BCB. La columna `TOTAL BANCOS` de la fila `TCO`
    es el **TCO oficial del día**.

    Estrategia: LEEMOS el TCO publicado (no lo inventamos) y, como chequeo de
    integridad, RECALCULAMOS el promedio ponderado por monto del detalle
    (fórmula del Anexo II) y avisamos si difieren > 0.01. Soporta múltiples días
    en un mismo archivo (reporte por rango)."""
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))

    # Índice de la columna "TOTAL BANCOS" (desde el header que arranca con 'Fecha')
    total_idx = None
    for r in rows:
        if r and r[0].strip().lower() == "fecha":
            for i, c in enumerate(r):
                if "total bancos" in c.lower():
                    total_idx = i
                    break
            break

    # TCO publicado por fecha (fila etiqueta 'TCO', columna TOTAL BANCOS)
    publicado: dict[str, float] = {}
    for r in rows:
        if len(r) > 1 and r[1].strip().upper() == "TCO":
            fecha = parse_fecha(r[0])
            if not fecha:
                continue
            val = None
            if total_idx is not None and total_idx < len(r):
                val = parse_rate(r[total_idx])
            if val is None:  # fallback: última cotización plausible de la fila
                cand = [x for x in (parse_rate(c) for c in r[2:]) if x is not None]
                val = cand[-1] if cand else None
            if val is not None:
                publicado[fecha] = val

    # Recalculo (verificación): Σ(precio×monto)/Σ(monto) del detalle, por fecha
    calc_num: dict[str, float] = {}
    calc_den: dict[str, float] = {}
    if total_idx is not None:
        for r in rows:
            if len(r) <= total_idx + 1:
                continue
            fecha = parse_fecha(r[0])
            if not fecha:
                continue
            label = r[1].strip().upper()
            if label in ("TCO", "TOTAL"):
                continue
            precio = _csv_num(r[1])
            monto = _csv_num(r[total_idx + 1])
            if precio is None or monto is None or monto <= 0:
                continue
            calc_num[fecha] = calc_num.get(fecha, 0.0) + precio * monto
            calc_den[fecha] = calc_den.get(fecha, 0.0) + monto

    out = []
    fechas = set(publicado) | set(calc_den)
    for fecha in sorted(fechas):
        pub = publicado.get(fecha)
        calc = round(calc_num[fecha] / calc_den[fecha], 2) if calc_den.get(fecha) else None
        if pub is not None and calc is not None and abs(pub - calc) > 0.01:
            print(f"WARNING: {fecha} TCO publicado {pub} ≠ recalculado {calc} "
                  f"(usando el publicado)", file=sys.stderr)
        tco = pub if pub is not None else calc
        if tco is None:
            continue
        verif = "ok" if (pub is not None and calc is not None and abs(pub - calc) <= 0.01) \
            else ("solo-publicado" if calc is None else "solo-calculado")
        print(f"  {fecha}: TCO {tco} (publicado={pub}, recalculado={calc}, verif={verif})")
        out.append({"fecha": fecha, "tco": tco})
    return out


def parse_csv(text: str) -> list[dict]:
    """Parsea un CSV (o pseudo-CSV) de fecha + TCO. Detecta el delimitador y, por
    cada fila, toma la primera celda que parsea como fecha y la primera que parsea
    como cotización plausible."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        delim = ";" if line.count(";") >= line.count(",") and ";" in line else ","
        cells = [c.strip().strip('"') for c in line.split(delim)]
        fecha = next((f for f in (parse_fecha(c) for c in cells) if f), None)
        if not fecha:
            continue
        tco = next((r for r in (parse_rate(c) for c in cells) if r is not None), None)
        if tco is None:
            continue
        out.append({"fecha": fecha, "tco": tco})
    return out


def parse_html(text: str) -> list[dict]:
    """Extrae pares (fecha, TCO) de las tablas HTML. Cubre dos orientaciones:
      (a) fila = (fecha, valor)  — el caso típico de un 'detalle histórico'.
      (b) headers = fechas + una fila de valores (tabla transpuesta estilo BCB).
    Devuelve candidatos deduplicados por fecha (gana el último visto)."""
    by_fecha: dict[str, float] = {}

    for table in re.findall(r"<table[^>]*>(.*?)</table>", text, re.DOTALL | re.IGNORECASE):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL | re.IGNORECASE)
        parsed_rows = []
        for row in rows:
            cells = [_strip_tags(c) for c in
                     re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)]
            parsed_rows.append(cells)

        # (a) fila = (fecha, valor)
        for cells in parsed_rows:
            fecha = next((f for f in (parse_fecha(c) for c in cells) if f), None)
            if not fecha:
                continue
            tco = next((r for r in (parse_rate(c) for c in cells) if r is not None), None)
            if tco is not None:
                by_fecha[fecha] = tco

        # (b) transpuesta: una fila de fechas + fila etiquetada TCO/promedio/oficial
        header_dates = [parse_fecha(c) for c in (parsed_rows[0] if parsed_rows else [])]
        if any(header_dates):
            label_re = re.compile(r"PROMEDIO\s+PONDERADO|TIPO\s+DE\s+CAMBIO|\bTCO\b|OFICIAL",
                                  re.IGNORECASE)
            for cells in parsed_rows[1:]:
                if cells and label_re.search(cells[0]):
                    # Alinear por la DERECHA: las columnas de datos son las finales,
                    # tolera que el header tenga (o no) una celda esquina inicial.
                    n = min(len(header_dates), len(cells))
                    for d, raw in zip(header_dates[-n:], cells[-n:]):
                        if not d:
                            continue
                        r = parse_rate(raw)
                        if r is not None:
                            by_fecha.setdefault(d, r)
                    break

    return [{"fecha": f, "tco": v} for f, v in by_fecha.items()]


def parse_content(text: str) -> list[dict]:
    """Despacha al parser correcto. Prioridad: (1) CSV oficial del BCB con su
    fila 'TCO' (el caso real); (2) HTML si la fuente es la página; (3) CSV
    genérico como último recurso."""
    # (1) CSV oficial del BCB — lo identifica el header 'TOTAL BANCOS' (firma
    #     estructural del reporte). Cubre el caso normal (con fila 'TCO') y el
    #     borde sin fila 'TCO' (recalcula del detalle).
    if ";" in text and re.search(r"total\s+bancos", text, re.IGNORECASE):
        entries = parse_tco_csv(text)
        if entries:
            return entries
    # (2)/(3) Fallbacks defensivos (formato desconocido / página HTML).
    looks_html = bool(re.search(r"<\s*(table|html|td|tr|body)\b", text, re.IGNORECASE))
    entries = parse_html(text) if looks_html else parse_csv(text)
    if not entries:
        entries = parse_csv(text) if looks_html else parse_html(text)
    return entries


# ── Persistencia ─────────────────────────────────────────────────────────────

def save_entries(entries: list[dict], dry_run: bool = False) -> None:
    """Agrega/actualiza al histórico JSON. Dedup por fecha; no pisa con None.
    Mismo contrato que bcb_referencial.save_entries."""
    if dry_run:
        print(f"[DRY RUN] {len(entries)} entradas no escritas")
        for e in sorted(entries, key=lambda x: x["fecha"])[-8:]:
            print(f"  {e['fecha']}: TCO {e['tco']}")
        return

    history = []
    if OUTPUT.exists():
        try:
            prev = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if isinstance(prev, list):
                history = prev
        except Exception as e:
            print(f"WARNING: no pude leer histórico previo: {e}", file=sys.stderr)

    by_fecha = {h.get("fecha"): h for h in history if h.get("fecha")}
    added = updated = 0
    for e in entries:
        if not e.get("fecha"):
            continue
        if e["fecha"] in by_fecha:
            cur = by_fecha[e["fecha"]]
            changed = False
            for k, v in e.items():
                if v is None:
                    continue
                if cur.get(k) != v:
                    cur[k] = v
                    changed = True
            if changed:
                updated += 1
        else:
            by_fecha[e["fecha"]] = dict(e)
            added += 1

    new_hist = sorted(by_fecha.values(), key=lambda h: h.get("fecha") or "")
    OUTPUT.write_text(json.dumps(new_hist, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{added} agregadas, {updated} actualizadas ({len(new_hist)} entradas totales): {OUTPUT}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scraper del Tipo de Cambio Oficial (TCO) del BCB")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-file", help="Parsear un archivo local (CSV o HTML) en vez de la red")
    parser.add_argument("--debug", action="store_true",
                        help=f"Volcar el contenido crudo a {RAW_DUMP} para inspección")
    parser.add_argument("--url", default=URL_TCO, help="Override del endpoint del BCB")
    parser.add_argument("--desde", help="Fecha inicial del rango YYYY-MM-DD (default: hoy-7 BO)")
    parser.add_argument("--hasta", help="Fecha final del rango YYYY-MM-DD (default: hoy BO)")
    parser.add_argument("--backfill", action="store_true",
                        help="Rango desde el inicio del régimen (2026-06-26, RD 88/2026)")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--fecha")
    parser.add_argument("--tco", type=float)
    parser.add_argument("--source", default="manual")
    parser.add_argument("--via", choices=["portada", "historico"], default="portada",
                        help="Fuente del TCO: 'portada' (default, fresca: HOY+MAÑANA de "
                             "bcb.gob.bo) o 'historico' (detalle CSV, para backfill/verificación)")
    args = parser.parse_args()

    # El backfill necesita el rango histórico del detalle CSV; la portada solo
    # tiene HOY+MAÑANA. El resto del tiempo, la portada es la fuente primaria
    # (va por delante del detalle, que tiene rezago).
    via = "historico" if args.backfill else args.via

    # Entrada manual (backfill puntual / corrección)
    if args.manual:
        if not (args.fecha and args.tco is not None):
            print("ERROR: --manual requiere --fecha YYYY-MM-DD --tco X.XX", file=sys.stderr)
            sys.exit(2)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.fecha):
            print(f"ERROR: --fecha debe ser YYYY-MM-DD, recibí: {args.fecha}", file=sys.stderr)
            sys.exit(2)
        entry = {"fecha": args.fecha, "tco": args.tco, "source": args.source}
        print(f"Manual -- {entry['fecha']}: TCO Bs {entry['tco']}")
        save_entries([entry], dry_run=args.dry_run)
        return

    # Obtener contenido (red o archivo local)
    if args.from_file:
        content = Path(args.from_file).read_text(encoding="utf-8", errors="replace")
        print(f"Leído de archivo local: {args.from_file} ({len(content)} chars)")
    elif via == "portada":
        try:
            content = fetch(URL_HOME)
        except Exception as e:
            print(f"ERROR: no pude bajar la portada {URL_HOME}: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Portada BCB descargada ({len(content)} chars)")
        if args.debug:
            RAW_DUMP.write_text(content, encoding="utf-8")
            print(f"[DEBUG] HTML crudo volcado a {RAW_DUMP} ({len(content)} chars)")
    else:
        # Rango de fechas. Default: ventana móvil de 7 días (AUTORREPARABLE — si una
        # corrida se pierde un día, la del día siguiente lo recupera, ya que el
        # reporte exporta todas las fechas publicadas dentro del rango). El TCO se
        # publica 20:00 BO; el cron corre 20:05 BO = 00:05 UTC del día siguiente,
        # así que "hoy BO" = UTC-4.
        bo_today = (datetime.now(timezone.utc) - timedelta(hours=4)).date()
        # Buffer de +5 días en `hasta`: el BCB fecha el TCO por su VIGENCIA (el
        # próximo día hábil), que va por DELANTE de "hoy" — el cierre del viernes
        # se publica como vigente el lunes (regla de fin de semana, RD 88/2026).
        # El endpoint solo exporta fechas publicadas, así que pedir de más es
        # inocuo; +5 cubre fines de semana largos (feriados).
        hasta = args.hasta or (bo_today + timedelta(days=5)).isoformat()
        if args.backfill:
            desde = args.desde or "2026-06-26"  # entrada en vigencia del nuevo régimen
        else:
            desde = args.desde or (bo_today - timedelta(days=14)).isoformat()
        try:
            content = fetch_report(args.url, desde, hasta)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            if args.debug:
                try:
                    RAW_DUMP.write_text(fetch(args.url), encoding="utf-8")
                    print(f"[DEBUG] página cruda volcada a {RAW_DUMP}", file=sys.stderr)
                except Exception:  # noqa: BLE001
                    pass
            sys.exit(1)
        print(f"Reporte TCO descargado (rango {desde} → {hasta})")
        if args.debug:
            RAW_DUMP.write_text(content, encoding="utf-8")
            print(f"[DEBUG] CSV crudo volcado a {RAW_DUMP} ({len(content)} chars)")

    if via == "portada":
        entries = parse_homepage_tco(content)
        fuente = "bcb_tco_portada"
    else:
        entries = parse_content(content)
        fuente = "bcb_tco"
    for e in entries:
        e["source"] = fuente

    if not entries:
        print("ERROR: no parseé ninguna entrada de TCO. Revisá el formato de la "
              "fuente; corré con --debug para volcar el crudo y ajustar el parser.",
              file=sys.stderr)
        if not args.debug and not args.from_file:
            RAW_DUMP.write_text(content, encoding="utf-8")
            print(f"(crudo guardado en {RAW_DUMP} para inspección)", file=sys.stderr)
        sys.exit(1)

    # Sello de fetch en la fecha más reciente (metadata)
    latest_fecha = max(e["fecha"] for e in entries)
    today_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for e in entries:
        if e["fecha"] == latest_fecha:
            e["fetched_at_utc"] = today_iso

    fechas = sorted(e["fecha"] for e in entries)
    print(f"TCO parseado: {len(entries)} días ({fechas[0]} → {fechas[-1]})")
    save_entries(entries, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
