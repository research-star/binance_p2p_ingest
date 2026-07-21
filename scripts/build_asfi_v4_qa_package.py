#!/usr/bin/env python3
"""Empaqueta ASFI V4 para QA visual sin persistir ni publicar cambios."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp"
PREVIEW = TMP / "asfi_v4_preview"
STAGING = TMP / "asfi_v4_visual_qa_package"
ZIP_PATH = TMP / "asfi_v4_visual_qa_package.zip"
PHASE1_TMP = ROOT.parent / "binance_p2p_ingest" / "tmp"
sys.path.insert(0, str(ROOT))

from asfi_ingest import extract, taxonomy_v4  # noqa: E402
from scripts.build_asfi_v4_preview import build_preview  # noqa: E402


FORMULA_PREFIXES = ("=", "+", "-", "@")
TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".csv", ".md", ".txt"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def static_hashes() -> dict[str, str]:
    return {path.name: sha256(path) for path in sorted((ROOT / "static").glob("asfi_*.json"))}


def safe_cell(value: object) -> str:
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    elif value is None:
        text = ""
    else:
        text = str(value)
    return "'" + text if text.lstrip().startswith(FORMULA_PREFIXES) else text


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: safe_cell(row.get(column, "")) for column in columns})


def copy_csv_safely(source: Path, target: Path) -> None:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    write_csv(target, columns, rows)


def sanitize_paths(value: object) -> object:
    if isinstance(value, dict):
        return {key: sanitize_paths(child) for key, child in value.items()}
    if isinstance(value, list):
        return [sanitize_paths(child) for child in value]
    if isinstance(value, str) and re.search(r"[A-Za-z]:[\\/]", value):
        return Path(value).name
    return value


def original_rows() -> tuple[list[dict], object]:
    # Importar la implementación V2 después de conservar la referencia V4 evita
    # que el sys.path del script de Fase 1 sustituya el módulo activo.
    sys.path.insert(0, str(PHASE1_TMP))
    import asfi_build_exports as phase1_exports  # type: ignore
    import asfi_build_phase1_v2 as phase1  # type: ignore

    rows, _, _ = phase1_exports.load_rows()
    return rows, phase1


def relevant_v2_match(text: str) -> tuple[str, str]:
    match = re.search(r"\w*uso\w*", text, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"utiliz|dispuso", text, flags=re.IGNORECASE)
    if not match:
        return text[:700], "No se aisló la coincidencia; revisar el texto completo."
    start, end = max(0, match.start() - 220), min(len(text), match.end() + 420)
    token = match.group(0)
    return text[start:end], f"La alternativa V2 `uso` coincidió dentro de `{token}`."


def build_manual_findings(by_id: dict[str, dict], originals: dict[str, dict]) -> list[dict]:
    definitions = {
        "asfi:2020-03-17:040": {
            "hallazgo": "Falso positivo: “autorizados” describe puntos de distribución autorizados, no un nuevo acto regulatorio.",
            "riesgo": "Sobrerrepresentar Registros y autorizaciones y ocultar un comunicado que no contiene una autorización regulatoria nueva.",
            "recomendacion_codex": "Revisar el caso individual; no ampliar ni restringir la regla hasta que Diego confirme el sentido jurídico del texto.",
            "alternativa": "Reclasificar esta fila a otros_residual.sin_patron_fuerte si se confirma que no existe acto autorizatorio.",
            "decision_requerida_de_diego": "CORREGIR mueve 1 registro de registros_autorizaciones.autorizacion_regulatoria a Otros; MANTENER mueve 0. No se estima impacto corpus-wide sin diseñar y auditar una regla nueva.",
        },
        "asfi:2020-04-28:013": {
            "hallazgo": "Distribución de rendimientos de un fondo; es candidata a dividendos.rendimientos_fondo aunque Fase 1 decidió mantenerla residual.",
            "riesgo": "Subcontar rendimientos de fondos y conservar un evento económicamente interpretable dentro de Otros.",
            "recomendacion_codex": "Validar manualmente si el rendimiento distribuido debe tratarse como evento económico equivalente a dividendos/rendimientos.",
            "alternativa": "Reclasificar esta fila a dividendos.rendimientos_fondo.",
            "decision_requerida_de_diego": "CORREGIR mueve 1 registro de Otros a Dividendos y activa 1 caso en un subtipo hoy con 0; MANTENER mueve 0. No hay una regla general propuesta.",
        },
        "asfi:2020-09-10:002": {
            "hallazgo": "La asamblea tomó conocimiento de informes; la mención de una emisión no demuestra ejecución económica de una emisión.",
            "riesgo": "Confundir una referencia informativa o societaria con una emisión efectivamente realizada.",
            "recomendacion_codex": "Revisar el acto dominante y decidir si debe prevalecer Junta/Asamblea u Otros sobre Emisiones.",
            "alternativa": "Mover la fila a juntas_asambleas.decisiones_adoptadas o a otros_residual.sin_patron_fuerte, según lectura jurídica.",
            "decision_requerida_de_diego": "CORREGIR mueve exactamente 1 registro fuera de emisiones_colocaciones.emision; MANTENER mueve 0. La elección del destino requiere decisión de producto.",
        },
        "asfi:2020-08-31:001": {
            "hallazgo": "La frase “efectuó el pago de dividendos” puede afinar declaración a pago_realizado.",
            "riesgo": "Subestimar pagos consumados y mezclar declaración/aprobación con ejecución efectiva.",
            "recomendacion_codex": "Si Diego confirma que el verbo describe pago ya ejecutado, corregir únicamente este caso y luego auditar cualquier regla propuesta.",
            "alternativa": "Cambiar el subtipo a dividendos.pago_realizado.",
            "decision_requerida_de_diego": "CORREGIR mueve 1 registro dentro de Dividendos: declaración -1 y pago_realizado +1; MANTENER mueve 0. El total del tipo no cambia.",
        },
    }
    rows = []
    for item_id, decision in definitions.items():
        current = by_id[item_id]["item"]
        original = originals[item_id]["item"]
        rows.append({
            "item_id": item_id,
            "fecha": by_id[item_id]["fecha"],
            "entidad": current.get("entidad", ""),
            "resumen": current.get("resumen", ""),
            "texto": current.get("texto", ""),
            "tipo_v3": original.get("categoria", original.get("seccion", "")),
            "grupo_v3": original.get("grupo", ""),
            "tipo_v4": current["type_id"],
            "subtipo_v4": current["subtype_id"],
            "eventos_secundarios": ";".join(current.get("eventos_secundarios", [])),
            "tags": ";".join(current.get("tags", [])),
            "campos": current.get("campos_estructurados", {}),
            **decision,
        })
    if len(rows) != 4:
        raise AssertionError("El export de hallazgos debe contener exactamente cuatro filas")
    return rows


def build_financing_review(original_list: list[dict], phase1: object) -> list[dict]:
    rows = []
    for row in original_list:
        old = phase1.classify(row)
        if old.get("type_id") != "financiamiento_bancario" or old.get("subtype_id") != "uso_linea_credito":
            continue
        current = extract.enriquecer(copy.deepcopy(row["item"]))
        if current.get("type_id") != "financiamiento" or current.get("subtype_id") != "contratacion_bancaria":
            continue
        text = str(row["item"].get("texto", ""))
        relevant, exact_match = relevant_v2_match(text)
        rows.append({
            "item_id": row["item_id"], "fecha": row["fecha"], "entidad": row["item"].get("entidad", ""),
            "resumen": row["item"].get("resumen", ""), "texto_relevante": relevant,
            "tipo_v2": "financiamiento", "subtipo_v2": "uso_linea_credito",
            "senal_v2": "Regex V2 `uso|utiliz|dispuso.{0,60}linea de credito`. " + exact_match,
            "tipo_v4": "financiamiento", "subtipo_v4": "contratacion_bancaria",
            "senal_v4": "V4 exige un verbo real de uso/disposición próximo a la línea; aquí domina la suscripción u obtención contractual.",
            "clasificacion_recomendada": "financiamiento.contratacion_bancaria",
            "explicacion": "La coincidencia V2 no prueba utilización de fondos: `uso` podía aparecer dentro de otra palabra, típicamente `recursos`. V4 conserva el tipo y corrige solo el subtipo.",
            "posible_falso_positivo": "Revisar el documento si existiera evidencia no capturada de un desembolso o uso efectivo; no modificar la regla antes de la decisión de Diego.",
        })
    if len(rows) != 5:
        raise AssertionError(f"Se esperaban cinco diferencias de financiamiento y se obtuvieron {len(rows)}")
    return rows


def write_exports(preview_result: dict, dry: dict, package_exports: Path) -> dict:
    rows = preview_result["rows"]
    by_id = {row["item_id"]: row for row in rows}
    originals_list, phase1 = original_rows()
    originals = {row["item_id"]: row for row in originals_list}

    findings = build_manual_findings(by_id, originals)
    finding_columns = [
        "item_id", "fecha", "entidad", "resumen", "texto", "tipo_v3", "grupo_v3", "tipo_v4", "subtipo_v4",
        "eventos_secundarios", "tags", "campos", "hallazgo", "riesgo", "recomendacion_codex", "alternativa", "decision_requerida_de_diego",
    ]
    findings_path = TMP / "asfi_v4_manual_review_findings.csv"
    write_csv(findings_path, finding_columns, findings)
    shutil.copyfile(findings_path, package_exports / findings_path.name)

    financing = build_financing_review(originals_list, phase1)
    financing_columns = [
        "item_id", "fecha", "entidad", "resumen", "texto_relevante", "tipo_v2", "subtipo_v2", "senal_v2", "tipo_v4", "subtipo_v4",
        "senal_v4", "clasificacion_recomendada", "explicacion", "posible_falso_positivo",
    ]
    financing_path = TMP / "asfi_v4_financing_5_case_review.csv"
    write_csv(financing_path, financing_columns, financing)
    shutil.copyfile(financing_path, package_exports / financing_path.name)

    sample_source = TMP / "asfi_v4_stratified_sample.csv"
    copy_csv_safely(sample_source, package_exports / sample_source.name)

    type_rows = []
    for type_id, label in taxonomy_v4.TYPE_LABELS.items():
        expected = int(dry["v2_unified_expected"].get(type_id, 0))
        actual = int(dry["type_totals_v4"].get(type_id, 0))
        type_rows.append({"type_id": type_id, "type_label": label, "v2_expected": expected, "v4_actual": actual, "delta": actual - expected})
    write_csv(package_exports / "asfi_v4_reconciliation_by_type.csv", ["type_id", "type_label", "v2_expected", "v4_actual", "delta"], type_rows)

    subtype_rows = []
    actual_subtypes = dry["subtype_totals_v4"]
    expected_subtypes = dry["subtype_v2_unified_expected"]
    for type_id, labels in taxonomy_v4.SUBTYPE_LABELS.items():
        for subtype_id, label in labels.items():
            key = f"{type_id}.{subtype_id}"
            expected, actual = int(expected_subtypes.get(key, 0)), int(actual_subtypes.get(key, 0))
            subtype_rows.append({"taxonomy_key": key, "type_id": type_id, "subtype_id": subtype_id, "subtype_label": label, "v2_expected": expected, "v4_actual": actual, "delta": actual - expected})
    write_csv(package_exports / "asfi_v4_reconciliation_by_subtype.csv", ["taxonomy_key", "type_id", "subtype_id", "subtype_label", "v2_expected", "v4_actual", "delta"], subtype_rows)

    by_year, residual_by_year = Counter(), Counter()
    entities: dict[str, dict] = defaultdict(lambda: {"count": 0, "types": set(), "subtypes": set()})
    secondary_rows, structured_rows, table_rows = [], [], []
    for row in rows:
        item, year = row["item"], row["fecha"][:4]
        by_year[year] += 1
        if item["type_id"] == "otros_residual":
            residual_by_year[year] += 1
        entity = item.get("entidad", "") or "(sin entidad)"
        entities[entity]["count"] += 1
        entities[entity]["types"].add(item["type_id"])
        entities[entity]["subtypes"].add(item["taxonomy_key"])
        common = {
            "item_id": row["item_id"], "fecha": row["fecha"], "entidad": item.get("entidad", ""),
            "taxonomy_key": item["taxonomy_key"], "resumen": item.get("resumen", ""),
        }
        if item.get("eventos_secundarios"):
            secondary_rows.append({**common, "eventos_secundarios": ";".join(item["eventos_secundarios"]), "tags": ";".join(item.get("tags", []))})
        if item.get("campos_estructurados"):
            structured_rows.append({**common, "campos_estructurados": item["campos_estructurados"], "source_table_status": item.get("source_table_status", "none")})
        if item.get("subtype_id") == "tabla_no_parseada" or item.get("campos_estructurados", {}).get("tabla_no_parseada"):
            table_rows.append({**common, "campos_estructurados": item.get("campos_estructurados", {}), "source_table_status": item.get("source_table_status", "none")})

    year_rows = [{"year": year, "total": by_year[year], "otros_residual": residual_by_year[year], "otros_pct": round(100 * residual_by_year[year] / by_year[year], 4)} for year in sorted(by_year)]
    write_csv(package_exports / "asfi_v4_counts_by_year.csv", ["year", "total", "otros_residual", "otros_pct"], year_rows)
    write_csv(package_exports / "asfi_v4_other_counts.csv", ["year", "total", "otros_residual", "otros_pct"], year_rows)
    entity_rows = [{"entidad": entity, "documents": data["count"], "distinct_types": len(data["types"]), "distinct_subtypes": len(data["subtypes"])} for entity, data in entities.items()]
    entity_rows.sort(key=lambda row: (-row["documents"], row["entidad"]))
    write_csv(package_exports / "asfi_v4_counts_by_entity.csv", ["entidad", "documents", "distinct_types", "distinct_subtypes"], entity_rows)

    zero_rows = [row for row in subtype_rows if row["v4_actual"] == 0]
    low_rows = [row for row in subtype_rows if 1 <= row["v4_actual"] <= 5]
    write_csv(package_exports / "asfi_v4_zero_case_subtypes.csv", ["taxonomy_key", "type_id", "subtype_id", "subtype_label", "v4_actual"], zero_rows)
    write_csv(package_exports / "asfi_v4_low_volume_subtypes_1_5.csv", ["taxonomy_key", "type_id", "subtype_id", "subtype_label", "v4_actual"], low_rows)
    write_csv(package_exports / "asfi_v4_documents_with_secondary_events.csv", ["item_id", "fecha", "entidad", "taxonomy_key", "eventos_secundarios", "tags", "resumen"], secondary_rows)
    write_csv(package_exports / "asfi_v4_documents_with_structured_data.csv", ["item_id", "fecha", "entidad", "taxonomy_key", "campos_estructurados", "source_table_status", "resumen"], structured_rows)
    write_csv(package_exports / "asfi_v4_documents_table_no_parseada.csv", ["item_id", "fecha", "entidad", "taxonomy_key", "campos_estructurados", "source_table_status", "resumen"], table_rows)
    write_csv(package_exports / "asfi_v4_scenarios.csv", ["code", "title", "href", "note", "expected_rows"], preview_result["scenarios"])

    return {
        "findings": len(findings), "financing": len(financing), "secondary": len(secondary_rows),
        "structured": len(structured_rows), "table_no_parseada": len(table_rows),
        "zero_subtypes": len(zero_rows), "low_subtypes": len(low_rows), "entities": len(entity_rows),
    }


def build_readme(preview_result: dict, export_summary: dict, responsive_status: dict) -> str:
    scenario_lines = "\n".join(
        f'- **{item["code"]}. {item["title"]}** — `{item["href"]}`; revisar {item["note"].lower()} ({item["expected_rows"]} filas esperadas).'
        for item in preview_result["scenarios"]
    )
    responsive = responsive_status.get("summary", "No se encontró un navegador automatizable; no se afirma que el QA responsive haya pasado.")
    return f"""# ASFI V4 — paquete para QA visual y decisiones finales

