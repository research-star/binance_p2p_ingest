#!/usr/bin/env python3
"""
i18n_bake.py — Motor de i18n a tiempo de bake (sin traducción en runtime).

dashboard.py hornea el template DOS veces (index.html en español, en/index.html
en inglés) resolviendo tokens {{t:clave.con.puntos}} contra los diccionarios
planos i18n/es.json e i18n/en.json. Además:

- Constantes horneadas: los placeholders literales {{lang}} y {{base}} del
  template se reemplazan por 'es'/'en' y ''/'/en' respectivamente.
- Regiones ES-only: bloques del template envueltos en marcadores
  <!-- i18n:es-only --> ... <!-- /i18n:es-only -->  (estilo HTML) o
  /* i18n:es-only */  ... /* /i18n:es-only */       (estilo JS)
  — los estilos de apertura y cierre pueden mezclarse dentro de un mismo
  bloque. Para lang != 'es' se elimina el span completo (marcadores
  incluidos); para 'es' se eliminan SOLO los comentarios marcadores (el
  contenido queda), así el output español no arrastra basura de marcadores.
- Clave faltante = abort ruidoso listando TODAS las claves ausentes (nunca se
  shippea un {{t:...}} crudo); tras resolver se asserta que no quede ninguno.

Orden del bake: strip_es_only → resolve_tokens → {{lang}}/{{base}}. El strip
va primero para que un token usado SOLO dentro de una región ES-only no sea
exigido en en.json.

Stdlib only. Uso desde dashboard.py:
    import i18n_bake
    html = i18n_bake.bake(template, 'en', '/en', i18n_bake.load_lang('en'))
"""

import json
import re
from pathlib import Path

I18N_DIR = Path(__file__).parent / 'i18n'

# Token de traducción: {{t:clave}} con claves punteadas tipo "nav.tab_inicio".
_TOKEN_RE = re.compile(r'\{\{t:([A-Za-z0-9_.\-]+)\}\}')

# Marcadores ES-only. Apertura y cierre aceptan cualquiera de los dos estilos
# de comentario (HTML o JS) — pueden diferir dentro del mismo bloque. El span
# es lazy (non-greedy) + DOTALL para soportar múltiples bloques multilínea.
_ES_ONLY_OPEN = r'(?:<!--\s*i18n:es-only\s*-->|/\*\s*i18n:es-only\s*\*/)'
_ES_ONLY_CLOSE = r'(?:<!--\s*/i18n:es-only\s*-->|/\*\s*/i18n:es-only\s*\*/)'
_ES_ONLY_SPAN_RE = re.compile(
    _ES_ONLY_OPEN + r'.*?' + _ES_ONLY_CLOSE, re.DOTALL)
_ES_ONLY_MARKER_RE = re.compile(
    r'(?:' + _ES_ONLY_OPEN + r'|' + _ES_ONLY_CLOSE + r')')
# Para validar apareamiento: distingue apertura de cierre con grupos nombrados.
_ES_ONLY_ANY_RE = re.compile(
    r'(?P<open>' + _ES_ONLY_OPEN + r')|(?P<close>' + _ES_ONLY_CLOSE + r')')
# Post-assert de tokens sobrevivientes: tolerante a whitespace ({{ t: ...}})
# para atrapar typos que _TOKEN_RE no matchea y que shippearían crudos.
_TOKEN_LEFTOVER_RE = re.compile(r'\{\{\s*t\s*:')


def load_lang(lang: str) -> dict:
    """Carga i18n/<lang>.json y valida que sea un objeto plano str→str.

    Errores ruidosos y accionables: archivo faltante, JSON inválido, raíz que
    no es objeto, o valores no-string — cada uno con path y detalle.
    """
    path = I18N_DIR / f'{lang}.json'
    if not path.exists():
        raise FileNotFoundError(
            f"i18n: no existe el diccionario {path} (lang={lang!r})")
    try:
        # utf-8-sig: idéntico a utf-8 para archivos limpios, pero tolera el
        # BOM que Windows/PowerShell 5.1 suelen anteponer al guardar.
        table = json.loads(path.read_text(encoding='utf-8-sig'))
    except ValueError as e:
        raise ValueError(f"i18n: JSON inválido en {path}: {e}") from e
    if not isinstance(table, dict):
        raise ValueError(
            f"i18n: {path} debe ser un objeto JSON plano, no "
            f"{type(table).__name__}")
    malos = [k for k, v in table.items()
             if not isinstance(k, str) or not isinstance(v, str)]
    if malos:
        raise ValueError(
            f"i18n: {path} debe mapear str→str; claves con valor no-string: "
            f"{sorted(map(str, malos))}")
    return table


