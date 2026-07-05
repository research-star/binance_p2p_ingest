"""extract.py — Campos estructurados por comunicado ASFI (para las tablitas).

Los comunicados del RMV son formulaicos ("Comunica que, el X, el Banco Y
procedió al desembolso de BsZ…"), así que los datos que el frontend tabula
(quién, monto, instrumento, cupón, cargo, persona) se extraen con regex —
determinístico, gratis y re-corrible sobre la data ya persistida (los JSON
guardan `texto` completo; `ingest_asfi.py --reextraer` recomputa todo esto
sin re-bajar PDFs).

Cada item gana:
  - `grupo`:  a qué tablita del frontend pertenece (GRUPOS) — 'otros' va a la
              lista general.
  - `campos`: dict de campos extraídos (solo los que matchearon; el frontend
              muestra "—" para los ausentes).

La extracción es best-effort: un campo ausente NUNCA es error — la fila cae
con la entidad + resumen igual. No inventa: si el regex no matchea, no hay campo.
"""
from __future__ import annotations

import re

GRUPOS = ("emisiones", "cupones", "prestamos", "personal", "dividendos",
          "compromisos", "calificaciones", "otros")

# ── Regex compartidos ────────────────────────────────────────────────────────

_RE_DENOM = re.compile(r"[“\"]([^”\"]{3,80})[”\"]")
_RE_REGISTRO = re.compile(r"ASFI/DSV-[A-Z0-9]+(?:-[A-Z0-9]+)*/\d{4}")
_RE_PIZARRA = re.compile(r"\b[A-Z]{2,4}-[A-Z0-9]{3}-[0-9]{2}\b")
# Excluye comillas tipográficas del capture: sin eso, en «Emisión de Bonos
# denominada “X” de EMISOR S.A.» el lazy arranca en el primer «de» y se traga
# todo hasta el S.A. (visto en calibración con Tienda Amiga).
_RE_EMISOR = re.compile(
    r"(?:de|emisora?)\s+([A-Z0-9ÁÉÍÓÚÑ][^,\n“”\"]{2,70}?(?:S\.\s?A\.|S\.\s?R\.\s?L\.|LTDA\.?|Ltda\.?))")
_RE_MONTO_BS = re.compile(r"Bs\.?\s?([\d\.]+(?:,\d{1,2})?)")
_RE_BANCO = re.compile(r"(Banco [A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\. ]{1,35}?S\.A\.)")
_RE_CUPON_N = re.compile(r"[Cc]up[oó]n\s+N[°º]?\s*(\d+)")
_RE_INSTRUMENTO = re.compile(
    r"((?:Bonos|BONOS|Pagarés|PAGARÉS)(?:\s+(?:Subordinados|Sociales|Bursátiles|SOCIALES|BURSÁTILES))?"
    r"\s+[A-ZÁÉÍÓÚÑ0-9][^,\.\(\n]{1,55}?|VALORES DE TITULARIZACIÓN\s+[A-ZÁÉÍÓÚÑ0-9 ]{3,45})"
    r"(?:\s*[\(,\.]| dentro| - | –|$)")
_RE_FECHA_LARGA = re.compile(r"a partir del (\d{1,2} de [a-záéíóú]+(?: de \d{4})?)")
_RE_PERSONA = re.compile(
    r"señor(?:a|es|ita)?[\s:]+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){1,4})")
_RE_CARGO = re.compile(
    r"(?:cargos? de|en el cargo de|como|funciones de)\s+"
    r"([A-ZÁÉÍÓÚÑ][^,\.\n:]{3,70}?)(?:\s+a\.i\.)?\s*[,\.\n]")
_MOVIMIENTOS = [
    ("renuncia", re.compile(r"renuncia", re.I)),
    ("desvinculación", re.compile(r"desvincul", re.I)),
    ("remoción", re.compile(r"remoci[óo]n|remover", re.I)),
    ("designación a.i.", re.compile(r"design\w+ (?:temporal|interin)|a\.i\.", re.I)),
    ("designación", re.compile(r"design(?:ó|a\b|ación)", re.I)),
    ("nombramiento", re.compile(r"nombramiento|nombrar", re.I)),
]
_RE_CAP = re.compile(r"\(CAP\)[\s\S]{0,80}?([\d]{1,3}[.,]\d{1,2})\s*%")
_RE_CAP2 = re.compile(r"CAP\s*>?\s*=?\s*\d+\s*%[\s\S]{0,20}?([\d.,]+)\s*%")
_RE_IL = re.compile(r"(?:Liquidez|IL)[\s\S]{0,80}?>?\s*=?\s*\d+\s*%[\s\S]{0,20}?([\d.,]+)\s*%")
_RE_IC = re.compile(r"(?:Cobertura|IC)\s*\(?I?C?\)?[\s\S]{0,80}?>?\s*=?\s*\d+\s*%[\s\S]{0,20}?([\d.,]+)\s*%")