## Cómo abrir

1. Descomprime todo el ZIP en una carpeta local.
2. Abre `preview/index.html` directamente con un navegador; no uses servidor.
3. Los enlaces A–O abren cada estado preconfigurado en una pestaña nueva.
4. Expande filas y subtipos para revisar resumen, texto, eventos secundarios, tags y datos clave.

El preview contiene los **30.267 comunicados reales** del corpus 2020-01-02 a 2026-07-15 embebidos localmente. No usa CDN, internet, API ni rutas del repositorio. El enlace al documento fuente se desactiva únicamente en este paquete autónomo.

## Escenarios A–O

{scenario_lines}

Para el mes B se maximiza primero la suma de tipos y subtipos distintos; los desempates usan cantidad de tipos, cantidad de subtipos, volumen y mes más reciente. El año C se elige por volumen total.

## Qué revisar

- Día A: presencia de Banco Solidario, OLEUM y los demás comunicados; tipo, subtipo, secundarios, datos clave y residual.
- Rangos B/C: agrupación tipo → subtipo, conteos, expansión y tabla horizontal contenida.
- D–H: filtros de tipo y tratamiento visual discreto de Otros.
- I–K: detalle, estado sin datos, eventos secundarios y tabla no parseada.
- L–O: casos de bajo volumen, búsqueda y combinación de subtipos.
- `exports/asfi_v4_manual_review_findings.csv`: exactamente cuatro decisiones pendientes; ninguna regla fue modificada.
- `exports/asfi_v4_financing_5_case_review.csv`: exactamente cinco diferencias V2/V4; ninguna regla fue modificada durante este empaquetado.
- Conciliaciones y listados cuantitativos: revisar deltas, ceros, subtipos 1–5 y cobertura de campos/eventos.

