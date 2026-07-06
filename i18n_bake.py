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


def _raise_marker_error(text: str, m: 're.Match', motivo: str) -> None:
    linea = text.count('\n', 0, m.start()) + 1
    snippet = text[max(0, m.start() - 40):m.end() + 40]
    raise ValueError(
        f"i18n: marcadores es-only desbalanceados — {motivo} "
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


def bake(template_text: str, lang: str, base: str, table: dict) -> str:
    """Hornea el template para un idioma: strip ES-only → tokens → constantes.

    `base` es el prefijo de paths del deploy ('' para ES, '/en' para EN).
    """
    html = strip_es_only(template_text, keep_content=(lang == 'es'))
    html = resolve_tokens(html, table, lang)
    html = html.replace('{{lang}}', lang)
    html = html.replace('{{base}}', base)
    return html
