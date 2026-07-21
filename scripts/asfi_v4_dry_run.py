#!/usr/bin/env python3
"""Ejecuta ASFI V4 sobre copias en memoria y concilia contra Fase 1.

No invoca red, IA ni ``ingest_asfi.py --reextraer``. Los únicos archivos que
puede escribir son el diagnóstico y la muestra indicados explícitamente.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asfi_ingest import extract  # noqa: E402
from asfi_ingest.taxonomy_v4 import SUBTYPE_LABELS, TYPE_LABELS, fold  # noqa: E402


TYPE_LABEL_ALIASES = {
    "Financiamiento bancario": "Financiamiento",
    "Financiamiento corporativo no bancario": "Financiamiento",
}
FINANCE_SUBTYPE_ALIASES = {
    ("Financiamiento bancario", "Contratación"): "Contratación bancaria",
    ("Financiamiento bancario", "Desembolso"): "Desembolso bancario",
    ("Financiamiento bancario", "Amortización"): "Amortización bancaria",
    ("Financiamiento bancario", "Cancelación total"): "Cancelación bancaria",
    ("Financiamiento corporativo no bancario", "Préstamo de parte vinculada"): "Préstamo de accionista o vinculada",
    ("Financiamiento corporativo no bancario", "Renovación o modificación"): "Renovación o modificación no bancaria",
    ("Financiamiento corporativo no bancario", "Cancelación o amortización"): "Cancelación o amortización no bancaria",
    ("Financiamiento corporativo no bancario", "Otro financiamiento no bancario"): "Otro financiamiento contractual no bursátil",
}
FINANCE_SUBTYPE_ID_ALIASES = {
    ("financiamiento_bancario", "contratacion"): "contratacion_bancaria",
    ("financiamiento_bancario", "desembolso"): "desembolso_bancario",
    ("financiamiento_bancario", "amortizacion"): "amortizacion_bancaria",
    ("financiamiento_bancario", "cancelacion_total"): "cancelacion_bancaria",
    ("financiamiento_corporativo", "desembolso"): "desembolso_no_bancario",
    ("financiamiento_corporativo", "renovacion_modificacion"): "renovacion_contractual",
    ("financiamiento_corporativo", "cancelacion_amortizacion"): "cancelacion_contractual",
    ("financiamiento_corporativo", "otro_financiamiento"): "otro_contractual_no_bursatil",
}
SUBTYPE_LABEL_ALIASES = {
    "Baja o cancelación RMV": "Cancelación en RMV",
}
KNOWN_SUBTYPE_DELTAS = {
    "financiamiento.contratacion_bancaria": 5,
    "financiamiento.uso_linea_credito": -5,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _static_hashes() -> dict[str, str]:
    return {path.name: _sha256(path) for path in sorted((ROOT / "static").glob("asfi_*.json"))}


def _phase1_default() -> Path:
    sibling = ROOT.parent / "binance_p2p_ingest" / "tmp"
    return sibling if sibling.exists() else ROOT / "tmp"


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _expected_labels(row: dict[str, str], type_col: str, subtype_col: str) -> tuple[str, str]:
    old_type, old_subtype = row[type_col], row[subtype_col]
    subtype = FINANCE_SUBTYPE_ALIASES.get((old_type, old_subtype), old_subtype)
    return TYPE_LABEL_ALIASES.get(old_type, old_type), SUBTYPE_LABEL_ALIASES.get(subtype, subtype)


def _safe_cell(value: object) -> str:
    text = str(value or "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _write_sample(path: Path, rows: list[dict]) -> None:
    columns = ["item_id", "fecha", "type_id", "subtype_id", "taxonomy_key", "entidad", "resumen", "eventos_secundarios", "tags"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _safe_cell(row.get(key, "")) for key in columns})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase1-dir", type=Path, default=_phase1_default())
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "asfi_v4_dry_run.json")
    parser.add_argument("--sample", type=Path, default=ROOT / "tmp" / "asfi_v4_stratified_sample.csv")
    args = parser.parse_args()

    phase1 = args.phase1_dir.resolve()
    required = [
        "asfi_chatgpt_509_review.csv", "asfi_residual_second_pass.csv",
        "asfi_existing_groups_recovery_v2.csv", "asfi_reconciliation_totals_v2.json",
        "asfi_taxonomy_types_subtypes.csv",
    ]
    missing = [name for name in required if not (phase1 / name).exists()]
    if missing:
        parser.error(f"Faltan insumos de Fase 1 en {phase1}: {', '.join(missing)}")

    before = _static_hashes()
    rows: list[dict] = []
    type_totals, subtype_totals = Counter(), Counter()
    annual_total, annual_residual = Counter(), Counter()
    source_states = Counter()
    for path in sorted((ROOT / "static").glob("asfi_????-??.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for date, report in sorted(payload.get("dias", {}).items()):
            for index, original in enumerate(report.get("items", [])):
                item = extract.enriquecer(copy.deepcopy(original))
                item_id = f"asfi:{date}:{index:03d}"
                record = {
                    "item_id": item_id, "fecha": date,
                    "type_id": item["type_id"], "type_label": item["type_label"],
                    "subtype_id": item["subtype_id"], "subtype_label": item["subtype_label"],
                    "taxonomy_key": item["taxonomy_key"], "entidad": item.get("entidad", ""),
                    "resumen": item.get("resumen", ""),
                    "eventos_secundarios": ";".join(item["eventos_secundarios"]),
                    "tags": ";".join(item["tags"]),
                    "source_table_status": item["source_table_status"],
                    "campos_estructurados": item["campos_estructurados"],
                }
                rows.append(record)
                type_totals[record["type_id"]] += 1
                subtype_totals[record["taxonomy_key"]] += 1
                annual_total[date[:4]] += 1
                if record["type_id"] == "otros_residual": annual_residual[date[:4]] += 1
                source_states[record["source_table_status"]] += 1
    by_id = {row["item_id"]: row for row in rows}

    reconciliation = json.loads((phase1 / "asfi_reconciliation_totals_v2.json").read_text(encoding="utf-8"))
    expected_types = Counter(reconciliation["universe"]["v2_types"])
    expected_types["financiamiento"] = expected_types.pop("financiamiento_bancario") + expected_types.pop("financiamiento_corporativo")
    type_delta = {key: type_totals[key] - expected_types[key] for key in TYPE_LABELS}
    expected_subtypes = Counter()
    for expected in _csv(phase1 / "asfi_taxonomy_types_subtypes.csv"):
        old_type, old_subtype = expected["type_id"], expected["subtype_id"]
        type_id = "financiamiento" if old_type in {"financiamiento_bancario", "financiamiento_corporativo"} else old_type
        subtype_id = FINANCE_SUBTYPE_ID_ALIASES.get((old_type, old_subtype), old_subtype)
        expected_subtypes[f"{type_id}.{subtype_id}"] += int(expected["documents"])
    subtype_delta = {
        key: subtype_totals[key] - expected_subtypes[key]
        for key in sorted(set(subtype_totals) | set(expected_subtypes))
        if subtype_totals[key] != expected_subtypes[key]
    }

    def audit(name: str, source: list[dict[str, str]], type_col: str, subtype_col: str, predicate=lambda row: True) -> dict:
        selected, mismatches = [row for row in source if predicate(row)], []
        for expected in selected:
            actual = by_id.get(expected["item_id"])
            expected_type, expected_subtype = _expected_labels(expected, type_col, subtype_col)
            if not actual or (actual["type_label"], actual["subtype_label"]) != (expected_type, expected_subtype):
                mismatches.append({
                    "item_id": expected["item_id"], "expected": [expected_type, expected_subtype],
                    "actual": [actual["type_label"], actual["subtype_label"]] if actual else None,
                })
        return {"rows": len(selected), "matched": len(selected) - len(mismatches), "mismatches": mismatches}

    review509 = _csv(phase1 / "asfi_chatgpt_509_review.csv")
    pass2 = _csv(phase1 / "asfi_residual_second_pass.csv")
    recoveries = _csv(phase1 / "asfi_existing_groups_recovery_v2.csv")
    audit509 = audit("509", review509, "grupo_principal_correcto", "subtipo_correcto")
    audit488 = audit("488", pass2, "tipo_principal_v2", "subtipo_v2", lambda row: row["decision_segunda_pasada"] == "RECUPERAR")
    audit_existing = audit("existing", recoveries, "tipo_principal_v2", "subtipo_v2")

    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        strata[(row["fecha"][:4], row["type_id"])].append(row)
    sample = []
    for key in sorted(strata):
        candidates = sorted(strata[key], key=lambda row: hashlib.sha256(row["item_id"].encode()).hexdigest())
        sample.extend(candidates[:2])
    _write_sample(args.sample.resolve(), sample)

    case_ids = ["asfi:2026-07-15:002", "asfi:2026-07-15:003", "asfi:2024-08-14:010", "asfi:2025-11-11:019", "asfi:2026-03-30:032"]
    audit_ok = not audit509["mismatches"] and not audit488["mismatches"] and not audit_existing["mismatches"]
    known_subtype_difference = subtype_delta == KNOWN_SUBTYPE_DELTAS
    status = "PASS_WITH_KNOWN_DIFFERENCES" if not any(type_delta.values()) and known_subtype_difference and audit_ok else ("PASS" if not any(type_delta.values()) and not subtype_delta and audit_ok else "REVIEW")
    report = {
        "status": status,
        "taxonomy_v": extract.TAXONOMIA_V,
        "safety": {
            "network_api_ai_calls": 0, "reextraer_executed": False,
            "productive_json_modified": before != _static_hashes(),
            "static_files_before": len(before), "static_files_after": len(_static_hashes()),
        },
        "universe": {"rows": len(rows), "date_range": [min(row["fecha"] for row in rows), max(row["fecha"] for row in rows)]},
        "type_totals_v4": dict(type_totals), "subtype_totals_v4": dict(subtype_totals),
        "v2_unified_expected": dict(expected_types), "type_delta_vs_v2": type_delta,
        "subtype_v2_unified_expected": dict(expected_subtypes), "subtype_delta_vs_v2": subtype_delta,
        "known_subtype_differences": {
            "expected_delta": KNOWN_SUBTYPE_DELTAS,
            "reason": "V2 buscaba `uso` sin límite de palabra y produjo cinco coincidencias incidentales (por ejemplo dentro de `recursos`); V4 exige verbo próximo a `línea de crédito`."
        },
        "residual_by_year": {
            year: {"rows": annual_residual[year], "total": annual_total[year], "pct": round(100 * annual_residual[year] / annual_total[year], 4)}
            for year in sorted(annual_total)
        },
        "audits": {"chatgpt_509": audit509, "independent_488": audit488, "existing_recovery_total": audit_existing},
        "redirected_three": {item_id: by_id[item_id] for item_id in case_ids[2:]},
        "acceptance_cases": {"oleum": by_id[case_ids[0]], "banco_solidario": by_id[case_ids[1]]},
        "source_table_states": dict(source_states),
        "stratified_sample": {"rows": len(sample), "strata": len(strata), "path": str(args.sample.resolve())},
        "stratified_review_findings": [
            {"scope": "corpus", "finding": "Cinco falsos `uso_linea_credito` por coincidencia de `uso` dentro de otras palabras.", "current_v4": "+5 contratacion_bancaria / -5 uso_linea_credito", "disposition": "Corrección técnica V4 aplicada; no altera el total del tipo Financiamiento."},
            {"item_id": "asfi:2020-03-17:040", "finding": "La palabra autorizados describe puntos de distribución, no un acto regulatorio.", "current_v4": "registros_autorizaciones.autorizacion_regulatoria", "disposition": "Conservado para respetar la recuperación 488; requiere decisión de Diego."},
            {"item_id": "asfi:2020-04-28:013", "finding": "Distribución de rendimientos de un fondo es candidata a dividendos.rendimientos_fondo.", "current_v4": "otros_residual.sin_patron_fuerte", "disposition": "Conservado según la decisión MANTENER_RESIDUAL de Fase 1; requiere decisión de Diego."},
            {"item_id": "asfi:2020-09-10:002", "finding": "La asamblea solo tomó conocimiento de informes; la mención de emisión no es una ejecución económica.", "current_v4": "emisiones_colocaciones.emision", "disposition": "Conservado para reconciliar V2; requiere decisión de Diego."},
            {"item_id": "asfi:2020-08-31:001", "finding": "Efectuó el pago de dividendos puede afinarse de declaración a pago_realizado.", "current_v4": "dividendos.declaracion", "disposition": "Diferencia de subtipo no aplicada para mantener la conciliación aprobada; requiere decisión de Diego."}
        ],
        "inputs": {name: {"path": str((phase1 / name).resolve()), "sha256": _sha256(phase1 / name)} for name in required},
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "rows": len(rows), "type_delta_vs_v2": type_delta, "subtype_delta_vs_v2": subtype_delta, "audits": report["audits"], "output": str(args.output.resolve()), "sample": str(args.sample.resolve())}, ensure_ascii=False, indent=2))
    return 0 if report["status"].startswith("PASS") and not report["safety"]["productive_json_modified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
