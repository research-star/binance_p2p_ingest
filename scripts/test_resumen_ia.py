#!/usr/bin/env python3
"""test_resumen_ia.py — Degradación elegante del resumen IA.

Sin ANTHROPIC_API_KEY (o con NOTICIAS_RESUMEN=0): habilitado()=False, resumir()
devuelve None y aplicar() es no-op (conserva el extracto). NUNCA hace red en este
test. Uso: python scripts/test_resumen_ia.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticias_ingest import resumen_ia


class _FakeResp:
    """Respuesta HTTP simulada (context manager) — NO toca la red real."""
    def __init__(self, payload: dict):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _conn_spend(seed_usd: float | None = None):
    """Conn :memory: con api_spend creada (self-apply). Si seed_usd, siembra el mes."""
    conn = sqlite3.connect(":memory:")
    resumen_ia.init_spend_schema(conn)
    if seed_usd is not None:
        conn.execute("INSERT INTO api_spend (mes, est_usd) VALUES (?, ?)",
                     (resumen_ia._mes_utc(), seed_usd))
        conn.commit()
    return conn


def run() -> int:
    # Windows: la consola cp1252 no encodea '→' del mensaje OK (en el VPS Linux es
    # UTF-8). Reconfig defensivo para que la validación local no rompa por encoding.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    errores = []

    # Sin key → deshabilitado; resumir None; aplicar no-op (conserva summary).
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("NOTICIAS_RESUMEN", None)
    if resumen_ia.habilitado():
        errores.append("habilitado() debería ser False sin ANTHROPIC_API_KEY")
    if resumen_ia.resumir("Titular de prueba", "cuerpo de prueba") is not None:
        errores.append("resumir() debería devolver None sin key")
    notas = [{"title": "T", "detail": "D", "summary": "extracto original"}]
    n = resumen_ia.aplicar(notas)
    if n != 0 or notas[0]["summary"] != "extracto original":
        errores.append(f"aplicar() debería ser no-op sin key (n={n}, summary={notas[0]['summary']!r})")

    # Con key pero flag apagado → deshabilitado (no llama a la API).
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-no-se-usa"
    os.environ["NOTICIAS_RESUMEN"] = "0"
    if resumen_ia.habilitado():
        errores.append("habilitado() debería ser False con NOTICIAS_RESUMEN=0")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("NOTICIAS_RESUMEN", None)

    # _es_fallo: centinela / rechazo / vacío → True (degrada a extractivo);
    # un resumen real → False (se persiste como 'ia').
    fallo_si = ["INSUFICIENTE", "Insuficiente.", "No puedo resumir esta noticia porque…",
                "La noticia trata sobre Colombia, no Bolivia.", "Lo siento, no me es posible.", "", "   ",
                # V2.1: INSUFICIENTE + explicación pegada (prefijo anclado) → fallo
                "INSUFICIENTE\n\n(El texto solo contiene el titular.)",
                "INSUFICIENTE: el texto no aporta datos verificables.",
                "INSUFICIENTE — sin contenido más allá del título.",
                "INSUFICIENTE (no hay cuerpo)."]
    for t in fallo_si:
        if not resumen_ia._es_fallo(t):
            errores.append(f"_es_fallo({t!r}) debería ser True")
    fallo_no = ["El BCB anunció nuevas medidas para el tipo de cambio.",
                "De la Espriella conformará su gabinete con foco en seguridad y empleo.",
                # La palabra "insuficiente" en el cuerpo (no al inicio) NO es fallo
                "La cosecha fue insuficiente este año, según el informe del INE.",
                "Producción insuficiente para la demanda interna, advierte la CNI."]
    for t in fallo_no:
        if resumen_ia._es_fallo(t):
            errores.append(f"_es_fallo({t!r}) debería ser False")

    # Candado de gasto API: con key habilitada, una llamada SIN autorizado aborta
    # ANTES del POST; con autorizado=True pasa el candado. CERO red real (urlopen
    # monkeypatcheado a fallo → resumir degrada a None, sin tocar la API).
    os.environ["ANTHROPIC_API_KEY"] = "sk-fake-no-network"
    os.environ.pop("NOTICIAS_RESUMEN", None)
    try:
        resumen_ia.resumir("Titular", "cuerpo con datos verificables", "Bolivia")  # autorizado=False
        errores.append("resumir() ad-hoc sin autorizado debería abortar (RuntimeError)")
    except RuntimeError:
        pass  # esperado: candado cazó la llamada ad-hoc, sin POST
    # aplicar() sin autorizar también aborta (propaga el candado)
    try:
        resumen_ia.aplicar([{"title": "T", "detail": "cuerpo", "carril": "bolivia"}])
        errores.append("aplicar() ad-hoc sin autorizado debería abortar (RuntimeError)")
    except RuntimeError:
        pass
    # Con autorizado=True el candado NO aborta (pipeline-like). Con conn válido y
    # acumulado < cap, el flujo llega al POST; red simulada caída → TRANSITORIO (no
    # None: el sentinela de fallo REINTENTABLE, para que el re-resumen no marque el
    # cuerpo como ya-juzgado ante un blip de red).
    import urllib.request as _u
    _orig = _u.urlopen
    _u.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("red bloqueada en test"))
    try:
        r = resumen_ia.resumir("Titular", "cuerpo con datos", "Bolivia",
                               autorizado=True, conn=_conn_spend(0.0))
        if r is not resumen_ia.TRANSITORIO:
            errores.append(f"resumir(autorizado=True) con red caída debería dar TRANSITORIO (got {r!r})")
    except RuntimeError as e:
        errores.append(f"resumir(autorizado=True) NO debería abortar por candado: {e}")
    finally:
        _u.urlopen = _orig

    # ── Migración 0009 idempotente: re-aplicar init_spend_schema no falla ni duplica.
    conn_idem = sqlite3.connect(":memory:")
    resumen_ia.init_spend_schema(conn_idem)
    conn_idem.execute("INSERT INTO api_spend (mes, est_usd, llamadas) VALUES ('2026-01', 0.5, 3)")
    conn_idem.commit()
    resumen_ia.init_spend_schema(conn_idem)  # 2ª vez: CREATE TABLE IF NOT EXISTS → no-op
    fila = conn_idem.execute("SELECT est_usd, llamadas FROM api_spend WHERE mes='2026-01'").fetchone()
    if fila != (0.5, 3):
        errores.append(f"0009 no idempotente: re-aplicar alteró/duplicó la fila ({fila})")

    # ── CAP de gasto (2ª condición de aborto) ────────────────────────────────
    # (a) Cap alcanzado: acumulado >= CAP → resumir devuelve None SIN tocar urlopen.
    conn_cap = _conn_spend(resumen_ia.CAP_USD_MENSUAL)  # gastado == cap → bloquea
    llamado = {"n": 0}

    def _boom(*a, **k):
        llamado["n"] += 1
        raise AssertionError("urlopen NO debe llamarse con el cap alcanzado")
    _u.urlopen = _boom
    try:
        r = resumen_ia.resumir("Titular", "cuerpo con datos verificables", "Bolivia",
                               autorizado=True, conn=conn_cap)
        if r is not None:
            errores.append(f"cap alcanzado: resumir debería devolver None (got {r!r})")
        if llamado["n"] != 0:
            errores.append("cap alcanzado: no debió construir/disparar el POST")
    finally:
        _u.urlopen = _orig

    # (b) Acumulado < cap: el flujo construye y dispara el POST (mock, sin red real)
    # y la captura de usage acumula input/output_tokens en api_spend, SIN commit
    # (atómico con la persistencia de la nota — el caller commitea).
    conn_ok = _conn_spend(0.0)
    payload = {"content": [{"type": "text", "text": "El BCB fijó el dólar en Bs 6,96 según el informe oficial."}],
               "usage": {"input_tokens": 1200, "output_tokens": 40}}
    visto = {"called": False}

    def _ok(*a, **k):
        visto["called"] = True
        return _FakeResp(payload)
    _u.urlopen = _ok
    try:
        r = resumen_ia.resumir("Titular", "cuerpo largo con datos " * 30, "Bolivia",
                               autorizado=True, conn=conn_ok)
        if not visto["called"]:
            errores.append("acumulado<cap: debió construir y disparar el POST (mock)")
        if r != payload["content"][0]["text"]:
            errores.append(f"acumulado<cap: resumir debería devolver el texto del POST (got {r!r})")
        # Captura: usa input/output_tokens; costo = 1200/1e6*1 + 40/1e6*5.
        row = conn_ok.execute(
            "SELECT est_usd, llamadas, in_tokens, out_tokens FROM api_spend WHERE mes = ?",
            (resumen_ia._mes_utc(),)).fetchone()
        esperado = 1200 / 1e6 * resumen_ia.PRECIO_IN_USD_MTOK + 40 / 1e6 * resumen_ia.PRECIO_OUT_USD_MTOK
        if not row or abs(row[0] - esperado) > 1e-12 or row[1] != 1 or row[2] != 1200 or row[3] != 40:
            errores.append(f"captura usage incorrecta (esperado est_usd={esperado}, 1/1200/40): {row}")
        # Atomicidad: resumir NO commiteó → el gasto queda en transacción abierta,
        # listo para que el commit por nota del caller lo flushee junto al INSERT/UPDATE.
        if not conn_ok.in_transaction:
            errores.append("captura usage: resumir no debería commitear (atómico con la nota)")
    finally:
        _u.urlopen = _orig

    # (c) FAIL-CLOSED: si la lectura de api_spend falla (tabla ausente), resumir
    # devuelve None SIN tocar urlopen.
    conn_sin_tabla = sqlite3.connect(":memory:")  # NO init_spend_schema → api_spend no existe
    boom2 = {"n": 0}

    def _boom2(*a, **k):
        boom2["n"] += 1
        raise AssertionError("fail-closed: urlopen NO debe llamarse")
    _u.urlopen = _boom2
    try:
        r = resumen_ia.resumir("Titular", "cuerpo con datos", "Bolivia",
                               autorizado=True, conn=conn_sin_tabla)
        if r is not None:
            errores.append(f"fail-closed: resumir debería devolver None (got {r!r})")
        if boom2["n"] != 0:
            errores.append("fail-closed: no debió construir/disparar el POST")
    finally:
        _u.urlopen = _orig
        os.environ.pop("ANTHROPIC_API_KEY", None)

    if errores:
        print("FAIL test_resumen_ia:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_resumen_ia: sin key → resumir None + aplicar no-op; flag off respetado; "
          "_es_fallo distingue centinela/rechazo/vacío; candado API aborta ad-hoc sin "
          "autorizar y deja pasar autorizado=True; 0009 idempotente; CAP bloquea sin POST "
          "al alcanzar el techo, deja pasar bajo el techo capturando usage (sin commit), "
          "y fail-closea sin POST si api_spend es ilegible.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