def _validate_es_only_pairing(text: str) -> None:
    """Valida que los marcadores es-only alternen estrictamente open→close.

    Sin esto, un marcador huérfano o mal tipeado degrada en silencio: un open
    sin close shippea el contenido ES + el comentario crudo al EN, y un close
    tipeado deja que el span lazy se coma contenido COMPARTIDO hasta el close
    del bloque siguiente. Abort ruidoso con línea y snippet del ofensor.
    """
    expecting_open = True
    last = None
    for m in _ES_ONLY_ANY_RE.finditer(text):
        is_open = m.lastgroup == 'open'
        if is_open != expecting_open:
            _raise_marker_error(text, m,
                                'apertura duplicada (falta el cierre del '
                                'bloque anterior)' if is_open
                                else 'cierre sin apertura previa')
        expecting_open = not expecting_open
        last = m
    if not expecting_open:
        _raise_marker_error(text, last, 'apertura sin cierre (bloque sin '
                                        'cerrar al final del template)')


def _raise_marker_error(text: str, m: 're.Match', motivo: str,
                        tipo: str = 'es-only') -> None:
    linea = text.count('\n', 0, m.start()) + 1
    snippet = text[max(0, m.start() - 40):m.end() + 40]
    raise ValueError(
        f"i18n: marcadores {tipo} desbalanceados — {motivo} "
        f"(línea {linea}): ...{snippet!r}...")


def strip_es_only(text: str, keep_content: bool) -> str:
    """Procesa las regiones ES-only del template.

    keep_content=True  (lang='es'): elimina SOLO los comentarios marcadores,
                        dejando el contenido — el ES no lleva basura i18n.
    keep_content=False (lang!='es'): elimina el span completo, marcadores
                        incluidos.

    Pre-condición (ambos modos): los marcadores deben alternar open/close
    balanceados — si no, ValueError (ver _validate_es_only_pairing).
    """
    _validate_es_only_pairing(text)
    if keep_content:
        return _ES_ONLY_MARKER_RE.sub('', text)
    return _ES_ONLY_SPAN_RE.sub('', text)


# ── Módulos opcionales (desbake, opción B) ──────────────────────────────────
# Marcadores análogos a es-only pero por MÓDULO: envuelven cada punto de contacto
# de un módulo desbakeable con su nombre. Mismo par de estilos de comentario
# (HTML <!-- --> / JS-CSS /* */) y misma técnica de span lazy+DOTALL.
#   <!-- bake:optional:dpf --> ... <!-- /bake:optional:dpf -->
#   /* bake:optional:dpf */    ... /* /bake:optional:dpf */
# Semántica (gobernada por el set `excluidos` = config.MODULOS_NO_BAKEADOS):
#   módulo EN excluidos     → se elimina el span completo (contenido + marcadores).
#   módulo NO en excluidos  → se eliminan solo los marcadores (el contenido queda),
#                             de modo que re-bakear = quitarlo del set, sin más.
_OPT_OPEN_TMPL = r'(?:<!--|/\*)\s*bake:optional:{name}\s*(?:-->|\*/)'
_OPT_CLOSE_TMPL = r'(?:<!--|/\*)\s*/bake:optional:{name}\s*(?:-->|\*/)'
# Descubre los nombres de módulo presentes (solo aperturas; el `/` del cierre
# impide que esta regex matchee un marcador de cierre).
_OPT_NAME_RE = re.compile(r'(?:<!--|/\*)\s*bake:optional:(?P<mod>[\w-]+)\s*(?:-->|\*/)')


def _opt_open_re(name: str) -> 're.Pattern':
    return re.compile(_OPT_OPEN_TMPL.format(name=re.escape(name)))


def _opt_close_re(name: str) -> 're.Pattern':
    return re.compile(_OPT_CLOSE_TMPL.format(name=re.escape(name)))


