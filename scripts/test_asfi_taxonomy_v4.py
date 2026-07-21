from __future__ import annotations

import copy
import json
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pytest

from asfi_ingest import extract
from asfi_ingest.taxonomy_v4 import SOURCE_TABLE_STATUSES, SUBTYPE_LABELS, TYPE_LABELS, classify

ROOT = Path(__file__).resolve().parents[1]


@lru_cache
def corpus() -> dict[str, dict]:
    out = {}
    for path in sorted((ROOT / "static").glob("asfi_????-??.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for date, report in payload["dias"].items():
            for index, item in enumerate(report["items"]):
                out[f"asfi:{date}:{index:03d}"] = item
    return out


def item(text: str, *, group: str = "otros", section: str = "Hechos Relevantes", fields=None) -> dict:
    result = {"texto": text, "resumen": text, "entidad": "Entidad de prueba S.A.", "seccion": section, "grupo": group, "tags": []}
    if fields:
        result["campos"] = fields
    return result


def test_catalog_has_17_visible_types_and_120_stable_subtypes():
    assert len(TYPE_LABELS) == 17
    assert sum(map(len, SUBTYPE_LABELS.values())) == 120
    assert "financiamiento" in TYPE_LABELS
    assert "financiamiento_bancario" not in TYPE_LABELS
    assert "financiamiento_corporativo" not in TYPE_LABELS


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (item("Resolución que impone multa por Bs10.000 e instruye aumento de capital", section="Resoluciones Administrativas"), "sanciones_procesos.multa"),
        (item("La Junta Extraordinaria realizada determinó aprobar el aumento de capital por Bs5.000.000", group="juntas"), "capital_societario.aumento_capital"),
        (item("Se designó al señor Juan Pérez como Gerente General y se le otorgó poder", group="personal"), "personal.designacion"),
        (item("Suscribió un Pagaré Privado con un accionista por USD100.000"), "financiamiento.pagare_privado"),
        (item("Realizó la oferta pública y colocación de Pagarés Bursátiles Serie A"), "emisiones_colocaciones.colocacion_reportada"),
        (item("Según el Prospecto de Emisión de Bonos utilizó los fondos para recambio de pasivos"), "uso_fondos.destino_inicial"),
        (item("Concluyó el pago total de los Bonos Serie A", group="cupones"), "pagos_valores.pago_total_valor"),
        (item("Reportó compromisos financieros", group="compromisos_reportados", fields={"indicadores": [{"ok": False}]}), "compromisos_financieros.reportado_incumple"),
        (item("Compromisos financieros son los siguientes", group="compromisos_anunciados", fields={"tabla_no_parseada": True}), "compromisos_financieros.tabla_no_parseada"),
    ],
)
def test_dominant_event_precedence(source, expected):
    assert classify(source)["taxonomy_key"] == expected


def test_secondary_meeting_is_kept_and_searchable():
    result = classify(item("La Junta Extraordinaria realizada determinó aprobar el aumento de capital", group="juntas"))
    assert result["type_id"] == "capital_societario"
    assert result["eventos_secundarios"] == ["juntas_asambleas.junta_extraordinaria_realizada"]


def test_real_acceptance_cases_oleum_and_banco_solidario():
    oleum = classify(corpus()["asfi:2026-07-15:002"])
    assert oleum["taxonomy_key"] == "capital_societario.aportes_capitalizacion"
    assert oleum["campos_estructurados"]["monto_maximo"] == "Bs 34.000.000"
    assert oleum["campos_estructurados"]["fecha_limite"] == "31 de julio de 2026"
    assert oleum["eventos_secundarios"] == ["juntas_asambleas.junta_extraordinaria_realizada"]

    banco = classify(corpus()["asfi:2026-07-15:003"])
    assert banco["taxonomy_key"] == "capital_societario.transferencia_accionaria"
    assert banco["source_table_status"] == "detected_unparsed"
    assert banco["source_table_verified"] is False
    assert banco["source_table_rows"] == []
    assert "Fase 2B" in banco["verification_notes"]


@pytest.mark.parametrize(
    ("item_id", "expected"),
    [
        ("asfi:2024-08-14:010", "financiamiento.pagare_privado"),
        ("asfi:2025-11-11:019", "financiamiento.pagare_privado"),
        ("asfi:2026-03-30:032", "uso_fondos.destino_inicial"),
    ],
)
def test_three_redirected_destinations(item_id, expected):
    assert classify(corpus()[item_id])["taxonomy_key"] == expected


@pytest.mark.parametrize(
    ("item_id", "expected"),
    [
        ("asfi:2020-03-17:040", "otros_residual.sin_patron_fuerte"),
        ("asfi:2020-04-28:013", "dividendos.rendimientos_fondo"),
        ("asfi:2020-09-10:002", "juntas_asambleas.decisiones_adoptadas"),
        ("asfi:2020-08-31:001", "dividendos.pago_realizado"),
    ],
)
def test_curated_overrides_decided_2026_07_20(item_id, expected):
    """Los 4 hallazgos de revisión manual re-etiquetados por decisión de Diego."""
    result = classify(corpus()[item_id])
    assert result["taxonomy_key"] == expected
    assert "override curado" in result["precedence_reason"]


def test_enrich_keeps_legacy_compatibility_and_adds_v4_contract():
    enriched = extract.enriquecer(copy.deepcopy(corpus()["asfi:2026-07-15:002"]))
    assert enriched["grupo"] == "juntas"
    assert enriched["grupo_v"] == 4
    assert enriched["taxonomy_v"] == 4
    assert enriched["taxonomy_key"] == f"{enriched['type_id']}.{enriched['subtype_id']}"
    assert enriched["source_table_status"] in SOURCE_TABLE_STATUSES


def test_every_catalog_subtype_has_a_composite_key():
    keys = {f"{type_id}.{subtype_id}" for type_id, subtypes in SUBTYPE_LABELS.items() for subtype_id in subtypes}
    assert len(keys) == 120
    assert all(key.count(".") == 1 for key in keys)


@pytest.mark.skipif(os.environ.get("ASFI_RUN_CORPUS_TEST") != "1", reason="activar explícitamente para el pase corpus-wide")
def test_corpus_wide_totals_reconcile_v2_with_unified_financing():
    # Totales post-overrides curados (decisión de Diego 2026-07-20): dividendos
    # +1, juntas +1, emisiones -1, registros -1 respecto de la conciliación V2.
    expected = {
        "auditorias": 147, "calificaciones_riesgo": 239, "capital_societario": 1099,
        "compromisos_financieros": 1402, "directorio": 1064, "dividendos": 253,
        "emisiones_colocaciones": 2339, "financiamiento": 1851,
        "juntas_asambleas": 4879, "otros_residual": 2016, "pagos_valores": 6982,
        "personal": 4572, "poderes_representacion": 776,
        "registros_autorizaciones": 554, "sanciones_procesos": 1160,
        "titularizacion": 519, "uso_fondos": 415,
    }
    totals = Counter(classify(source)["type_id"] for source in corpus().values())
    assert sum(totals.values()) == 30267
    assert dict(totals) == expected

