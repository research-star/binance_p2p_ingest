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

V2 (feedback Diego 2026-07-05): grupos nuevos `directorio` (sale/entra/
ratificado — el antes→después silla-por-silla no es extraíble: ASFI no publica
el mapeo, solo la lista final), `juntas` (convocatorias con fecha y agenda,
donde cae el caso MADISA "distribución de resultados"), `uso_fondos`,
`auditorias`; dividendos con monto (Bs/USD, total o por acción); compromisos
generalizado a TODOS los pares indicador/compromiso/valor con evaluación de
cumplimiento (incluye CDD/CCC/CAF de titularizadoras — caso iBolsa).

V3 (fase 2a, 2026-07-12): re-taxonomía para desinflar `otros` (1.836→~750 sobre
la data de ene–jul 2026) promoviendo señal que ya existía en tags/texto:
  - `juntas` ahora captura asambleas/actas REALIZADAS (multi-decisión
    "determinó lo siguiente: 1… 2…"), no solo convocatorias.
  - `emisiones` capta inscripción vía Comité/Bolsa y autorizaciones formales
    (Resolución/Carta) sin depender del tag `emision`.
  - `personal`/`prestamos`/`dividendos` amplían por verbo textual.
  - `titularizacion` (GRUPO NUEVO): desembolsos/convocatorias/reportes de
    patrimonios autónomos (BDP ST, iBolsa ST y símiles).
  - `compromisos` se PARTE en `compromisos_reportados` (con indicadores
    parseados) y `compromisos_anunciados` (fecha+texto; los que traen tabla
    rota por el aplanado pypdf quedan marcados `tabla_no_parseada` para el P2).
Cada item gana además `grupo_v` (versión de taxonomía = TAXONOMIA_V) y
`revisado` ('provisional' hasta curación humana). El detalle de calibración,
falsos positivos y decisiones de prioridad vive en
`asfi_ingest/CUADERNO_HECHOS_RELEVANTES.md`.

