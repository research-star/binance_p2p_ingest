#!/usr/bin/env python3
"""Construye una preview ASFI V4 autónoma a partir del corpus local.

El destino debe vivir bajo ``tmp/``. No modifica ``static/``, no persiste V4
en los JSON productivos y no realiza llamadas de red.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import i18n_bake  # noqa: E402
from asfi_ingest import extract  # noqa: E402
from config import MODULOS_NO_BAKEADOS  # noqa: E402


BASE_CSS = r"""
:root{color-scheme:light;--bg-primary:#f4f1ea;--bg-secondary:#fffdf8;--bg-tertiary:#eee9df;--text-primary:#202528;--text-secondary:#50575b;--text-muted:#737a7e;--text-soft:#979c9f;--border-color:#d7d1c7;--line-strong:#bbb4a8;--blue-accent:#1e4d7a;--np-accent:#b5503f;--font-display:Georgia,'Times New Roman',serif;--font-mono:Consolas,'Courier New',monospace}
*{box-sizing:border-box}html,body{margin:0;max-width:100%;background:var(--bg-primary);color:var(--text-primary);font-family:Arial,Helvetica,sans-serif}body{overflow-x:hidden}button,input,select{font:inherit}.qa-shell{width:min(1440px,100%);margin:0 auto}.qa-header{padding:18px clamp(12px,3vw,34px);background:#192a38;color:#fff}.qa-header h1{margin:0;font:600 clamp(20px,3vw,31px)/1.15 var(--font-display)}.qa-header p{max-width:900px;margin:8px 0 0;color:#dce4e9;font-size:13px;line-height:1.5}.qa-scenarios{padding:14px clamp(12px,3vw,34px);border-bottom:1px solid var(--border-color);background:var(--bg-secondary)}.qa-scenarios h2{margin:0 0 9px;font-size:14px}.qa-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(230px,100%),1fr));gap:7px}.qa-scenario{display:block;min-width:0;padding:9px 10px;border:1px solid var(--border-color);background:var(--bg-primary);color:var(--text-primary);text-decoration:none}.qa-scenario:hover{border-color:var(--blue-accent)}.qa-scenario strong{display:block;color:var(--blue-accent);font:600 11px/1.3 var(--font-mono)}.qa-scenario span{display:block;margin-top:3px;font-size:11px;line-height:1.35;overflow-wrap:anywhere}.qa-note{margin:9px 0 0;color:var(--text-muted);font-size:10.5px}.fb-subheader{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:20px clamp(12px,3vw,34px) 12px}.fb-subheader h1{margin:0;font:600 clamp(20px,3vw,30px)/1.15 var(--font-display)}.fb-subtitle{margin-top:5px;color:var(--text-muted);font-size:12px}.content{padding:0 clamp(12px,3vw,34px) 34px;min-width:0}.fb-data-table{width:100%;border-collapse:collapse;font-size:12px}.fb-data-table th,.fb-data-table td{padding:8px 10px;border-top:1px solid var(--border-color);text-align:left}.fb-data-table th{background:var(--bg-tertiary);font:600 10px/1.2 var(--font-mono);text-transform:uppercase;color:var(--text-muted)}
@media(max-width:760px){.fb-subheader{display:block}.asfi-nav{margin-top:12px}}
"""


def _fold(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").lower()


def _searchable(row: dict) -> str:
    item = row["item"]
    return _fold(" ".join([
        str(item.get("entidad", "")), str(item.get("texto", "")),
        str(item.get("resumen", "")), str(item.get("categoria", "")),
        str(item.get("seccion", "")), json.dumps(item.get("campos_estructurados", {}), ensure_ascii=False),
        " ".join(item.get("eventos_secundarios", [])), " ".join(item.get("tags", [])),
    ]))


def _hash(date_range: str, *, type_id: str = "", subtypes: tuple[str, ...] = (), query: str = "") -> str:
    parts = [date_range]
    if type_id:
        parts.append(f"type={type_id}")
    if subtypes:
        parts.append("subtypes=" + ",".join(subtypes))
    if query:
        parts.append("q=" + query)
    return ";".join(parts)


def _expected(rows: list[dict], scenario_hash: str) -> int:
    parts = scenario_hash.split(";")
    date_part = parts.pop(0)
    if ".." in date_part:
        start, end = date_part.split("..", 1)
    else:
        start = end = date_part
    options = {}
    for part in parts:
        key, value = part.split("=", 1)
        options[key] = value
    selected = [row for row in rows if start <= row["fecha"] <= end]
    if options.get("type"):
        selected = [row for row in selected if row["item"]["type_id"] == options["type"]]
    if options.get("subtypes"):
        subtypes = set(options["subtypes"].split(","))
        selected = [row for row in selected if row["item"]["subtype_id"] in subtypes]
    if options.get("q"):
        needle = _fold(options["q"])
        selected = [row for row in selected if needle in _searchable(row)]
    return len(selected)


def _build_scenarios(rows: list[dict]) -> list[dict]:
    full = "2020-01-02..2026-07-15"
    by_month: dict[str, list[dict]] = defaultdict(list)
    by_year: Counter[str] = Counter()
    subtype_totals: Counter[str] = Counter()
    for row in rows:
        by_month[row["fecha"][:7]].append(row)
        by_year[row["fecha"][:4]] += 1
        subtype_totals[row["item"]["taxonomy_key"]] += 1

    month = max(
        by_month,
        key=lambda key: (
            len({row["item"]["type_id"] for row in by_month[key]})
            + len({row["item"]["taxonomy_key"] for row in by_month[key]}),
            len({row["item"]["type_id"] for row in by_month[key]}),
            len({row["item"]["taxonomy_key"] for row in by_month[key]}),
            len(by_month[key]), key,
        ),
    )
    year = max(by_year, key=lambda key: (by_year[key], key))
    multi = next(row for row in rows if len(row["item"].get("eventos_secundarios", [])) >= 2)
    no_fields = next(row for row in rows if not row["item"].get("campos_estructurados"))
    no_fields_query = no_fields["item"].get("entidad", "") or " ".join(
        re.findall(r"[\wáéíóúñÁÉÍÓÚÑ]+", no_fields["item"].get("resumen", ""))[:6]
    )
    table = next(row for row in rows if row["item"].get("subtype_id") == "tabla_no_parseada")
    singleton_key = sorted(key for key, count in subtype_totals.items() if count == 1)[0]
    singleton = next(row for row in rows if row["item"]["taxonomy_key"] == singleton_key)
    secondary = multi["item"]["eventos_secundarios"][0]

    definitions = [
        ("A", "Día de control · 15/07/2026", _hash("2026-07-15"), "Banco Solidario, OLEUM y todos los comunicados del día"),
        ("B", f"Mes de máxima diversidad · {month}", _hash(f"{month}-01..{month}-31"), "Máximo conjunto combinado de tipos y subtipos distintos"),
        ("C", f"Año de mayor volumen · {year}", _hash(f"{year}-01-01..{year}-12-31"), f"{by_year[year]} comunicados"),
        ("D", "Solo Capital y cambios societarios", _hash(full, type_id="capital_societario"), "Filtro de tipo"),
        ("E", "Solo Sanciones y procesos regulatorios", _hash(full, type_id="sanciones_procesos"), "Filtro de tipo"),
        ("F", "Solo Financiamiento", _hash(full, type_id="financiamiento"), "Filtro de tipo"),
        ("G", "Solo Registros y autorizaciones", _hash(full, type_id="registros_autorizaciones"), "Filtro de tipo"),
        ("H", "Solo Otros comunicados", _hash(full, type_id="otros_residual"), "Residual visible y separado"),
        ("I", "Documento con múltiples eventos", _hash(multi["fecha"], query=multi["item"].get("entidad", "")), multi["item_id"]),
        ("J", "Documento sin campos estructurados", _hash(no_fields["fecha"], query=no_fields_query), no_fields["item_id"]),
        ("K", "Documento con tabla_no_parseada", _hash(table["fecha"], type_id=table["item"]["type_id"], subtypes=("tabla_no_parseada",)), table["item_id"]),
        ("L", "Subtipo con un solo registro", _hash(full, type_id=singleton["item"]["type_id"], subtypes=(singleton["item"]["subtype_id"],)), singleton_key),
        ("M", "Búsqueda por entidad", _hash(full, query="Banco Solidario"), "Consulta textual preconfigurada"),
        ("N", "Búsqueda por evento secundario", _hash(full, query=secondary), secondary),
        ("O", "Selección múltiple de subtipos", _hash(full, type_id="capital_societario", subtypes=("transferencia_accionaria", "aportes_capitalizacion")), "Dos subtipos de Capital"),
    ]
    scenarios = []
    for code, title, scenario_hash, note in definitions:
        scenarios.append({
            "code": code, "title": title, "hash": scenario_hash,
            "href": "index.html#" + quote(scenario_hash, safe=".;=,_-"),
            "note": note, "expected_rows": _expected(rows, scenario_hash),
        })
    return scenarios


def _extract_shell(template: str) -> tuple[str, str]:
    marker = template.index("<!-- ═══ ASFI TAB")
    style_start = template.index("<style>", marker) + len("<style>")
    style_end = template.index("</style>", style_start)
    tab_start = template.index('<div id="tab-asfi"', style_end)
    tab_end = template.index("<!-- /tab-asfi -->", tab_start) + len("<!-- /tab-asfi -->")
    style = template[style_start:style_end]
    tab = template[tab_start:tab_end].replace('id="tab-asfi" style="display:none;"', 'id="tab-asfi" style="display:block;"', 1)
    return style, tab


def _patch_ui_for_preview(source: str) -> str:
    source = re.sub(r"var VIEWER='[^']*';", "var VIEWER='';", source, count=1)
    old = "function loadJson(url){return fetch(url,{cache:'no-cache'}).then(function(response){if(!response.ok)throw new Error(response.status);return response.json();});}"
    new = "function loadJson(url){var bundle=window.ASFI_V4_PREVIEW_DATA||{};if(url==='/asfi_index.json')return Promise.resolve(bundle.index);var match=url.match(/asfi_(\\d{4}-\\d{2})\\.json$/);if(match&&bundle.months&&bundle.months[match[1]])return Promise.resolve(bundle.months[match[1]]);return Promise.reject(new Error('Archivo local no incluido: '+url));}"
    if old not in source:
        raise RuntimeError("No se encontró loadJson esperado en el UI V4")
    return source.replace(old, new, 1)


def build_preview(output: Path) -> dict:
    output = output.resolve()
    tmp_root = (ROOT / "tmp").resolve()
    if output != tmp_root and tmp_root not in output.parents:
        raise ValueError(f"El preview debe quedar dentro de {tmp_root}")
    output.mkdir(parents=True, exist_ok=True)

    total = 0
    months: dict[str, dict] = {}
    rows: list[dict] = []
    for source in sorted((ROOT / "static").glob("asfi_????-??.json")):
        payload = json.loads(source.read_text(encoding="utf-8"))
        for date, report in sorted(payload.get("dias", {}).items()):
            enriched = []
            for index, original in enumerate(report.get("items", [])):
                item = extract.enriquecer(copy.deepcopy(original))
                enriched.append(item)
                rows.append({"item_id": f"asfi:{date}:{index:03d}", "fecha": date, "item": item})
                total += 1
            report["items"] = enriched
        month = source.stem.removeprefix("asfi_")
        months[month] = payload
        (output / source.name).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    index = json.loads((ROOT / "static" / "asfi_index.json").read_text(encoding="utf-8"))
    (output / "asfi_index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    scenarios = _build_scenarios(rows)
    (output / "scenarios.json").write_text(json.dumps(scenarios, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    bundle = "window.ASFI_V4_PREVIEW_DATA=" + json.dumps({"index": index, "months": months}, ensure_ascii=False, separators=(",", ":")) + ";\n"
    bundle = bundle.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    (output / "asfi-v4-preview-data.js").write_text(bundle, encoding="utf-8")

    ui_source = (ROOT / "static" / "asfi-taxonomy-v4-ui.js").read_text(encoding="utf-8")
    (output / "asfi-taxonomy-v4-ui.js").write_text(_patch_ui_for_preview(ui_source), encoding="utf-8")

    template = (ROOT / "template.html").read_text(encoding="utf-8")
    asfi_css, asfi_tab = _extract_shell(template)
    scenario_html = "".join(
        f'<a class="qa-scenario" href="{scenario["href"]}" target="_blank" rel="noopener"><strong>{scenario["code"]} · {scenario["title"]}</strong><span>{scenario["note"]} · {scenario["expected_rows"]} filas esperadas</span></a>'
        for scenario in scenarios
    )
    shell = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASFI V4 · Preview autónomo para QA</title><style>{BASE_CSS}\n{asfi_css}</style></head>
<body><div class="qa-shell"><header class="qa-header"><h1>ASFI V4 · QA visual y funcional</h1><p>Preview autónomo generado con 30.267 comunicados reales del corpus local. Los escenarios se abren en una pestaña nueva para aplicar el estado inicial completo.</p></header>
<section class="qa-scenarios"><h2>Escenarios obligatorios A–O</h2><div class="qa-grid">{scenario_html}</div><p class="qa-note">Los enlaces no requieren servidor, internet ni recursos externos. El enlace al documento ASFI está desactivado únicamente en este paquete autónomo.</p></section>
{asfi_tab}</div>
<script>window.ASFI_V4_I18N={{allTypes:'Todos los tipos',subtypes:'Subtipos',disclosures:'comunicados',structuredLabel:'Datos clave estructurados por FinanzasBo a partir del comunicado',secondary:'Eventos secundarios',noStructured:'No hay campos estructurados confiables para este comunicado.',openSource:'Abrir documento original',empty:'No hay comunicados para esta combinación de filtros.',loading:'Cargando…',error:'No se pudieron cargar los datos ASFI.',yes:'Sí',no:'No',sourceVerified:'Tabla publicada por ASFI',reconstructedVerified:'Tabla reconstruida por FinanzasBo a partir del comunicado de ASFI',reconstructedUnverified:'Datos estructurados preliminares — consulta el documento original',detectedUnparsed:'Posible tabla detectada; pendiente de cotejo'}};</script>
<script src="asfi-v4-preview-data.js"></script><script src="asfi-taxonomy-v4-ui.js"></script><script>window.renderAsfi();</script></body></html>"""
    html = i18n_bake.bake(shell, "es", "", i18n_bake.load_lang("es"), excluidos=MODULOS_NO_BAKEADOS)
    (output / "index.html").write_text(html, encoding="utf-8")
    return {"output": str(output), "items": total, "taxonomy_v": extract.TAXONOMIA_V, "scenarios": scenarios, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "asfi_v4_preview")
    args = parser.parse_args()
    result = build_preview(args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