## Estado del QA responsive

{responsive}

## Resumen de exports

- Hallazgos manuales: {export_summary['findings']}.
- Diferencias de financiamiento: {export_summary['financing']}.
- Documentos con eventos secundarios: {export_summary['secondary']}.
- Documentos con datos estructurados: {export_summary['structured']}.
- Documentos con `tabla_no_parseada`: {export_summary['table_no_parseada']}.
- Subtipos sin casos: {export_summary['zero_subtypes']}.
- Subtipos con 1–5 casos: {export_summary['low_subtypes']}.

## Perímetro

Este paquete es diagnóstico. No persiste V4, no modifica los 74 JSON mensuales, no reextrae PDFs, no publica y no autoriza commit, merge ni despliegue.
"""


def verify_package(root: Path, before_hashes: dict[str, str]) -> dict:
    utf8_errors, absolute_paths, external_resources, formula_cells = [], [], [], []
    for path in sorted(file for file in root.rglob("*") if file.is_file()):
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                utf8_errors.append({"file": str(path.relative_to(root)), "error": str(exc)})
                continue
            # Evita falsos positivos por secuencias JSON como ``detalle:\n``;
            # una ruta local de Windows debe incluir una raíz de sistema real.
            local_path = re.search(
                r"(?i)\b[A-Z]:(?:\\\\|\\|/)(?:Users|Dev|Windows|Program Files|ProgramData|Temp)(?:\\\\|\\|/)",
                text,
            )
            if local_path or "file://" in text.lower():
                absolute_paths.append(str(path.relative_to(root)))
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row_number, row in enumerate(csv.reader(handle), start=1):
                    for column_number, cell in enumerate(row, start=1):
                        if cell.lstrip().startswith(FORMULA_PREFIXES):
                            formula_cells.append({"file": str(path.relative_to(root)), "row": row_number, "column": column_number})

    html = (root / "preview" / "index.html").read_text(encoding="utf-8")
    ui = (root / "preview" / "asfi-taxonomy-v4-ui.js").read_text(encoding="utf-8")
    for pattern in (r"https?://", r"(?i)(?:src|href)=[\"']/", r"(?i)\bfetch\s*\(", r"XMLHttpRequest", r"WebSocket"):
        if re.search(pattern, html + "\n" + ui):
            external_resources.append(pattern)
    required_preview = ["index.html", "asfi-v4-preview-data.js", "asfi-taxonomy-v4-ui.js", "scenarios.json"]
    missing_preview = [name for name in required_preview if not (root / "preview" / name).is_file()]
    after_hashes = static_hashes()
    return {
        "utf8": {"passed": not utf8_errors, "errors": utf8_errors},
        "absolute_local_paths": {"passed": not absolute_paths, "files": absolute_paths},
        "external_resources": {"passed": not external_resources, "patterns": external_resources},
        "csv_formulas": {"passed": not formula_cells, "cells": formula_cells},
        "autonomous_preview": {"passed": not missing_preview and not external_resources and not absolute_paths, "missing": missing_preview},
        "productive_json": {"passed": before_hashes == after_hashes, "files": len(after_hashes)},
    }


def main() -> int:
    before_hashes = static_hashes()
    preview_result = build_preview(PREVIEW)

    if STAGING.exists():
        resolved = STAGING.resolve()
        if resolved.parent != TMP.resolve() or resolved.name != "asfi_v4_visual_qa_package":
            raise RuntimeError(f"Destino de staging inesperado: {resolved}")
        shutil.rmtree(resolved)
    (STAGING / "exports").mkdir(parents=True)
    (STAGING / "docs").mkdir(parents=True)
    shutil.copytree(PREVIEW, STAGING / "preview")

    dry = json.loads((TMP / "asfi_v4_dry_run.json").read_text(encoding="utf-8"))
    sanitized_dry = sanitize_paths(dry)
    (STAGING / "exports" / "asfi_v4_dry_run.json").write_text(json.dumps(sanitized_dry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    export_summary = write_exports(preview_result, dry, STAGING / "exports")

    responsive_path = TMP / "asfi_v4_responsive_measurements.json"
    responsive = json.loads(responsive_path.read_text(encoding="utf-8")) if responsive_path.exists() else {
        "status": "NOT_RUN", "summary": "No se encontró un navegador automatizable; no se afirma que el QA responsive haya pasado.", "viewports": []
    }
    (STAGING / "docs" / "responsive_qa_status.json").write_text(json.dumps(responsive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    screenshots = TMP / "asfi_v4_screenshots"
    if screenshots.exists() and any(path.is_file() for path in screenshots.rglob("*")):
        shutil.copytree(screenshots, STAGING / "screenshots")
    readme = build_readme(preview_result, export_summary, responsive)
    (STAGING / "README.md").write_text(readme, encoding="utf-8")

    verification = verify_package(STAGING, before_hashes)
    (STAGING / "docs" / "package_verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not all(section["passed"] for section in verification.values()):
        raise AssertionError(json.dumps(verification, ensure_ascii=False))

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(file for file in STAGING.rglob("*") if file.is_file()):
            archive.write(path, path.relative_to(STAGING).as_posix())
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        names = archive.namelist()
    if bad:
        raise AssertionError(f"Entrada ZIP corrupta: {bad}")

    report = {
        "zip": str(ZIP_PATH.resolve()), "size_bytes": ZIP_PATH.stat().st_size, "sha256": sha256(ZIP_PATH),
        "file_count": len(names), "files": names, "verification": verification,
        "export_summary": export_summary, "scenarios": preview_result["scenarios"],
    }
    (TMP / "asfi_v4_visual_qa_package_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "files" and key != "scenarios"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