V4 (fase 2A, propuesta local): conserva `grupo`/`campos` como compatibilidad y
añade tipo, subtipo, clave compuesta, eventos secundarios, tags, campos
estructurados y contrato de tablas fuente mediante `taxonomy_v4`. Persistir
esta capa sobre los JSON requiere una autorización posterior.
"""
from __future__ import annotations

import re

from . import taxonomy_v4

# Versión de la taxonomía. Se estampa en cada item (`grupo_v`) para que un pase
# futuro pueda re-clasificar selectivamente. V1 = implícito (items sin el campo).
# V3 (fase 2b.1b): amplía verbos de préstamo ("adquirió un préstamo/línea de
# crédito", drift léxico visto en 2025) y de fin laboral ("finalizó/concluyó la
# relación/vinculación laboral", "dejó de ejercer/prestar/pertenecer", "cese de
# funciones") — cierra ~69/año (préstamo) + ~5-7/año (personal) que caían a 'otros'.
TAXONOMIA_V = taxonomy_v4.TAXONOMIA_V

GRUPOS = ("emisiones", "cupones", "prestamos", "directorio", "personal",
          "dividendos", "uso_fondos", "compromisos_reportados",
          "compromisos_anunciados", "titularizacion", "auditorias", "juntas",
          "calificaciones", "otros")

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
# Dividendos pueden venir en USD y/o "por acción".
_RE_MONTO_DIV = re.compile(
    r"(Bs|USD|\$us|US\$|Dólares(?: Americanos)?)\.?\s?([\d\.]+(?:,\d{1,6})?)"
    r"(\s*(?:por acci[óo]n|/acci[óo]n))?", re.I)
_RE_BANCO = re.compile(r"(Banco [A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\. ]{1,35}?S\.A\.)")
_RE_CUPON_N = re.compile(r"[Cc]up[oó]n\s+N[°º]?\s*(\d+)")
_RE_INSTRUMENTO = re.compile(
    r"((?:Bonos|BONOS|Pagarés|PAGARÉS)(?:\s+(?:Subordinados|Sociales|Bursátiles|SOCIALES|BURSÁTILES))?"
    r"\s+[A-ZÁÉÍÓÚÑ0-9][^,\.\(\n]{1,55}?|VALORES DE TITULARIZACIÓN\s+[A-ZÁÉÍÓÚÑ0-9 ]{3,45})"
    r"(?:\s*[\(,\.]| dentro| - | –|$)")
_RE_FECHA_LARGA = re.compile(r"a partir del (\d{1,2} de [a-záéíóú]+(?: de \d{4})?)")
_RE_PERSONA = re.compile(
    r"señor(?:a|es|ita)?[\s:]+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){1,4})")
# Dos formas: "en el cargo de X," y "a los cargos: X, Y y Z, siendo…" (Nistahuz).
_RE_CARGO = re.compile(
    r"(?:cargos? de|en el cargo de|como|funciones de)\s+"
    r"([A-ZÁÉÍÓÚÑ][^,\.\n:]{3,70}?)(?:\s+a\.i\.)?\s*[,\.\n]")
_RE_CARGOS_LISTA = re.compile(
    r"cargos?:\s*([A-ZÁÉÍÓÚÑ][^\.\n]{3,140}?)(?:,\s+siendo|\.\s|\.$|$)")
_MOVIMIENTOS = [
    ("renuncia", re.compile(r"renuncia", re.I)),
    ("desvinculación", re.compile(r"desvincul", re.I)),
    ("remoción", re.compile(r"remoci[óo]n|remover", re.I)),
    ("designación a.i.", re.compile(r"design\w+ (?:temporal|interin)|a\.i\.", re.I)),
    ("designación", re.compile(r"design(?:ó|a\b|ación)", re.I)),
    ("nombramiento", re.compile(r"nombramiento|nombrar", re.I)),
]

# Compromisos financieros: pares "SIGLA op umbral valor" tal como los aplana el
# parser desde las tablas ("CAP>=11% 13.82%", "CDD >= 1,10 7,95", "CAF <=2,00 1,93").
_RE_INDICADOR = re.compile(
    r"\(?([A-Z]{2,5})\)?:?\s*(>=|<=|=>|=<)\s*([\d]+(?:[.,]\d+)?)\s*%?\s+"
    r"(?:\(i\)\s*)?([\d]+(?:[.,]\d+)?)\s*%?")
# Variante verbal (estilo BCP): "Coeficiente de Adecuación Patrimonial mayor o
# igual al 11% … fue de 13,07%".
_RE_INDICADOR_VERBAL = re.compile(
    r"((?:Coeficiente|Ratio|Índice) de [A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ ]{2,45})"
    r"[\s\S]{0,120}?(mayor|menor) o igual (?:a|al)?\s*([\d]+(?:[.,]\d+)?)\s*%"
    r"[\s\S]{0,200}?fue de\s*([\d]+(?:[.,]\d+)?)\s*%")
_SIGLAS_VERBAL = [("Adecuación Patrimonial", "CAP"), ("Liquidez", "Liquidez"),
                  ("Cobertura", "Cobertura"), ("Mora", "Mora")]

# Directorio: remociones / nombramientos / ratificaciones. Cada patrón declara
# su orden de grupos con 'nc' (nombres, cargo) o 'cn' (cargo, nombres) — las
# redacciones de ASFI alternan ambos y vienen en singular Y plural.
_SENOR = r"señor\w*"
_DE_SENOR = r"de(?:l| los| la| las)? " + _SENOR
_A_SENOR = r"a(?:l| los| la| las)?(?: " + _SENOR + r")?"
_RE_DIR_SALEN = [
    ("nc", re.compile(r"[Rr]emoci[óo]n " + _DE_SENOR + r":?\s*([^\.]+?)\s+de(?:l| sus?) cargos? de ([A-ZÁÉÍÓÚÑ][^\.,;]{3,50})")),
    ("cn", re.compile(r"[Rr]emover del cargo de ([A-ZÁÉÍÓÚÑ][^:]{3,50}?) " + _A_SENOR + r":?\s*([^\.]+?)\.")),
    ("nc", re.compile(r"[Rr]emoci[óo]n " + _DE_SENOR + r":?\s*([A-ZÁÉÍÓÚÑ][^\.,]{5,60}?),?\s+(?:como|del cargo de) ([A-ZÁÉÍÓÚÑ][^\.,;]{3,50})")),
]
_RE_DIR_ENTRAN = [
    ("cn", re.compile(r"[Nn]ombrar como ([A-ZÁÉÍÓÚÑ][^:]{3,50}?) " + _A_SENOR + r":?\s*([^\.]+?)\.")),
    ("nc", re.compile(r"[Nn]ombramiento " + _DE_SENOR + r":?\s*([^\.]+?),?\s+(?:para ejercer (?:las funciones|el cargo) de|como(?: nuevo)?) ([A-ZÁÉÍÓÚÑ][^\.,;]{3,50})")),
    ("cn", re.compile(r"[Dd]esignar como ([A-ZÁÉÍÓÚÑ][^:]{3,50}?) " + _A_SENOR + r":?\s*([A-ZÁÉÍÓÚÑ][^\.\n]{5,60}?)\.")),
    ("nc", re.compile(r"[Dd]esignaci[óo]n " + _DE_SENOR + r":?\s*([^\.]+?)\s+como ([A-ZÁÉÍÓÚÑ][^\.,;]{3,50})")),
]
_RE_DIR_RATIF = [
    ("nc", re.compile(r"[Rr]atificaci[óo]n " + _DE_SENOR + r":?\s*([^\.]+?)\s+como ([A-ZÁÉÍÓÚÑ][^\.,;]{3,60})")),
    ("cn", re.compile(r"[Rr]atificar como ([A-ZÁÉÍÓÚÑ][^:]{3,50}?) " + _A_SENOR + r":?\s*([^\.]+?)\.")),
]
# Listas "Presidente - Nombre Vicepresidente - Nombre…" (estilo EMIPA): solo se
# aplica si el texto habla de cargos del Directorio (evita ruido).
_CARGOS_MESA = r"Presidenta?|Vicepresidenta?|Secretari[oa]|Vocal|Director|Síndico"
_RE_DIR_PARES = re.compile(
    r"(Presidenta?|Vicepresidenta?|Secretari[oa]|Vocal|Director(?:a)?(?: Titular| Suplente| Laboral)?|"
    r"Síndico(?: Titular| Suplente)?)\s*[-–:]\s*"
    # el nombre NO puede contener palabras-cargo: sin el lookahead, en la lista
    # "…Zenteno Sejas Vicepresidente - Paola…" el nombre se traga el cargo siguiente
    r"([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+(?!(?:" + _CARGOS_MESA + r")\b)[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+){1,4})")
_RE_DIR_SIGNAL = re.compile(
    r"Director(?:es)? (?:Titular|Suplente)|Síndico|Directorio quedó conformado|"
    r"composición del Directorio|cargos del Directorio|(?:Presidente|Vicepresidente) del Directorio", re.I)
_RE_DIR_VERBO = re.compile(r"remoci[óo]n|remover|nombra|ratific|design", re.I)

# Juntas convocadas (calendario) + agenda destacada.
_RE_JUNTA_CONV = re.compile(
    r"convocatoria a (?:la )?(?:Junta General|Asamblea General)\s+(Ordinaria|Extraordinaria)", re.I)
_RE_JUNTA_FECHA = re.compile(r"a (?:realizarse|celebrarse|llevarse a cabo) el (\d{1,2} de \w+ de \d{4})")
_AGENDA_KEYS = [
    ("distribución de resultados", re.compile(r"[Dd]istribuci[óo]n.{0,30}[Rr]esultados|[Dd]ividendos")),
    ("emisión de valores", re.compile(r"[Ee]misi[óo]n de (bonos|pagar|valores|acciones)", re.I)),
    ("aumento de capital", re.compile(r"aumento de capital", re.I)),
    ("estados financieros", re.compile(r"[Ee]stados [Ff]inancieros")),
    ("directorio", re.compile(r"[Ee]lecci[óo]n|[Dd]esignaci[óo]n de [Dd]irectores")),
]

# Firma auditora (fase 2a.1): el disparador es case-INSENSITIVE (scoped `(?i:…)`) —
# el texto real alterna "Auditoría Externa"/"auditoría externa" y la versión vieja,
# case-sensitive, perdía la mayúscula. Cubre "firma [de] [auditoría externa]",
# "firma auditora", "empresa [de auditoría externa]", "consultora", y el verbo-acto
# ("contratación/elección/designación de [la] [firma|empresa]") — el nombre puede
# seguir directo al verbo sin sustantivo intermedio ("contratación de BERTHIN… S.R.L.").
# La captura arranca en MAYÚSCULA (case-sensitive), tras una comilla opcional, y un
# lookahead negativo impide que arranque en una palabra-trigger (evita capturar
# "Firma de Auditoría Externa X" con el prefijo). Corta en el sufijo legal.
_RE_AUDITORA = re.compile(
    r"(?i:"
    r"firma(?:\s+auditora|\s+de\s+auditor[ií]a(?:\s+externa)?)?"
    r"|empresa(?:\s+de\s+auditor[ií]a(?:\s+externa)?)?"
    r"|consultora"
    r"|(?:elecci[óo]n|contrataci[óo]n|designaci[óo]n)\s+de(?:\s+la)?(?:\s+(?:firma|empresa|consultora))?"
    r")"
    r"\s+[“\"«'‘]?"
    r"(?!(?:Firma|Empresa|Consultora|Auditor[ií]a)\b)"
    r"([A-ZÁÉÍÓÚÑ][^,\n“”\"«»]{2,70}?"
    r"(?:S\.\s?R\.\s?L\.|S\.\s?A\.(?:\s?M\.)?|LTDA\.?|Ltda\.?))")
_RE_AUD_ACTO = re.compile(
    r"contrataci[óo]n|elecci[óo]n|designaci[óo]n|aprobar la firma|ratificar", re.I)
_RE_GESTION = re.compile(r"gesti[óo]n(?:es)? (\d{4}(?:\s*[-y]+\s*\d{4})?)")
# Fallback de gestión: el cierre fiscal "al 31 de diciembre de YYYY" = gestión
# auditada cuando el comunicado no dice "gestión YYYY" explícito. Solo 31-dic
# (cierre de ejercicio) para no capturar fechas sueltas (dictamen, reunión).
_RE_GESTION_FECHA = re.compile(r"al\s+31\s+de\s+diciembre\s+de\s+(\d{4})", re.I)

_RE_DESTINO = re.compile(
    r"[-–]?\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ /]{4,60}?):\s*(?:Bs|USD|\$us)", )
_RE_DESTINO2 = re.compile(r"como ([a-z][a-záéíóúñ ]{5,40}?)[\.,]")


def _monto_corto(raw: str, moneda: str = "Bs") -> str:
    """'25.000.000,00' → 'Bs 25,0 M' (formato boliviano: punto=miles, coma=decimal)."""
    try:
        v = float(raw.replace(".", "").replace(",", "."))
    except ValueError:
        return f"{moneda} {raw}"
    if v >= 1e6:
        return f"{moneda} " + f"{v/1e6:.1f}".replace(".", ",") + " M"
    if v >= 1e3:
        return f"{moneda} {v/1e3:.0f} mil"
    if v == int(v):
        return f"{moneda} {int(v)}"
    return f"{moneda} " + f"{v:.2f}".replace(".", ",")


def _num(raw: str) -> float:
    """Número en formato boliviano o anglo: '1,10'→1.10, '13.82'→13.82,
    '25.000,50'→25000.50."""
    s = raw.strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def _split_nombres(raw: str) -> list[str]:
    """'X Pérez, Y López y Z Díaz' → ['X Pérez', 'Y López', 'Z Díaz']."""
    limpio = re.sub(r"\s+", " ", raw).strip(" .;:")
    partes = re.split(r",\s*| y (?=[A-ZÁÉÍÓÚÑ])| e (?=[A-ZÁÉÍÓÚÑ])", limpio)
    out = []
    for p in partes:
        p = p.strip(" .;:")
        # nombre plausible: 2-5 palabras capitalizadas
        if p and 2 <= len(p.split()) <= 6 and p[0].isupper() and len(p) < 60:
            out.append(p)
    return out


# ── Regex de clasificación V3 (fase 2a) ─────────────────────────────────────
# Inscripción de valores vía Comité de Inscripciones / autorizar la inscripción
# en la Bolsa/RMV — señal inequívoca de emisión (no depende del tag `emision`).
_RE_INSCRIPCION = re.compile(
    r"[Cc]omit[ée] de Inscripci|[Aa]utoriz(?:ar|ó) la inscripci[óo]n|"
    r"inscri(?:bir|pci[óo]n).{0,40}(?:Bolsa Boliviana|Registro del Mercado|RMV)", re.I)
# Objeto de emisión: distingue una autorización/inscripción de valores de un acto
# administrativo cualquiera (cambio de denominación de un fondo, tasas, etc.).
_RE_EMISION_OBJ = re.compile(
    r"[Bb]onos|[Pp]agar[ée]s|[Vv]alores de [Tt]itularizaci[óo]n|[Pp]rograma de [Ee]misiones|"
    r"[Oo]ferta [Pp][úu]blica|emisi[óo]n de (?:bonos|pagar|valores|acciones|cuotas)", re.I)
_RE_AUTORIZA_INSCRIBE = re.compile(r"[Aa]utoriza|[Ii]nscrib", re.I)
# Acta de reunión/asamblea REALIZADA con decisiones (multi-tema): el frame
# "Junta/Asamblea/reunión de Directorio … determinó/aprobó/Orden del Día".
_RE_REUNION_ACTA = re.compile(
    r"(?:Junta General|Asamblea General|reuni[óo]n de Directorio|sesi[óo]n de Directorio|"
    r"Asamblea de Tenedores|Asamblea General de Tenedores)"
    r"[\s\S]{0,400}?(?:determin[óo]|resolvi[óo]|acord[óo]|Orden del D[íi]a|se aprob|"
    r"aprob[óo]|se procedi[óo])", re.I)
# Verbo claro de cambio de UNA persona (standalone; NO la infinitiva "Designar a",
# que es típica de agenda de junta multi-tema y se rutea por el frame de junta).
_RE_PERSONAL_VERBO = re.compile(
    r"asume el cargo|asumi[óo] el cargo|fue ascendid|culmin[óo][^.]{0,40}relaci[óo]n laboral|"
    r"acept[óo] la renuncia|present[óo] su renuncia|fue posesionad|se incorpora(?:r[áa])?|"
    r"design[óo] (?:a|al|como)|fue design|"
    # V3: variantes de fin de relación laboral (drift léxico 2025/2026).
    r"finaliz[óo] (?:la|su) (?:vinculaci[óo]n|relaci[óo]n) laboral|"
    r"conclu(?:y[óo]|si[óo]n)[^.]{0,30}(?:relaci[óo]n|vinculaci[óo]n) laboral|"
    r"dej[óo] de (?:ejercer|prestar|desempe[ñn]ar|pertenecer)|cese de (?:sus )?funciones", re.I)
# Préstamo/desembolso recibido, por verbo textual (el tag `prestamo` solo capta
# "desembolso"/"préstamo de dinero" y se pierde "obtuvo/suscribió un préstamo").
_RE_PRESTAMO_TXT = re.compile(
    r"obtuvo un pr[ée]stamo|suscrib\w+[^.]{0,60}(?:contrato de pr[ée]stamo|l[íi]nea de cr[ée]dito)|"
    # V3: "adquirió/adquirir (un) préstamo/línea de crédito/crédito" (redacción 2025+2026).
    r"adquiri[óo] (?:un[ao]? )?(?:pr[ée]stamo|l[íi]nea de cr[ée]dito|cr[ée]dito)|"
    r"adquirir (?:un[ao]? )?(?:pr[ée]stamo|l[íi]nea de cr[ée]dito)|"
    r"desembolso|pr[ée]stamo de dinero|otorg[óo][^.]{0,20}pr[ée]stamo", re.I)
# Compromiso financiero cuya TABLA de indicadores existe pero el aplanado pypdf la
# rompió (regex no extrajo pares): se marca para el re-parseo de tablas del P2.
_RE_TABLA_PRESENTE = re.compile(
    r"Indicadores?\s+Financieros|PAR[ÁA]METRO DE INDICADORES|COMPROMISO\s+CUMPLIMIENTO|"
    r"INDICADOR\s+COMPROMISO|Compromisos Financieros[\s\S]{0,80}(?:detalle|siguiente)", re.I)


def clasificar_grupo(item: dict, skip_directorio: bool = False) -> str:
    """Tablita destino. Prioridad = del hecho más específico/regulatorio al más
    genérico; el frame de junta/asamblea es el ÚLTIMO recurso (regla 13) para no
    sepultar el evento económico extraíble (monto, persona, instrumento) dentro
    de una fila de reunión sin campos. `skip_directorio` re-clasifica ignorando
    la rama directorio (lo usa enriquecer al degradar una directorio sin cambios).
    Detalle de calibración y falsos positivos: CUADERNO_HECHOS_RELEVANTES.md."""
    tags = set(item.get("tags", ()))
    seccion = item.get("seccion", "")
    cat = item.get("categoria", "")
    texto = item.get("texto", "")
    low = texto.lower()
    # 1. Emisiones: (a) inscripción vía Comité/Bolsa (inequívoca), o (b) acto FORMAL
    #    (Resolución/Carta) que autoriza/inscribe un objeto de emisión —con o sin
    #    tag `emision`. Exigir sección formal en (b) evita robar cupones/compromisos/
    #    convocatorias (viven en Hechos Relevantes/Noticias y también nombran bonos).
    formal = seccion in ("Resoluciones Administrativas", "Cartas de Autorización")
    if _RE_INSCRIPCION.search(texto):
        return "emisiones"
    if formal and _RE_AUTORIZA_INSCRIBE.search(texto) and (
            "emision" in tags or _RE_EMISION_OBJ.search(texto)):
        return "emisiones"
    if "cupon" in tags:
        return "cupones"
    if "compromisos" in tags:
        return "compromisos"          # se parte en enriquecer (reportados/anunciados)
    if "calificacion" in tags and "Calificadoras" in cat:
        return "calificaciones"
    # 5. Convocatorias con fecha futura → calendario de juntas (acá cae MADISA
    #    aunque su agenda hable de distribución de resultados: es agenda, no pago).
    if _RE_JUNTA_CONV.search(texto) and _RE_JUNTA_FECHA.search(texto):
        return "juntas"
    # 6. Cambios de composición de directorio/síndicos (tentativo: enriquecer() lo
    #    degrada si no extrae ningún cambio). VA ANTES de titularización para no
    #    perder cambios de directorio de titularizadoras.
    if not skip_directorio and _RE_DIR_SIGNAL.search(texto) and _RE_DIR_VERBO.search(texto):
        return "directorio"
    # 7. Titularización (NUEVO): desembolsos/convocatorias/reportes de patrimonios
    #    autónomos que no cayeron en cupones/compromisos/directorio.
    if "patrimonio autónomo" in low:
        return "titularizacion"
    # 8. Auditorías: designación/contratación de auditor externo, PERO no una
    #    asamblea que solo menciona la auditoría en su agenda (esas llevan tag
    #    `junta` y son actas multi-decisión → juntas). Las designaciones genuinas
    #    son actas de "reunión de Directorio" (sin tag `junta`) o notas standalone.
    if "auditoria" in tags and "junta" not in tags \
            and re.search(r"[Aa]uditor[íi]a [Ee]xterna|[Aa]uditor [Ee]xterno", texto) \
            and _RE_AUD_ACTO.search(texto):
        return "auditorias"
    # 9. Personal: cambio de UNA persona por tag o verbo standalone.
    if "personal" in tags or _RE_PERSONAL_VERBO.search(texto):
        return "personal"
    # 10. Préstamos/desembolsos recibidos (tag O verbo); patrimonios autónomos NO.
    if ("prestamo" in tags or _RE_PRESTAMO_TXT.search(texto)) and "patrimonio autónomo" not in low:
        return "prestamos"
    # 11. Dividendos pagados/distribuidos.
    if "dividendos" in tags and re.search(r"pago|pagar[áa]|cancelar[áa]|distribuci[óo]n", low):
        return "dividendos"
    # 12. Uso de recursos captados.
    if "uso_fondos" in tags:
        return "uso_fondos"
    # 13. Frame de junta/asamblea de accionistas (tag) o acta de reunión de
    #     Directorio realizada (multi-decisión) sin evento dominante ya ruteado —
    #     ÚLTIMO antes de otros.
    if "junta" in tags or _RE_REUNION_ACTA.search(texto):
        return "juntas"
    return "otros"


def _campos_directorio(texto: str) -> list[dict]:
    """[{persona, cargo, tipo}] con tipo ∈ sale|entra|ratificado."""
    cambios: list[dict] = []

    def agregar(nombres_raw: str, cargo: str, tipo: str):
        cargo = " ".join(cargo.split())
        # el cargo termina donde arranca otra cláusula ("· El nombramiento…",
        # "y el nombramiento…", "del Director X") — cortar en esos separadores
        cargo = re.split(r"\s+·\s+|\s+y (?:el|la|los|las)\s+|\s+del?\s+(?:la\s+)?(?:Director|señor)",
                         cargo)[0]
        cargo = cargo.rstrip(" .,;:")[:50]
        for p in _split_nombres(nombres_raw):
            cambios.append({"persona": p, "cargo": cargo, "tipo": tipo})

    for tipo, patrones in (("sale", _RE_DIR_SALEN), ("entra", _RE_DIR_ENTRAN),
                           ("ratificado", _RE_DIR_RATIF)):
        for orden, rx in patrones:
            for m in rx.finditer(texto):
                g = m.groups()
                nombres, cargo = (g[0], g[1]) if orden == "nc" else (g[1], g[0])
                agregar(nombres, cargo, tipo)
    # Listas "Presidente - Nombre …" (designaciones de mesa directiva)
    if re.search(r"cargos del Directorio|conformaci[óo]n del Directorio", texto, re.I):
        for m in _RE_DIR_PARES.finditer(texto):
            agregar(m.group(2), m.group(1), "entra")

    # dedupe conservando orden (una persona puede matchear 2 variantes)
    vistos = set()
    unicos = []
    for c in cambios[:24]:
        k = (c["persona"], c["tipo"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(c)
    return unicos


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

    elif grupo == "directorio":
        cambios = _campos_directorio(texto)
        if cambios:
            c["cambios"] = cambios

    elif grupo == "personal":
        m = _RE_PERSONA.search(texto)
        if m:
            c["persona"] = m.group(1)
        m = _RE_CARGOS_LISTA.search(texto) or _RE_CARGO.search(texto)
        if m:
            cargo = " ".join(m.group(1).split())
            cargo = re.sub(r"\s+a$", "", cargo)  # resto de "a.i." cortado por el punto
            c["cargo"] = (cargo[:87] + "…") if len(cargo) > 90 else cargo
        for nombre, rx in _MOVIMIENTOS:
            if rx.search(texto):
                c["movimiento"] = nombre
                break

    elif grupo == "dividendos":
        m = _RE_MONTO_DIV.search(texto)
        if m:
            moneda = m.group(1)
            moneda = "Bs" if moneda.lower().startswith("bs") else "USD"
            monto = _monto_corto(m.group(2), moneda)
            if m.group(3):
                monto += " por acción"
            c["monto"] = monto
        m = _RE_FECHA_LARGA.search(texto)
        if m:
            c["fecha_pago"] = m.group(1)

    elif grupo == "uso_fondos":
        m = _RE_INSTRUMENTO.search(texto)
        if m:
            c["instrumento"] = " ".join(m.group(1).split()).rstrip(" -–")
        m = _RE_DESTINO.search(texto)
        if m:
            c["destino"] = " ".join(m.group(1).split())[:60]
        else:
            m = _RE_DESTINO2.search(texto)
            if m:
                c["destino"] = m.group(1).strip()[:60]
        m = _RE_MONTO_BS.search(texto)
        if m:
            c["monto"] = _monto_corto(m.group(1))

    elif grupo == "compromisos":
        indicadores = []

        def agregar_ind(sigla, op, umbral_raw, valor_raw, pct):
            try:
                umbral, valor = _num(umbral_raw), _num(valor_raw)
            except ValueError:
                return
            cumple = valor >= umbral if op == ">=" else valor <= umbral
            fmt = (lambda x: (f"{x:.2f}".rstrip("0").rstrip(".")) + ("%" if pct else ""))
            indicadores.append({"sigla": sigla, "op": op, "req": fmt(umbral),
                                "valor": fmt(valor), "ok": bool(cumple)})

        for m in _RE_INDICADOR.finditer(texto):
            sigla, op, u, v = m.groups()
            op = {"=>": ">=", "=<": "<="}.get(op, op)
            agregar_ind(sigla, op, u, v, "%" in texto[m.start():m.end()])
        for m in _RE_INDICADOR_VERBAL.finditer(texto):
            nombre, sentido, u, v = m.groups()
            sigla = next((s for frag, s in _SIGLAS_VERBAL if frag in nombre),
                         nombre.split(" de ")[-1][:18])
            agregar_ind(sigla, ">=" if sentido == "mayor" else "<=", u, v, True)
        if indicadores:
            c["indicadores"] = indicadores[:10]

    elif grupo == "auditorias":
        m = _RE_AUDITORA.search(texto)
        if m:
            c["firma"] = " ".join(m.group(1).split())
        # gestión explícita ("gestión YYYY") primero; si no, cierre fiscal.
        m = _RE_GESTION.search(texto) or _RE_GESTION_FECHA.search(texto)
        if m:
            c["gestion"] = m.group(1)

    elif grupo == "juntas":
        m = _RE_JUNTA_CONV.search(texto)
        if m:
            c["tipo"] = m.group(1).capitalize()
        m = _RE_JUNTA_FECHA.search(texto)
        if m:
            c["fecha_junta"] = m.group(1)
        temas = [nombre for nombre, rx in _AGENDA_KEYS if rx.search(texto)][:2]
        if temas:
            c["agenda"] = " · ".join(temas)

    # 'calificaciones' y 'otros': sin campos tabulares (tablas de ratings son
    # demasiado irregulares para regex confiable — entidad + resumen alcanzan).
    return c


def enriquecer(item: dict) -> dict:
    """Agrega/recomputa grupo + campos + grupo_v + revisado in-place
    (idempotente). NO toca resumen/resumen_origen — eso es territorio de
    resumen.py.

    Degradaciones extraction-driven (la señal textual sola mete falso positivo):
      - 'directorio' sin cambios extraídos → se RE-CLASIFICA ignorando la rama
        directorio (así una reunión de directorio sin cambio de composición cae
        en juntas/personal/otros, no se pierde en 'otros').
      - 'personal' de una asamblea de accionistas (tag `junta`) SIN persona
        extraíble = fila inútil → degrada a 'juntas' (tipo/agenda dan más
        contexto). Los standalone (sin tag `junta`) se quedan.
    'auditorias' YA NO degrada por falta de `firma`: la rama de clasificación
    exige señal fuerte de auditoría, así que se conserva aunque la firma no
    extraiga (V3, fase 2a).

    Split de compromisos: la clasificación devuelve 'compromisos' (paraguas) y
    acá se parte según haya indicadores parseados → 'compromisos_reportados' vs
    'compromisos_anunciados' (estos últimos con tabla rota por pypdf quedan
    marcados `tabla_no_parseada` para el re-parseo de tablas del P2)."""
    grupo = clasificar_grupo(item)
    item["grupo"] = grupo
    campos = extraer_campos(item)
    if grupo == "directorio" and not campos.get("cambios"):
        grupo = clasificar_grupo(item, skip_directorio=True)
        item["grupo"] = grupo
        campos = extraer_campos(item)
    if grupo == "personal" and "junta" in set(item.get("tags", ())) \
            and not campos.get("persona"):
        item["grupo"] = grupo = "juntas"
        campos = extraer_campos(item)
    if grupo == "compromisos":
        if campos.get("indicadores"):
            item["grupo"] = "compromisos_reportados"
        else:
            item["grupo"] = "compromisos_anunciados"
            if _RE_TABLA_PRESENTE.search(item.get("texto", "")):
                campos["tabla_no_parseada"] = True
    # Metadatos de taxonomía. `grupo_v` se re-estampa siempre; `revisado` respeta
    # una curación humana previa ('revisado') y default a 'provisional'.
    item["grupo_v"] = TAXONOMIA_V
    item.setdefault("revisado", "provisional")
    if campos:
        item["campos"] = campos
    else:
        item.pop("campos", None)
    return taxonomy_v4.enrich(item)
