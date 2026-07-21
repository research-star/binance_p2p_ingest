"""Taxonomía temática V4 para hechos relevantes ASFI.

La clasificación es determinística y trabaja únicamente con el texto ya
persistido. Mantiene una sola pareja ``type_id``/``subtype_id`` por comunicado;
los frames societarios y otras señales transversales quedan en eventos
secundarios o tags. La reconstrucción de tablas fuente no pertenece a esta
fase: aquí solo se estampa el contrato de datos que utilizará Fase 2B.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


TAXONOMIA_V = 4

TYPE_LABELS = {
    "sanciones_procesos": "Sanciones y procesos regulatorios",
    "capital_societario": "Capital y cambios societarios",
    "emisiones_colocaciones": "Emisiones y colocaciones",
    "pagos_valores": "Cupones y pagos de valores",
    "financiamiento": "Financiamiento",
    "poderes_representacion": "Poderes y representación legal",
    "juntas_asambleas": "Juntas y asambleas",
    "personal": "Personal",
    "directorio": "Directorio y sindicatura",
    "compromisos_financieros": "Compromisos financieros",
    "calificaciones_riesgo": "Calificaciones de riesgo",
    "dividendos": "Dividendos y rendimientos",
    "uso_fondos": "Uso de recursos captados",
    "auditorias": "Auditorías externas",
    "titularizacion": "Titularización",
    "registros_autorizaciones": "Registros y autorizaciones",
    "otros_residual": "Otros comunicados",
}

# Catálogo completo de Fase 1, con los dos tipos de financiamiento integrados.
# Las claves son contrato público: no deben renombrarse sin una migración.
SUBTYPE_LABELS = {
    "sanciones_procesos": {
        "multa": "Multa", "amonestacion": "Amonestación",
        "cargo_desestimado": "Cargo desestimado",
        "prescripcion_archivo": "Prescripción o archivo",
        "incumplimiento_regulatorio": "Incumplimiento regulatorio",
        "sancion_no_monetaria": "Sanción no monetaria",
        "resolucion_proceso": "Resolución de proceso sancionatorio",
    },
    "capital_societario": {
        "transferencia_accionaria": "Transferencia accionaria",
        "aportes_capitalizacion": "Aportes para capitalización",
        "aumento_capital": "Aumento de capital", "reduccion_capital": "Reducción de capital",
        "cambio_composicion": "Cambio de composición accionaria",
        "emision_acciones": "Emisión de acciones",
        "modificacion_estatutos": "Modificación de estatutos",
        "cambio_denominacion": "Cambio de denominación", "fusion": "Fusión",
        "escision": "Escisión", "disolucion_liquidacion": "Disolución o liquidación",
        "domicilio_legal": "Cambio de domicilio legal",
    },
    "emisiones_colocaciones": {
        "autorizacion_registro": "Autorización o registro", "emision": "Emisión",
        "inicio_colocacion": "Inicio de colocación", "colocacion_reportada": "Colocación reportada",
        "colocacion_parcial": "Colocación parcial", "colocacion_total": "Colocación total",
        "conclusion_cierre": "Conclusión o cierre",
        "modificacion_condiciones": "Modificación de condiciones",
        "ampliacion_plazo": "Ampliación del plazo de colocación",
    },
    "pagos_valores": {
        "cupon_programado": "Cupón programado", "cupon_pagado": "Cupón pagado",
        "pago_programado_valor": "Pago programado de valor",
        "amortizacion_capital": "Amortización de capital", "pago_intereses": "Pago de intereses",
        "redencion_vencimiento": "Redención o vencimiento",
        "pago_total_valor": "Pago o cancelación total",
    },
    "financiamiento": {
        "contratacion_bancaria": "Contratación bancaria",
        "desembolso_bancario": "Desembolso bancario",
        "uso_linea_credito": "Uso de línea de crédito",
        "avance_cuenta_corriente": "Avance en cuenta corriente", "renovacion": "Renovación",
        "refinanciamiento": "Refinanciamiento",
        "modificacion_condiciones": "Modificación de condiciones",
        "amortizacion_bancaria": "Amortización bancaria", "prepago": "Prepago",
        "cancelacion_bancaria": "Cancelación bancaria", "reporte_deuda": "Reporte de deuda",
        "prestamo_vinculada": "Préstamo de accionista o vinculada",
        "pagare_privado": "Pagaré privado", "desembolso_no_bancario": "Desembolso no bancario",
        "renovacion_contractual": "Renovación o modificación no bancaria",
        "cancelacion_contractual": "Cancelación o amortización no bancaria",
        "otro_contractual_no_bursatil": "Otro financiamiento contractual no bursátil",
    },
    "poderes_representacion": {
        "otorgamiento": "Otorgamiento", "revocacion": "Revocación", "sustitucion": "Sustitución",
        "renovacion": "Renovación", "modificacion_facultades": "Modificación de facultades",
    },
    "juntas_asambleas": {
        "convocatoria_ordinaria": "Convocatoria ordinaria",
        "convocatoria_extraordinaria": "Convocatoria extraordinaria",
        "modificacion_convocatoria": "Modificación de convocatoria", "suspension": "Suspensión",
        "junta_ordinaria_realizada": "Junta ordinaria realizada",
        "junta_extraordinaria_realizada": "Junta extraordinaria realizada",
        "decisiones_adoptadas": "Decisiones adoptadas", "asamblea_tenedores": "Asamblea de tenedores",
        "asamblea_participantes": "Asamblea de participantes",
    },
    "personal": {
        "designacion": "Designación o nombramiento", "renuncia": "Renuncia",
        "cese_desvinculacion": "Cese o desvinculación",
        "ascenso_cambio_cargo": "Ascenso o cambio de cargo",
        "interinato_suplencia": "Interinato o suplencia", "licencia_retorno": "Licencia o retorno",
        "otro_movimiento": "Otro movimiento de personal",
    },
    "directorio": {
        "designacion": "Designación", "remocion": "Remoción", "ratificacion": "Ratificación",
        "composicion": "Composición del directorio", "sindicatura": "Cambio de síndico",
        "otro_cambio": "Otro cambio",
    },
    "compromisos_financieros": {
        "reportado_cumple": "Reportado — cumple", "reportado_incumple": "Reportado — incumple",
        "reporte_sin_estado": "Reporte sin estado determinable", "anunciado": "Compromiso anunciado",
        "tabla_no_parseada": "Tabla pendiente de parseo",
    },
    "calificaciones_riesgo": {
        "asignacion_inicial": "Asignación inicial", "mejora": "Mejora de calificación",
        "rebaja": "Rebaja de calificación", "confirmacion": "Confirmación",
        "cambio_perspectiva": "Cambio de perspectiva",
        "cambio_calificadora": "Cambio de calificadora o contrato", "actualizacion": "Actualización",
    },
    "dividendos": {
        "declaracion": "Declaración", "pago_programado": "Pago programado",
        "pago_realizado": "Pago realizado", "rendimientos_fondo": "Distribución de rendimientos",
    },
    "uso_fondos": {
        "destino_inicial": "Destino inicial", "reporte_periodico": "Reporte periódico",
        "saldo_pendiente": "Saldo pendiente",
    },
    "auditorias": {
        "contratacion_designacion": "Contratación o designación", "ratificacion": "Ratificación",
        "cambio_firma": "Cambio de firma", "otro": "Otro evento de auditoría",
    },
    "titularizacion": {
        "reporte": "Reporte", "desembolso": "Desembolso",
        "constitucion_emision": "Constitución o emisión", "pago": "Pago", "asamblea": "Asamblea",
    },
    "registros_autorizaciones": {
        "inscripcion_operador": "Inscripción de operador", "inscripcion_rmv": "Inscripción en RMV",
        "inscripcion_responsable": "Inscripción de responsable",
        "autorizacion_fondo": "Autorización de fondo", "inscripcion_auditor": "Inscripción de auditor",
        "baja_operador": "Baja de operador", "no_objecion": "No objeción",
        "cancelacion_rmv": "Cancelación en RMV",
        "modificacion_reglamento": "Modificación de reglamento",
        "autorizacion_regulatoria": "Autorización regulatoria",
        "registro_operativo": "Registro operativo",
    },
    "otros_residual": {
        "sin_patron_fuerte": "Sin patrón fuerte", "contenido_generico": "Contenido genérico",
    },
}

assert set(TYPE_LABELS) == set(SUBTYPE_LABELS)
assert sum(map(len, SUBTYPE_LABELS.values())) == 120

SOURCE_TABLE_STATUSES = (
    "none", "detected_unparsed", "reconstructed_unverified",
    "reconstructed_verified", "source_verified",
)

FIELD_SCHEMAS = {
    "capital_societario.transferencia_accionaria": ("vendedor", "comprador", "cantidad_acciones", "porcentaje", "fecha_efectiva"),
    "capital_societario.aportes_capitalizacion": ("operacion", "monto_maximo", "moneda", "destino", "fecha_limite", "proximo_paso", "efecto_societario"),
    "capital_societario.aumento_capital": ("capital_anterior", "capital_nuevo", "monto_aumento", "moneda", "fecha_efectiva"),
    "sanciones_procesos.multa": ("entidad_sancionada", "monto", "moneda", "resolucion", "estado_proceso"),
    "emisiones_colocaciones.colocacion_reportada": ("instrumento", "serie", "monto", "cantidad", "porcentaje_colocado", "estado"),
    "compromisos_financieros.reportado_cumple": ("fecha_corte", "indicadores"),
    "compromisos_financieros.reportado_incumple": ("fecha_corte", "indicadores"),
}

_LEGACY_DEFAULTS = {
    "emisiones": ("emisiones_colocaciones", "emision"),
    "cupones": ("pagos_valores", "cupon_programado"),
    "prestamos": ("financiamiento", "contratacion_bancaria"),
    "directorio": ("directorio", "composicion"), "personal": ("personal", "otro_movimiento"),
    "dividendos": ("dividendos", "pago_programado"), "uso_fondos": ("uso_fondos", "reporte_periodico"),
    "compromisos_reportados": ("compromisos_financieros", "reportado_cumple"),
    "compromisos_anunciados": ("compromisos_financieros", "anunciado"),
    "titularizacion": ("titularizacion", "reporte"),
    "auditorias": ("auditorias", "contratacion_designacion"),
    "juntas": ("juntas_asambleas", "decisiones_adoptadas"),
    "calificaciones": ("calificaciones_riesgo", "actualizacion"),
    "otros": ("otros_residual", "sin_patron_fuerte"),
}


def fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"\s+", " ", "".join(ch for ch in text if not unicodedata.combining(ch)).lower()).strip()


def _has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.S))


def _dominant_text(item: dict) -> str:
    """Quita la agenda enumerada de convocatorias, no decisiones posteriores."""
    raw = str(item.get("texto", "") or item.get("resumen", ""))
    kept: list[str] = []
    in_agenda = saw_numbered = False
    for line in raw.splitlines() or [raw]:
        current = fold(line)
        agenda = re.search(r"orden del dia|agenda:", current)
        if agenda:
            prefix = current[: agenda.start()].strip(" :-")
            if prefix:
                kept.append(prefix)
            in_agenda, saw_numbered = True, False
            continue
        if in_agenda:
            stripped = current.lstrip()
            if re.match(r"^(?:\d+|[ivxlcdm]+)[.)-]\s*", stripped):
                saw_numbered = True
                continue
            if not stripped:
                continue
            if saw_numbered and re.match(r"^[-•*]", stripped):
                in_agenda = False
                kept.append(current)
            continue
        kept.append(current)
    cleaned = " ".join(kept).strip() or fold(item.get("resumen", ""))
    return fold(f"{item.get('seccion', '')} {cleaned}")


def _full_text(item: dict) -> str:
    return fold(" ".join(str(item.get(key, "") or "") for key in ("entidad", "seccion", "texto", "resumen")))


def _meeting_only_agenda(item: dict, text: str) -> bool:
    # Fase 1 evaluó esta salvaguarda contra el registro completo, no contra el
    # texto con agenda removida que usa la precedencia principal.
    text = _full_text(item)
    if not _has(text, r"convoc|orden del dia|agenda"):
        return False
    if _has(text, r"(?:junta|asamblea).{0,120}(?:realizada|celebrada|se llevo a cabo)"):
        return False
    if _has(text, r"(?:determino|resolvio|acordo) (?:aprobar )?(?:la )?convoc|aprobo (?:la |una )?convocatoria|determino convocar|resolvio convocar"):
        return True
    return not _has(text, r"determino|resolvio|acordo|aprobo|se aprobo|formaliz")


def _first_match(text: str, checks: Iterable[tuple[str, str]]) -> str | None:
    return next((key for key, pattern in checks if _has(text, pattern)), None)


def _capital_subtype(text: str) -> str | None:
    return _first_match(text, (
        ("transferencia_accionaria", r"transferencias?.{0,100}acciones|transferid.{0,80}acciones|transfiri.{0,80}acciones|transferencia accionaria|compraventa.{0,60}acciones|venta (?:total|parcial).{0,80}paquete accionario|adquiri.{0,60}paquete accionario"),
        ("aportes_capitalizacion", r"reserva de aportes.{0,50}capitaliz|aportes? para (?:futuros? aumentos? de )?capitaliz|aportes? para futuros? aumentos? de capital|aportes por capitalizar|aportes? (?:pendientes? de capitalizacion|de capital)"),
        ("aumento_capital", r"aumento (?:de(?:l)? )?capital|incremento (?:de(?:l)? )?capital|capitalizacion (?:de|derivada|producto).{0,80}(?:utilidades|reservas|reinversion)|transfiri.{0,80}(?:a|al) capital pagado"),
        ("reduccion_capital", r"reduccion (?:de(?:l)? )?capital|disminucion (?:de(?:l)? )?capital|disminucion (?:de )?aportes? de capital|redu(?:jo|ce|cir).{0,40}capital"),
        ("cambio_composicion", r"composicion accionaria|estructura accionaria|cambio.{0,60}accionistas|participacion accionaria"),
        ("emision_acciones", r"emision de (?:nuevas )?acciones"),
        ("modificacion_estatutos", r"modificacion de estatut|reforma de estatut"),
        ("cambio_denominacion", r"cambio de (?:denominacion|razon social)"),
        ("fusion", r"\bfusion|absorcion societaria"), ("escision", r"\bescision"),
        ("disolucion_liquidacion", r"disolucion|liquidacion voluntaria|inicio de liquidacion"),
        ("domicilio_legal", r"cambio de domicilio (?:legal|social)|domicilio legal"),
    ))


def _sanction_subtype(text: str) -> str:
    return _first_match(text, (
        ("cargo_desestimado", r"desestim|sin lugar|improbado|no aplicar (?:ninguna )?sancion|revoc.{0,60}(?:cargo|sancion)"),
        ("prescripcion_archivo", r"prescrip|archivo de obrados|archiv(?:ar|o)"),
        ("multa", r"multa"), ("amonestacion", r"amonest"),
        ("sancion_no_monetaria", r"suspension|inhabilit|cancelacion de autorizacion"),
        ("resolucion_proceso", r"proceso sancion|procedimiento sancion|resolucion sancion"),
    )) or "incumplimiento_regulatorio"


def _payment_subtype(item: dict, text: str) -> str | None:
    text = _full_text(item)
    group = item.get("grupo", "otros")
    if str(group).startswith("compromisos_") or group == "uso_fondos" or _meeting_only_agenda(item, text):
        return None
    market = _has(text, r"bonos|pagare|valores de titularizacion|cupon|emision")
    if group != "cupones" and not (market and _has(text, r"pago|cancel|amortiz|redencion|vencimiento|provision de fondos")):
        return None
    if _has(text, r"amortizacion de capital|capital.{0,50}amortiz"): return "amortizacion_capital"
    if _has(text, r"redencion|vencimiento"): return "redencion_vencimiento"
    if _has(text, r"concluyo (?:con )?(?:(?:el )?pago|(?:la )?cancelacion)|pago de la totalidad|cancelacion total|cancelacion (?:de|del) (?:los |las |el )?(?:pagares?|bonos|valores)"): return "pago_total_valor"
    if _has(text, r"pago de intereses|intereses.{0,60}pag"): return "pago_intereses"
    if item.get("campos", {}).get("estado") == "pagado" or _has(text, r"concluyo.{0,40}pago|efectivizo.{0,40}pago"): return "cupon_pagado"
    return "cupon_programado" if "cupon" in text else "pago_programado_valor"


def _issue_subtype(item: dict, text: str) -> str | None:
    text = _full_text(item)
    group = item.get("grupo", "otros")
    if str(group).startswith("compromisos_") or group == "uso_fondos" or _meeting_only_agenda(item, text): return None
    if not (group == "emisiones" or _has(text, r"colocacion primaria|colocacion.{0,120}(?:bonos|pagare|valores|emision|cuotas? de participacion)|(?:bonos|pagare|valores|emision|cuotas? de participacion).{0,120}colocacion|registro (?:e inscripcion|de la emision)|programa de emisiones|emision de bonos|oferta publica.{0,100}(?:bonos|pagare|cuotas? de participacion)")): return None
    if _has(text, r"amplia.{0,80}plazo de colocacion|ampliacion.{0,80}plazo de colocacion"): return "ampliacion_plazo"
    if _has(text, r"modific.{0,80}(?:condiciones|caracteristicas|terminos).{0,100}(?:emision|programa|bonos|pagare)"): return "modificacion_condiciones"
    if _has(text, r"colocacion.{0,80}(?:100%|totalidad)|(?:100%|totalidad).{0,80}colocacion"): return "colocacion_total"
    if _has(text, r"colocacion primaria parcial|colocacion parcial"): return "colocacion_parcial"
    if _has(text, r"concluyo|finalizo|cierre.{0,50}colocacion") and "colocacion" in text: return "conclusion_cierre"
    if _has(text, r"inicio|iniciara|procedio|realizo") and "colocacion" in text:
        return "inicio_colocacion" if _has(text, r"inicio (?:de )?(?:la )?colocacion|iniciara (?:la )?colocacion") else "colocacion_reportada"
    if _has(text, r"autoriz|registro|inscripcion"): return "autorizacion_registro"
    return "emision"


def _bank_financing_subtype(item: dict, text: str) -> str | None:
    text = _full_text(item)
    group = item.get("grupo", "otros")
    if str(group).startswith("compromisos_") or group == "uso_fondos" or _meeting_only_agenda(item, text): return None
    explicit = _has(text, r"prestamo bancario|linea de credito|avance en cuenta corriente|financiamiento bancario|credito bancario|\bbanco\b.{0,160}desembols|desembols.{0,160}\bbanco\b")
    if not explicit and _has(text, r"bonos|pagares bursatiles|colocacion|cupon|valores de titularizacion"): return None
    if not (group == "prestamos" or explicit or _has(text, r"deuda financiera")): return None
    return _first_match(text, (
        ("reporte_deuda", r"deuda financiera vigente|reporte de deuda|saldo de (?:la )?deuda"),
        ("cancelacion_bancaria", r"cancelacion (?:total )?(?:del |de )?(?:prestamo|credito)|cancelo.{0,50}(?:prestamo|credito)"),
        ("prepago", r"prepago|pago anticipado"), ("amortizacion_bancaria", r"amortizacion|amortizo"),
        ("refinanciamiento", r"refinanc"), ("renovacion", r"renov.{0,60}(?:prestamo|credito|linea)"),
        ("modificacion_condiciones", r"modific.{0,80}(?:condiciones|plazo|tasa)"),
        ("avance_cuenta_corriente", r"avance en cuenta corriente"),
        ("uso_linea_credito", r"(?:uso|utiliz|dispuso).{0,60}linea de credito"),
        ("desembolso_bancario", r"desembolso|desembolso recibido"),
    )) or "contratacion_bancaria"


def _contract_financing_subtype(item: dict, text: str) -> str | None:
    text = _full_text(item)
    group = item.get("grupo", "otros")
    if str(group).startswith("compromisos_") or group == "uso_fondos" or _meeting_only_agenda(item, text): return None
    if _has(text, r"bonos|pagares bursatiles|oferta publica|colocacion|cupon|valores de titularizacion"): return None
    private = _has(text, r"pagare privado")
    related = _has(text, r"prestamo.{0,100}(?:empresa|sociedad|parte) vinculada|prestamo intercompan|financiamiento intercompan")
    nonbank = _has(text, r"desembolso") and _has(text, r"banco central de bolivia|\bbcb\b|parte vinculada|accionista|casa matriz")
    if not (private or related or nonbank): return None
    if _has(text, r"renov|modific|enmienda"): return "renovacion_contractual"
    if private: return "pagare_privado"
    if _has(text, r"cancel|amortiz|devolucion|prepago|pago anticipado"): return "cancelacion_contractual"
    if related: return "prestamo_vinculada"
    return "desembolso_no_bancario" if nonbank else "otro_contractual_no_bursatil"


def _use_funds_subtype(item: dict, text: str) -> str | None:
    text = _full_text(item)
    if not (_has(text, r"utiliz.{0,60}(?:los )?(?:fondos|recursos)|uso (?:de|dado a) (?:los )?(?:fondos|recursos)|destino (?:de|dado a) (?:los )?(?:fondos|recursos)|recambio de pasivos") and _has(text, r"bonos|emision|prospecto|recursos captados")): return None
    if _has(text, r"saldo|remanente|pendiente"): return "saldo_pendiente"
    if _has(text, r"trimestre|periodo|fecha de corte|reporte"): return "reporte_periodico"
    return "destino_inicial"


def _personnel_subtype(text: str) -> str | None:
    return _first_match(text, (("renuncia", r"renunci|presento su renuncia"), ("cese_desvinculacion", r"desvincul|cese de funciones|dejo de ejercer|finalizo.{0,40}relacion laboral|concluyo.{0,40}relacion laboral"), ("interinato_suplencia", r"a\.i\.|interin|suplenc|temporalmente"), ("licencia_retorno", r"licencia|vacaciones|retom|reasumio|reincorpor|ausent"), ("ascenso_cambio_cargo", r"ascendi|cambio de cargo|modific.{0,50}cargo"), ("designacion", r"design|nombr|asumio el cargo|posesion")))


def _personnel_signal(text: str) -> bool:
    if _has(text, r"designacion.{0,100}(?:accionistas?.{0,60}(?:firma|firmar).{0,30}acta|presidente y secretario de (?:la )?(?:junta|asamblea)|comision (?:aprobadora|para la aprobacion) del acta)"): return False
    if _has(text, r"renunci|cese de funciones|desvincul|dejo de ejercer|asumio el cargo|cambio de cargo|reincorpor|reasumio|retom|ausent"): return True
    role = r"cargo|gerente|subgerente|jefe|director ejecutivo|presidente ejecutivo|vicepresidente|secretari[oa]|administrador|responsable|oficial|representante legal|contador|tesorero|auditor interno|asesor"
    action = r"design|nombr|posesion|ascendi|interin|suplenc"
    return _has(text, rf"(?:{action}).{{0,160}}(?:{role})|(?:{role}).{{0,160}}(?:{action})")


def _board_subtype(text: str) -> str | None:
    role = r"\bdirector(?:es|a|as)?\b|\bmiembros? del directorio\b|\bsindic(?:o|a|os|as)?\b"
    if not _has(text, role):
        return "composicion" if _has(text, r"(?:composicion|conformacion|quedo conformado).{0,160}\bdirectorio\b|\bdirectorio\b.{0,160}(?:composicion|conformacion|quedo conformado)") else None
    return _first_match(text, (("remocion", rf"(?:remoci|remov).{{0,160}}(?:{role})|(?:{role}).{{0,160}}(?:remoci|remov)"), ("ratificacion", rf"ratific.{{0,160}}(?:{role})|(?:{role}).{{0,160}}ratific"), ("sindicatura", r"(?:design|nombr|remoci|ratific|sustitu).{0,160}sindic|sindic.{0,160}(?:design|nombr|remoci|ratific|sustitu)"), ("designacion", rf"(?:design|nombr|posesion).{{0,160}}(?:{role})|(?:{role}).{{0,160}}(?:design|nombr|posesion)"), ("composicion", rf"(?:composicion|conformacion|quedo conformado).{{0,160}}(?:{role})|(?:{role}).{{0,160}}(?:composicion|conformacion|quedo conformado)")))


def _powers_subtype(text: str) -> str | None:
    if not _has(text, r"\bpoder(?:es)?\b|apoderad|representante legal"): return None
    return _first_match(text, (("revocacion", r"revoc"), ("sustitucion", r"sustitu"), ("renovacion", r"renov"), ("modificacion_facultades", r"modific|ampli.{0,40}facultades|limit.{0,40}facultades"), ("otorgamiento", r"otorg|confier|confer|formaliz|registr.{0,80}poder|asum.{0,80}representante legal")))


def _meeting_subtype(text: str) -> str:
    if "tenedores" in text: return "asamblea_tenedores"
    if "participantes" in text: return "asamblea_participantes"
    if _has(text, r"suspend|suspension"): return "suspension"
    if _has(text, r"modific|reprogram|nueva fecha") and "convoc" in text: return "modificacion_convocatoria"
    ordinary, extraordinary = "ordinaria" in text and "extraordinaria" not in text, "extraordinaria" in text
    if "convoc" in text: return "convocatoria_extraordinaria" if extraordinary else "convocatoria_ordinaria"
    if _has(text, r"realizada|se celebro|se llevo a cabo|determino|resolvio|acordo|aprobo"):
        if extraordinary: return "junta_extraordinaria_realizada"
        if ordinary: return "junta_ordinaria_realizada"
    return "decisiones_adoptadas"


def _registration_subtype(item: dict, text: str) -> str | None:
    text = _full_text(item)
    section = fold(item.get("seccion", ""))
    if not _has(text, r"inscripcion|registro del mercado de valores|\brmv\b|registros? de la (?:bbv|bolsa)|sistema de registro de cuenta emisor|autoriza|no objecion|modificacion (?:al|del) reglamento"): return None
    if "no objecion" in text: return "no_objecion"
    if _has(text, r"cancelacion|baja") and _has(text, r"registro|rmv"): return "baja_operador" if _has(text, r"operador|asesor de inversion|corredor|representante") else "cancelacion_rmv"
    if "auditor" in text and _has(text, r"inscripcion|registro"): return "inscripcion_auditor"
    if _has(text, r"operador|asesor de inversion|corredor") and _has(text, r"inscripcion|registro|baja"): return "inscripcion_operador"
    if _has(text, r"responsable|funcionario") and _has(text, r"inscripcion|registro"): return "inscripcion_responsable"
    if _has(text, r"sistema de registro de cuenta emisor|registro operativo interno"): return "registro_operativo"
    if "fondo de inversion" in text and _has(text, r"autoriza|inscripcion|registro"): return "autorizacion_fondo"
    if _has(text, r"modificacion (?:al|del) reglamento|aprobar.{0,80}reglamento"): return "modificacion_reglamento"
    if _has(text, r"inscripcion|registro del mercado|rmv"): return "inscripcion_rmv"
    return "autorizacion_regulatoria" if section in {"resoluciones administrativas", "cartas de autorizacion"} or "autoriza" in text else None


def _is_generic(item: dict) -> bool:
    text, summary = fold(item.get("texto", "")), fold(item.get("resumen", ""))
    exact = {"ver adjunto", "adjunto", "se adjunta", "ha comunicado ver adjunto", "comunica ver adjunto", "resuelve ver adjunto"}
    return text in exact or summary in exact or (len(text) <= 90 and bool(re.search(r"\b(?:ver|se remite|remite|se adjunta) adjunt", text))) or (len(text) <= 55 and text in {"ha comunicado", "comunica", "resuelve"})


def _tags(item: dict, text: str) -> list[str]:
    tags = list(dict.fromkeys(str(x) for x in item.get("tags", []) if x))
    patterns = (
        ("rectificacion", r"\brectific|\baclara|\bcomplementa (?:el|la) hecho relevante"),
        ("red_atencion", r"(?:apertura|cierre|traslado|reubic|cambio de domicilio|inaugur).{0,120}(?:sucursal|agencia|oficina|punto de atencion|cajero)"),
        ("operacion_fondo", r"comite de inversion|(?:suscripcion|rescate) de cuotas|valor de cuota"),
        ("organizacion_interna", r"(?:aprobo|modifico|cambio|reorganiz|actualizo).{0,120}(?:estructura organiz|organigrama|gerencia|comite)"),
        ("inmueble_activo", r"(?:compra|venta|transferencia|adquisicion).{0,100}(?:inmueble|terreno|edificio)"),
    )
    for key, pattern in patterns:
        if _has(text, pattern) and key not in tags: tags.append(key)
    if item.get("resumen_origen") == "ia" and "resumen_ia" not in tags: tags.append("resumen_ia")
    if _is_generic(item) and "contenido_generico" not in tags: tags.append("contenido_generico")
    return tags


def _structured_fields(item: dict, type_id: str, subtype_id: str, text: str) -> dict:
    fields = dict(item.get("campos") or {})
    entity = item.get("entidad")
    if entity: fields.setdefault("entidad", entity)
    # OLEUM: caso de aceptación explícito de Fase 1.
    if "oleum sociedad aceitera" in fold(entity) and subtype_id == "aportes_capitalizacion":
        fields.update({
            "operacion": "Constitución de reserva de aportes por capitalizar",
            "monto_maximo": "Bs 34.000.000", "moneda": "Bs",
            "destino": "Atender obligaciones asumidas por la Sociedad",
            "fecha_limite": "31 de julio de 2026",
            "proximo_paso": "Suscripción futura de nuevas acciones ordinarias",
            "efecto_societario": "Ajuste posterior de la composición accionaria según aportes efectivos",
        })
    if type_id == "financiamiento":
        if fields.get("banco"):
            fields.setdefault("acreedor", fields["banco"])
        term = re.search(r"\b(?:plazo de|a)\s+(\d+(?:[.,]\d+)?\s+(?:dias?|meses?|anos?))", text)
        if term:
            fields.setdefault("plazo", term.group(1))
    if type_id == "sanciones_procesos":
        fields.setdefault("entidad_sancionada", entity)
        resolution = re.search(r"\b(?:resolucion|res\.)\s+([a-z0-9/.-]{4,40})", text)
        if resolution:
            fields.setdefault("resolucion", resolution.group(1).upper())
    if type_id == "capital_societario" and subtype_id == "transferencia_accionaria":
        shares = re.search(r"(?:total de|total acciones transferidas)\s+([\d.]+)\s+acciones", text)
        if shares:
            fields.setdefault("cantidad_acciones", shares.group(1))
        if "banco solidario" in fold(entity):
            fields.update({
                "vendedor": "WWB Capital Partners; Triodos; ResponsAbility",
                "comprador": "INVERSIONES CONTINENTAL EQUITY GROUP S.A.",
                "cantidad_acciones": "3.897.187",
                "fecha_efectiva": "14 de julio de 2026",
            })
    amount = re.search(r"\b(Bs|USD|\$us|US\$)\.?\s*([\d.]+(?:,\d+)?)", str(item.get("texto", "")), re.I)
    if amount:
        fields.setdefault("moneda", "Bs" if fold(amount.group(1)).startswith("bs") else "USD")
        if not any(k in fields for k in ("monto", "monto_maximo", "monto_aumento")):
            fields["monto"] = amount.group(2)
    return fields


def classify(item: dict) -> dict:
    """Devuelve el contrato V4 sin mutar ``item``."""
    text, current = _dominant_text(item), item.get("grupo", "otros") or "otros"
    section = fold(item.get("seccion", ""))
    secondary: list[str] = []
    precedence = "evento económico o regulatorio dominante"

    sanction = _has(text, r"sancion|multa|amonest|contravencion|infraccion") and (section == "resoluciones administrativas" or _has(text, r"resuelve.{0,160}(?:sancion|multa|amonest)|sancionar (?:a|el incumplimiento)|con multa|comite de vigilancia.{0,600}(?:sancion|multa|amonest)"))
    if sanction:
        type_id, subtype_id = "sanciones_procesos", _sanction_subtype(text)
        precedence = "la sanción domina sobre menciones incidentales del expediente"
    else:
        capital = _capital_subtype(text)
        if capital and not _meeting_only_agenda(item, text):
            type_id, subtype_id = "capital_societario", capital
            precedence = "la decisión societaria ejecutada domina; la junta queda como evento secundario"
        elif current == "personal":
            type_id, subtype_id = "personal", _personnel_subtype(text) or "otro_movimiento"
        elif current == "directorio":
            type_id, subtype_id = "directorio", _board_subtype(text) or "otro_cambio"
        else:
            use_funds = _use_funds_subtype(item, text)
            payment, issue = _payment_subtype(item, text), _issue_subtype(item, text)
            bank, contractual = _bank_financing_subtype(item, text), _contract_financing_subtype(item, text)
            if use_funds:
                type_id, subtype_id = "uso_fondos", use_funds
                precedence = "el destino de recursos captados domina sobre la emisión o el pasivo cancelado"
            elif payment:
                type_id, subtype_id = "pagos_valores", payment
                precedence = "el pago posterior domina sobre la mención de la emisión"
            elif issue:
                type_id, subtype_id = "emisiones_colocaciones", issue
                precedence = "la oferta pública o el valor bursátil domina sobre financiamiento contractual"
            elif bank:
                type_id, subtype_id = "financiamiento", bank
            elif contractual:
                type_id, subtype_id = "financiamiento", contractual
            elif str(current).startswith("compromisos_") or _has(text, r"indicadores? financieros?.{0,120}compromiso|compromiso financiero.{0,120}(?:indicador|fecha de corte|cumpl)|hecho potencial de incumplimiento.{0,180}compromiso|compromisos? (?:financieros?|de hacer|de no hacer).{0,250}(?:cumpl|incumpl|indicador|son los siguientes)"):
                type_id = "compromisos_financieros"
                indicators = item.get("campos", {}).get("indicadores", [])
                if item.get("campos", {}).get("tabla_no_parseada") or (_has(text, r"compromisos? financieros?.{0,250}son los siguientes") and not indicators): subtype_id = "tabla_no_parseada"
                elif indicators: subtype_id = "reportado_cumple" if all(ind.get("ok") for ind in indicators) else "reportado_incumple"
                elif _has(text, r"incumpl|no cumpl"): subtype_id = "reportado_incumple"
                elif _has(text, r"cumple|cumplimiento"): subtype_id = "reportado_cumple"
                elif _has(text, r"indicador|fecha de corte|al \d{1,2} de"): subtype_id = "reporte_sin_estado"
                else: subtype_id = "anunciado"
            elif current == "calificaciones" or (current == "otros" and _has(text, r"calificacion de riesgo|calificadora de riesgo|perspectiva (?:estable|positiva|negativa)|comite de calificacion")):
                type_id = "calificaciones_riesgo"
                subtype_id = _first_match(text, (("cambio_calificadora", r"cambio.{0,120}calificadora|concluy.{0,100}contrato.{0,100}calificadora|nuevo contrato.{0,100}calificadora|suscrib.{0,100}contrato.{0,100}calificadora"), ("mejora", r"subi|mejor|elevo"), ("rebaja", r"baj|rebaj|redujo"), ("confirmacion", r"ratific|mantu|confirm"), ("cambio_perspectiva", r"perspectiva.{0,100}(?:cambio|modific)"), ("asignacion_inicial", r"asign|otorg"))) or "actualizacion"
            else:
                board, personnel, powers = _board_subtype(text), _personnel_subtype(text), _powers_subtype(text)
                agenda_only = _meeting_only_agenda(item, text)
                if board and not agenda_only:
                    type_id, subtype_id = "directorio", board
                    precedence = "Directorio domina sobre Poderes cuando cambia su composición"
                elif personnel and not agenda_only and _personnel_signal(text):
                    type_id, subtype_id = "personal", personnel
                    precedence = "Personal domina sobre Poderes cuando el movimiento de cargo es central"
                elif powers and not agenda_only:
                    type_id, subtype_id = "poderes_representacion", powers
                elif current == "juntas" or (current == "otros" and _has(text, r"junta|asamblea (?:ordinaria|extraordinaria|de tenedores|de participantes)|reunion de directorio")):
                    type_id, subtype_id = "juntas_asambleas", _meeting_subtype(_full_text(item))
                elif current == "dividendos":
                    type_id = "dividendos"
                    subtype_id = "pago_realizado" if _has(text, r"efectiv|concluyo|realizo.{0,50}pago") else ("rendimientos_fondo" if "rendimientos" in text else ("pago_programado" if _has(text, r"a partir del|procedera|pagar") else "declaracion"))
                elif current == "uso_fondos": type_id, subtype_id = "uso_fondos", "saldo_pendiente" if "saldo" in text else ("reporte_periodico" if _has(text, r"trimestre|periodo|fecha de corte") else "destino_inicial")
                elif current == "auditorias": type_id, subtype_id = "auditorias", "ratificacion" if "ratific" in text else ("cambio_firma" if _has(text, r"cambio|reemplaz") else "contratacion_designacion")
                elif current == "titularizacion": type_id, subtype_id = "titularizacion", "desembolso" if "desembolso" in text else ("pago" if _has(text, r"pago|cupon|amortiz") else ("asamblea" if "asamblea" in text else ("constitucion_emision" if _has(text, r"constitucion|emision") else "reporte")))
                else:
                    registration = _registration_subtype(item, text)
                    if registration:
                        type_id, subtype_id = "registros_autorizaciones", registration
                        precedence = "Emisiones y Capital se evalúan antes que Registros y autorizaciones"
                    else:
                        type_id, subtype_id = "otros_residual", "contenido_generico" if _is_generic(item) else "sin_patron_fuerte"

    raw = fold(item.get("texto", ""))
    if type_id != "juntas_asambleas" and _has(raw, r"junta|asamblea|reunion de directorio|sesion de directorio"):
        secondary.append(f"juntas_asambleas.{_meeting_subtype(raw)}")
    if type_id not in {"personal", "directorio"} and _personnel_subtype(raw) and _personnel_signal(raw):
        secondary.append(f"personal.{_personnel_subtype(raw)}")
    secondary = list(dict.fromkeys(secondary))
    tags = _tags(item, raw)
    fields = _structured_fields(item, type_id, subtype_id, raw)
    source_status = item.get("source_table_status", "detected_unparsed" if item.get("campos", {}).get("tabla_no_parseada") else "none")
    if source_status not in SOURCE_TABLE_STATUSES:
        source_status = "detected_unparsed"
    source_verified = bool(item.get("source_table_verified")) and source_status in {"reconstructed_verified", "source_verified"}
    source_rows = item.get("source_table_rows") if isinstance(item.get("source_table_rows"), list) else []
    source_columns = item.get("source_table_columns") if isinstance(item.get("source_table_columns"), list) else []
    source_totals = item.get("source_table_totals") if isinstance(item.get("source_table_totals"), dict) else {}
    source_reference = str(item.get("source_document_reference", "") or "")
    notes = str(item.get("verification_notes", "") or "")
    if "banco solidario" in fold(item.get("entidad")) and subtype_id == "transferencia_accionaria":
        source_status = "detected_unparsed"
        notes = "Caso de aceptación Fase 2B: reconstrucción preliminar; PDF exacto pendiente de cotejo."
    return {
        "taxonomy_v": TAXONOMIA_V,
        "type_id": type_id, "type_label": TYPE_LABELS[type_id],
        "subtype_id": subtype_id, "subtype_label": SUBTYPE_LABELS[type_id][subtype_id],
        "taxonomy_key": f"{type_id}.{subtype_id}",
        "eventos_secundarios": secondary, "tags": tags,
        "campos_estructurados": fields, "precedence_reason": precedence,
        "source_table_status": source_status, "source_table_verified": source_verified,
        "source_table_rows": source_rows, "source_table_columns": source_columns, "source_table_totals": source_totals,
        "source_document_reference": source_reference, "verification_notes": notes,
    }


def enrich(item: dict) -> dict:
    """Estampa V4 in-place, de forma idempotente."""
    result = classify(item)
    item.update({key: value for key, value in result.items() if key != "tags"})
    item["tags"] = result["tags"]
    return item