def _monto_corto(raw: str) -> str:
    """'25.000.000,00' → 'Bs 25,0 M' (formato boliviano: punto=miles, coma=decimal)."""
    try:
        v = float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        return f"Bs {raw}"
    if v >= 1e6:
        return f"Bs {v/1e6:.1f}".replace(".", ",") + " M"
    if v >= 1e3:
        return f"Bs {v/1e3:.0f} mil"
    return f"Bs {v:.0f}"


def clasificar_grupo(item: dict) -> str:
    """Tablita destino. Prioridad pensada para la lectura del día: lo
    administrativo-bursátil primero, juntas/resoluciones genéricas a 'otros'."""
    tags = set(item.get("tags", ()))
    seccion = item.get("seccion", "")
    cat = item.get("categoria", "")
    texto = item.get("texto", "")
    # Emisiones = SOLO actos regulatorios (autorizar/inscribir); "aprobar una
    # emisión" en una junta o "sin Oferta Pública" NO son emisiones autorizadas.
    if "emision" in tags and seccion in ("Resoluciones Administrativas",
                                         "Cartas de Autorización") \
            and re.search(r"[Aa]utoriza|[Ii]nscribe", texto):
        return "emisiones"
    if "junta" in tags:
        return "otros"          # juntas = multi-decisión, van a la lista general
    if "cupon" in tags:
        return "cupones"
    if "compromisos" in tags:
        return "compromisos"
    if "calificacion" in tags and "Calificadoras" in cat:
        return "calificaciones"
    if "personal" in tags:
        return "personal"
    # Desembolsos de patrimonios autónomos (titularización) NO son préstamos
    # bancarios a empresas — van a la lista general.
    if "prestamo" in tags and "patrimonio autónomo" not in texto.lower():
        return "prestamos"
    if "dividendos" in tags:
        return "dividendos"
    return "otros"


def extraer_campos(item: dict) -> dict:
    """Campos según grupo. Solo claves que matchearon (best-effort)."""
    texto = item.get("texto", "")
    grupo = item.get("grupo") or clasificar_grupo(item)
    c: dict = {}

    if grupo == "emisiones":
        m = _RE_DENOM.search(texto)
        if m:
            c["instrumento"] = m.group(1)
        m = _RE_EMISOR.search(texto)
        if m:
            c["emisor"] = " ".join(m.group(1).split())
        m = _RE_REGISTRO.search(texto)
        if m:
            c["registro"] = m.group(0)
        m = _RE_PIZARRA.search(texto)
        if m:
            c["pizarra"] = m.group(0)

    elif grupo == "cupones":
        m = _RE_CUPON_N.search(texto)
        if m:
            c["cupon_n"] = m.group(1)
        m = _RE_INSTRUMENTO.search(texto)
        if m:
            inst = " ".join(m.group(1).split()).rstrip(" -–")
            # El char-class excluye '.', así que "GAS & ELECTRICIDAD S.A."
            # queda cortado en " S" — se recompone el sufijo societario.
            inst = re.sub(r"\sS$", " S.A.", inst)
            c["instrumento"] = inst
        m = _RE_FECHA_LARGA.search(texto)
        if m:
            c["fecha_pago"] = m.group(1)
        c["estado"] = "pagado" if re.search(r"concluy[óo]", texto) else "programado"
        if "amortización" in texto.lower():
            c["amortiza"] = "sí"

    elif grupo == "prestamos":
        m = _RE_BANCO.search(texto)
        if m:
            c["banco"] = m.group(1)
        m = _RE_MONTO_BS.search(texto)
        if m:
            c["monto"] = _monto_corto(m.group(1))

    elif grupo == "personal":
        m = _RE_PERSONA.search(texto)
        if m:
            c["persona"] = m.group(1)
        m = _RE_CARGO.search(texto)
        if m:
            cargo = " ".join(m.group(1).split())
            cargo = re.sub(r"\s+a$", "", cargo)  # resto de "a.i." cortado por el punto
            c["cargo"] = cargo[:60]
        for nombre, rx in _MOVIMIENTOS:
            if rx.search(texto):
                c["movimiento"] = nombre
                break

    elif grupo == "dividendos":
        m = _RE_FECHA_LARGA.search(texto)
        if m:
            c["fecha_pago"] = m.group(1)

    elif grupo == "compromisos":
        m = _RE_CAP2.search(texto) or _RE_CAP.search(texto)
        if m:
            c["cap"] = (m.group(1) or "").replace(",", ".") + "%"
        m = _RE_IL.search(texto)
        if m:
            c["liquidez"] = m.group(1).replace(",", ".") + "%"
        m = _RE_IC.search(texto)
        if m:
            c["cobertura"] = m.group(1).replace(",", ".") + "%"

    # 'calificaciones' y 'otros': sin campos tabulares (tablas de ratings son
    # demasiado irregulares para regex confiable — entidad + resumen alcanzan).
    return c


def enriquecer(item: dict) -> dict:
    """Agrega/recomputa grupo + campos in-place (idempotente). NO toca
    resumen/resumen_origen — eso es territorio de resumen.py."""
    item["grupo"] = clasificar_grupo(item)
    campos = extraer_campos(item)
    if campos:
        item["campos"] = campos
    else:
        item.pop("campos", None)
    return item