def _opt_span_re(name: str) -> 're.Pattern':
    return re.compile(
        _OPT_OPEN_TMPL.format(name=re.escape(name)) + r'.*?'
        + _OPT_CLOSE_TMPL.format(name=re.escape(name)), re.DOTALL)


def _validate_optional_pairing(text: str, name: str) -> None:
    """Como _validate_es_only_pairing pero por módulo: los marcadores de `name`
    deben alternar open→close. Un huérfano degradaría en silencio (span lazy se
    come contenido compartido, o marcador crudo shippeado)."""
    any_re = re.compile(
        r'(?:<!--|/\*)\s*(?P<close>/)?bake:optional:' + re.escape(name)
        + r'\s*(?:-->|\*/)')
    expecting_open = True
    last = None
    for m in any_re.finditer(text):
        is_open = not m.group('close')
        if is_open != expecting_open:
            _raise_marker_error(
                text, m,
                f"módulo {name!r}: apertura duplicada (falta cierre)" if is_open
                else f"módulo {name!r}: cierre sin apertura previa",
                tipo='bake:optional')
        expecting_open = not expecting_open
        last = m
    if not expecting_open:
        _raise_marker_error(text, last,
                            f"módulo {name!r}: apertura sin cierre",
                            tipo='bake:optional')


def strip_optional_modules(text: str, excluidos) -> str:
    """Procesa los marcadores bake:optional según `excluidos` (iterable de
    nombres de módulo). Ver el bloque de docs de arriba para la semántica.

    Valida el apareamiento de TODOS los módulos presentes ANTES de mutar (los
    spans de módulos distintos no se anidan entre sí, así que el orden de strip
    es indiferente; validar sobre el texto original evita falsos positivos)."""
    excluidos = set(excluidos or ())
    nombres = sorted({m.group('mod') for m in _OPT_NAME_RE.finditer(text)})
    for name in nombres:
        _validate_optional_pairing(text, name)
    for name in nombres:
        if name in excluidos:
            text = _opt_span_re(name).sub('', text)
        else:
            text = _opt_open_re(name).sub('', text)
            text = _opt_close_re(name).sub('', text)
    return text


def resolve_tokens(text: str, table: dict, lang: str) -> str:
    """Resuelve todos los {{t:clave}} contra `table`.

    Falla ruidoso: junta TODAS las claves faltantes antes de abortar (un solo
    error con la lista completa, no muerte por mil cortes). Post-condición:
    ningún '{{t:' puede sobrevivir — si queda (token malformado que el regex
    no matcheó), aborta mostrando un snippet alrededor de la primera
    ocurrencia.
    """
    faltantes = []
    for key in _TOKEN_RE.findall(text):
        if key not in table and key not in faltantes:
            faltantes.append(key)
    if faltantes:
        raise ValueError(
            f"i18n: {len(faltantes)} clave(s) faltante(s) en el diccionario "
            f"'{lang}': {sorted(faltantes)}")

    text = _TOKEN_RE.sub(lambda m: table[m.group(1)], text)

    sobrante = _TOKEN_LEFTOVER_RE.search(text)
    if sobrante:
        pos = sobrante.start()
        snippet = text[max(0, pos - 40):pos + 80]
        raise ValueError(
            f"i18n: quedó un '{{{{t:' sin resolver (lang={lang!r}) cerca de: "
            f"...{snippet!r}...")
    return text


def bake(template_text: str, lang: str, base: str, table: dict,
         excluidos=None) -> str:
    """Hornea el template para un idioma: strip ES-only → strip módulos
    desbakeados → tokens → constantes.

    `base` es el prefijo de paths del deploy ('' para ES, '/en' para EN).
    `excluidos` es el set de módulos a NO bakear (config.MODULOS_NO_BAKEADOS);
    None/vacío = bakear todo. El strip de módulos va tras es-only y antes de
    resolver tokens (para no exigir en el diccionario tokens que viven solo en
    un módulo desbakeado), misma razón que el orden de es-only.
    """
    html = strip_es_only(template_text, keep_content=(lang == 'es'))
    html = strip_optional_modules(html, excluidos)
    html = resolve_tokens(html, table, lang)
    html = html.replace('{{lang}}', lang)
    html = html.replace('{{base}}', base)
    return html
