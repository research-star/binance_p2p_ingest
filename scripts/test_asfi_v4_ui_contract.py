from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "asfi-taxonomy-v4-ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "template.html").read_text(encoding="utf-8")


def test_frontend_has_type_subtype_search_sort_and_clear_controls():
    for control in ("asfiBuscar", "asfiTipo", "asfiSubtipos", "asfiOrden", "asfiLimpiarTema"):
        assert f'id="{control}"' in HTML


def test_shareable_url_keeps_dates_type_subtypes_query_and_sort():
    for token in ("syncHash", "type=", "subtypes=", "q=", "sort=", "state.from", "state.to"):
        assert token in JS
    assert "history.replaceState" in JS


def test_zero_result_subtypes_are_not_rendered_and_count_is_unique_per_item():
    assert "if(!subCounts[id])delete state.subtypes[id]" in JS
    assert "if(!typeCounts[type])return" in JS
    assert "entries.push({item:item,date:date,index:index" in JS


def test_search_includes_secondary_events_tags_and_structured_fields():
    assert "item.eventos_secundarios" in JS
    assert "item.tags" in JS
    assert "JSON.stringify(fields(item))" in JS


def test_only_same_origin_asfi_json_fetches_exist():
    fetch_fragments = [line for line in JS.splitlines() if "fetch(" in line]
    assert len(fetch_fragments) == 1
    assert "loadJson(url)" in fetch_fragments[0]
    assert "loadJson('/asfi_index.json')" in JS
    assert "loadJson('/asfi_'+month+'.json')" in JS
    for forbidden in ("openai", "api.openai", "XMLHttpRequest", "WebSocket"):
        assert forbidden not in JS.lower()


def test_tables_are_contained_and_global_overflow_is_not_hidden():
    assert ".table-scroll" in HTML
    assert "overflow-x:auto" in HTML
    assert "min-width:0" in HTML
    assert "overflow-x:hidden" not in HTML[HTML.index("<!-- ═══ ASFI TAB"):HTML.index("<!-- i18n:es-only -->", HTML.index("<!-- ═══ ASFI TAB"))]


def test_source_table_labels_and_structured_data_disclaimer_are_present():
    for key in ("source_verified", "reconstructed_verified", "reconstructed_unverified", "detected_unparsed"):
        assert key in JS
    assert "Datos clave estructurados por FinanzasBo" in (ROOT / "i18n" / "es.json").read_text(encoding="utf-8")

