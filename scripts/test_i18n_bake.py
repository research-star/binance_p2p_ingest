#!/usr/bin/env python3
"""
test_i18n_bake.py — Tests del motor de i18n a tiempo de bake (i18n_bake.py).

Verifica:
  - resolve_tokens: happy path; clave faltante aborta listando TODAS las
    faltantes + el lang; '{{t:' sobreviviente aborta con snippet.
  - strip_es_only: marcadores HTML, JS, estilos mezclados de apertura/cierre,
    múltiples bloques, ambos modos de keep_content; marcadores desbalanceados
    (open huérfano, close huérfano, close tipeado entre bloques) abortan
    ruidoso en ambos modos.
  - bake(): semántica de orden — un token DENTRO de un bloque es-only no se
    exige para lang='en' (se stripea antes de resolver) pero SÍ para 'es'.
  - Sustitución de {{lang}} / {{base}}.
  - Higiene de diccionarios reales (i18n/*.json): sin comillas rectas en
    valores; keys(en) ⊆ keys(es).
  - Cobertura de tokens: todo {{t:clave}} de template.html existe en es.json
    Y en en.json (clave faltante = fallo en PR-time, no en el bake del VPS).
  - static/404.html: canary barato de la lógica prefix-aware /en.

Uso:  python -m pytest scripts/test_i18n_bake.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n_bake
from i18n_bake import bake, resolve_tokens, strip_es_only


# ── resolve_tokens ──────────────────────────────────────────────────────────


def test_resolve_tokens_happy_path():
    table = {'nav.tab_inicio': 'Inicio', 'nav.tab-p2p': 'P2P', 'a.b_c-d': 'X'}
    out = resolve_tokens(
        '<a>{{t:nav.tab_inicio}}</a><b>{{t:nav.tab-p2p}}</b>{{t:a.b_c-d}}',
        table, 'es')
    assert out == '<a>Inicio</a><b>P2P</b>X'


def test_resolve_tokens_repeated_token():
    out = resolve_tokens('{{t:k}} y {{t:k}}', {'k': 'V'}, 'es')
    assert out == 'V y V'


def test_resolve_tokens_missing_keys_lists_all_and_lang():
    """Aborta con TODAS las faltantes juntas (no muerte por mil cortes)."""
    table = {'presente': 'ok'}
    with pytest.raises(ValueError) as exc:
        resolve_tokens(
            '{{t:presente}} {{t:falta.una}} {{t:falta.otra}} {{t:falta.una}}',
            table, 'en')
    msg = str(exc.value)
    assert 'falta.una' in msg
    assert 'falta.otra' in msg
    assert "'en'" in msg
    assert 'presente' not in msg  # solo lista faltantes, no las resueltas


def test_resolve_tokens_leftover_raises_with_snippet():
    """Un '{{t:' que el regex no matchea (token malformado) no puede shippear."""
    # 'ñ' no entra en la clase de caracteres del token → queda sin resolver.
    with pytest.raises(ValueError) as exc:
        resolve_tokens('hola {{t:clave.ñ}} chau', {}, 'es')
    assert '{{t:' in str(exc.value)
    assert 'clave' in str(exc.value)


@pytest.mark.parametrize('malformado', [
    '{{ t:nav.tab_inicio }}',   # espacio tras {{
    '{{t :nav.tab_inicio}}',    # espacio antes de :
    '{{  t  :  clave  }}',      # whitespace generalizado
])
def test_resolve_tokens_leftover_whitespace_variants_raise(malformado):
    """Tokens con whitespace ({{ t:... }}) tampoco pueden shippear crudos."""
    with pytest.raises(ValueError) as exc:
        resolve_tokens(f'hola {malformado} chau', {'nav.tab_inicio': 'X'}, 'en')
    assert 'sin resolver' in str(exc.value)


# ── strip_es_only ───────────────────────────────────────────────────────────


def test_strip_html_markers_drop_span():
    text = 'A<!-- i18n:es-only -->guia<!-- /i18n:es-only -->B'
    assert strip_es_only(text, keep_content=False) == 'AB'


def test_strip_html_markers_keep_content():
    text = 'A<!-- i18n:es-only -->guia<!-- /i18n:es-only -->B'
    assert strip_es_only(text, keep_content=True) == 'AguiaB'


def test_strip_js_markers_both_modes():
    text = "x();/* i18n:es-only */soloEs();/* /i18n:es-only */y();"
    assert strip_es_only(text, keep_content=False) == 'x();y();'
    assert strip_es_only(text, keep_content=True) == 'x();soloEs();y();'


def test_strip_mixed_open_close_styles():
    """Apertura HTML + cierre JS (y viceversa) dentro del mismo bloque."""
    t1 = 'A<!-- i18n:es-only -->c/* /i18n:es-only */B'
    t2 = 'A/* i18n:es-only */c<!-- /i18n:es-only -->B'
    assert strip_es_only(t1, keep_content=False) == 'AB'
    assert strip_es_only(t2, keep_content=False) == 'AB'
    assert strip_es_only(t1, keep_content=True) == 'AcB'
    assert strip_es_only(t2, keep_content=True) == 'AcB'


def test_strip_multiple_blocks_lazy():
    """Non-greedy: dos bloques no se fusionan en un mega-span."""
    text = ('K1<!-- i18n:es-only -->uno<!-- /i18n:es-only -->K2'
            '/* i18n:es-only */dos/* /i18n:es-only */K3')
    assert strip_es_only(text, keep_content=False) == 'K1K2K3'
    assert strip_es_only(text, keep_content=True) == 'K1unoK2dosK3'


def test_strip_multiline_dotall():
    text = 'A<!-- i18n:es-only -->\nlinea1\nlinea2\n<!-- /i18n:es-only -->B'
    assert strip_es_only(text, keep_content=False) == 'AB'


def test_strip_no_markers_is_noop():
    text = '<div>sin marcadores</div>'
    assert strip_es_only(text, keep_content=False) == text
    assert strip_es_only(text, keep_content=True) == text


# ── strip_es_only: validación de apareamiento (abort ruidoso) ────────────────


@pytest.mark.parametrize('keep', [True, False])
def test_strip_unclosed_open_raises(keep):
    """Escenario A: open sin close (typo en el cierre) → abort, no ship."""
    text = ('X<!-- i18n:es-only -->Guia local'
            '<!-- /i18n:es-onli -->Y')  # cierre tipeado: no es marcador
    with pytest.raises(ValueError) as exc:
        strip_es_only(text, keep_content=keep)
    assert 'desbalanceados' in str(exc.value)
    assert 'apertura sin cierre' in str(exc.value)


@pytest.mark.parametrize('keep', [True, False])
def test_strip_typoed_close_between_blocks_raises(keep):
    """Escenario B (over-strip): close del bloque 1 tipeado → el span lazy se
    comería el contenido COMPARTIDO hasta el close del bloque 2. Debe abortar
    (dos aperturas seguidas), no borrar en silencio."""
    text = ('<!-- i18n:es-only -->uno<!-- /i18n:es-onli -->'  # close roto
            'COMPARTIDO'
            '<!-- i18n:es-only -->dos<!-- /i18n:es-only -->')
    with pytest.raises(ValueError) as exc:
        strip_es_only(text, keep_content=keep)
    assert 'apertura duplicada' in str(exc.value)


@pytest.mark.parametrize('keep', [True, False])
def test_strip_orphan_close_raises(keep):
    text = 'A<!-- /i18n:es-only -->B'
    with pytest.raises(ValueError) as exc:
        strip_es_only(text, keep_content=keep)
    assert 'cierre sin apertura' in str(exc.value)


def test_strip_error_includes_line_and_snippet():
    text = 'l1\nl2\nl3<!-- i18n:es-only -->huerfano\nl4'
    with pytest.raises(ValueError) as exc:
        strip_es_only(text, keep_content=False)
    msg = str(exc.value)
    assert 'línea 3' in msg
    assert 'huerfano' in msg


# ── bake: orden strip → resolve → constantes ────────────────────────────────

_TPL = ('<html lang="{{lang}}"><a href="{{base}}/">{{t:comun}}</a>'
        '<!-- i18n:es-only --><nav>{{t:solo.es}}</nav><!-- /i18n:es-only -->'
        '</html>')


def test_bake_en_token_inside_es_only_not_required():
    """El strip corre ANTES de resolver: 'solo.es' no se exige en EN."""
    out = bake(_TPL, 'en', '/en', {'comun': 'Common'})
    assert out == '<html lang="en"><a href="/en/">Common</a></html>'


def test_bake_es_token_inside_es_only_is_required():
    """Para ES el contenido queda → 'solo.es' SÍ debe estar en es.json."""
    with pytest.raises(ValueError) as exc:
        bake(_TPL, 'es', '', {'comun': 'Común'})
    assert 'solo.es' in str(exc.value)


def test_bake_es_full():
    out = bake(_TPL, 'es', '', {'comun': 'Común', 'solo.es': 'Guía'})
    assert out == ('<html lang="es"><a href="/">Común</a>'
                   '<nav>Guía</nav></html>')
    assert 'i18n:es-only' not in out  # sin basura de marcadores en ES


def test_bake_lang_base_substitution():
    out = bake('[{{lang}}|{{base}}|{{lang}}]', 'en', '/en', {})
    assert out == '[en|/en|en]'
    out_es = bake('[{{lang}}|{{base}}]', 'es', '', {})
    assert out_es == '[es|]'


# ── Higiene de los diccionarios reales ──────────────────────────────────────

_ES_JSON = ROOT / 'i18n' / 'es.json'
_EN_JSON = ROOT / 'i18n' / 'en.json'


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding='utf-8'))


def test_dict_values_no_straight_quotes():
    """Comillas rectas ' y \" prohibidas en valores (tipografía + no romper
    atributos HTML/JS al inyectar). Skip mientras en.json siga vacío
    (workstream f los llena)."""
    en = _load(_EN_JSON)
    if not en:
        pytest.skip('i18n/en.json aún vacío (lo llena el workstream f)')
    for name, table in (('es.json', _load(_ES_JSON)), ('en.json', en)):
        malos = {k: v for k, v in table.items() if "'" in v or '"' in v}
        assert not malos, f"{name}: comillas rectas en valores de {sorted(malos)}"


def test_template_tokens_exist_in_both_dicts():
    """Cobertura de tokens: TODO {{t:clave}} del template debe existir en
    es.json Y en en.json — mismo regex que el motor (_TOKEN_RE). Así una
    clave faltante rompe en PR-time (pytest) y no en el bake del VPS."""
    tpl = (ROOT / 'template.html').read_text(encoding='utf-8')
    keys = set(i18n_bake._TOKEN_RE.findall(tpl))
    assert keys, 'template.html sin tokens {{t:...}} — ¿regex o template rotos?'
    es, en = _load(_ES_JSON), _load(_EN_JSON)
    faltan_es = sorted(k for k in keys if k not in es)
    faltan_en = sorted(k for k in keys if k not in en)
    assert not faltan_es, f"tokens del template sin clave en es.json: {faltan_es}"
    assert not faltan_en, f"tokens del template sin clave en en.json: {faltan_en}"


def test_dict_en_keys_subset_of_es():
    """keys(en) ⊆ keys(es): en.json no puede inventar claves.

    NOTA: la invariante completa post-workstream-f sería «toda clave de
    es.json existe en en.json SALVO las usadas solo dentro de regiones
    es-only» — ese set depende del template y no es conocible en un unit
    test, así que acá solo se pinnea la dirección testeable (en ⊆ es).
    """
    en = _load(_EN_JSON)
    if not en:
        pytest.skip('i18n/en.json aún vacío (lo llena el workstream f)')
    es = _load(_ES_JSON)
    extras = set(en) - set(es)
    assert not extras, f"en.json inventa claves que no están en es.json: {sorted(extras)}"


# ── Calendario: bake productivo + gate admin ───────────────────────────────


def test_calendario_baked_only_es_and_admin_gated():
    """El hotfix publica Calendario en ES, pero botón, panel y ruta quedan
    detrás del gate de sesión. EN no debe heredar ninguna traza del módulo."""
    from config import MODULOS_NO_BAKEADOS

    assert 'calendario' not in MODULOS_NO_BAKEADOS
    tpl = (ROOT / 'template.html').read_text(encoding='utf-8')
    es = bake(tpl, 'es', '', i18n_bake.load_lang('es'),
              MODULOS_NO_BAKEADOS)
    en = bake(tpl, 'en', '/en', i18n_bake.load_lang('en'),
              MODULOS_NO_BAKEADOS)

    assert 'data-tab="calendario" data-admin-only hidden' in es
    assert 'id="tab-calendario" data-admin-only hidden' in es
    assert "'/calendario': {tab:'calendario'}" in es
    assert 'const CAL_DATA' in es
    assert 'fbCanActivateCalendar' in es
    assert '__fbAdminGateState' in es
    assert '__fbReconcileCalendarRoute' in es
    assert '#tab-calendario[hidden]{display:none!important}' in es
    assert "if(!fbCanActivateCalendar(target)){ target='noticias'" in es
    assert "fbSlug(location.pathname)==='/calendario')" in es

    trazas = (
        'data-tab="calendario"', 'tab-calendario', "'/calendario'",
        'const CAL_DATA', 'renderCalendario', 'fbCanActivateCalendar',
        '__fbAdminGateState', '__fbReconcileCalendarRoute',
    )
    assert all(traza not in en for traza in trazas)


# ── load_lang ───────────────────────────────────────────────────────────────


# ── Cobertura data.* (workstream f: labels COICOP/PIB por idioma) ──────────


def test_dashboard_coicop_pib_slugs_have_data_keys_in_both_dicts():
    """Todo slug de INE_IPC_DIVISIONES/INE_IPP_GRUPOS (dashboard.py) debe tener
    su clave data.coicop.<slug>/data.pib.<slug> en es.json Y en en.json —
    si no, el relabel EN cae al fallback genérico (slug.replace + capitalize)
    en vez de al label real. Import hermético: dashboard.py no toca la DB al
    importarse (side effects solo bajo `if __name__ == '__main__'`)."""
    sys.path.insert(0, str(ROOT))
    import dashboard  # noqa: E402 (import diferido a propósito)
    es, en = _load(_ES_JSON), _load(_EN_JSON)
    faltan_es, faltan_en = [], []
    for slug in dashboard.INE_IPC_DIVISIONES:
        key = f'data.coicop.{slug}'
        if key not in es:
            faltan_es.append(key)
        if key not in en:
            faltan_en.append(key)
    for slug in dashboard.INE_IPP_GRUPOS:
        key = f'data.pib.{slug}'
        if key not in es:
            faltan_es.append(key)
        if key not in en:
            faltan_en.append(key)
    assert not faltan_es, f"slugs COICOP/PIB sin clave en es.json: {sorted(faltan_es)}"
    assert not faltan_en, f"slugs COICOP/PIB sin clave en en.json: {sorted(faltan_en)}"


def test_load_lang_missing_file():
    with pytest.raises(FileNotFoundError):
        i18n_bake.load_lang('xx-inexistente')


def test_load_lang_tolerates_utf8_bom(tmp_path, monkeypatch):
    """PowerShell 5.1 / editores Windows suelen guardar con BOM: no debe
    romper el parseo JSON (utf-8-sig)."""
    (tmp_path / 'xx.json').write_bytes(
        b'\xef\xbb\xbf' + json.dumps({'k': 'v'}).encode('utf-8'))
    monkeypatch.setattr(i18n_bake, 'I18N_DIR', tmp_path)
    assert i18n_bake.load_lang('xx') == {'k': 'v'}


def test_load_lang_reads_real_dicts():
    assert isinstance(i18n_bake.load_lang('es'), dict)
    assert isinstance(i18n_bake.load_lang('en'), dict)


# ── 404.html: canary del bounce prefix-aware /en ────────────────────────────


def test_404_en_prefix_logic_present():
    html = (ROOT / 'static' / '404.html').read_text(encoding='utf-8')
    assert "'/en/?path=" in html
    assert "indexOf('/en/')" in html
    assert "pn === '/en'" in html
    assert 'Redirigiendo… · Redirecting…' in html


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
