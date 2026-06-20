#!/usr/bin/env python3
"""Verificación del motor de galería v1.1 (keyword-priority) — dashboard.gallery_slug_v2.

Reproducible y sin deps: `python scripts/test_gallery_keyword.py` (exit 0 = OK, 1 = falla).
Cubre los 5 casos del brief: (i) prioridad ante co-ocurrencia, (ii) límite de palabra,
(iii) multipalabra, (iv) fallback a tema sin keyword, (v) latam→internacional;
más una guarda de que ningún slug fuera de las 14 imágenes se emita.
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # consola Windows cp1252 → no crashear por glifos no-ASCII
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dashboard import gallery_slug_v2, _gal_wb, _gal_norm, VALID_GALLERY_SLUGS  # noqa: E402

PASS, FAIL = 0, 0


def check(desc, got, expected):
    global PASS, FAIL
    ok = got == expected
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"  [{'OK ' if ok else 'FALLA'}] {desc}\n          got={got!r} exp={expected!r}" if not ok
          else f"  [OK ] {desc}  -> {got!r}")


def v2(text, tema='General', category='economia', carril='bolivia'):
    # text va como title; summary/detail vacíos (se concatenan igual).
    return gallery_slug_v2(text, '', '', tema, category, carril)


print("== (i) PRIORIDAD ante múltiples matches (gana el de menor índice en la tabla) ==")
check("bloqueo + inflacion -> bloqueos (#2 < #7)", v2("Bloqueo de rutas dispara la inflacion"), "bloqueos")
check("eleccion + dolar -> elecciones (#1 < #11)", v2("En plena eleccion sube el dolar paralelo"), "elecciones")
check("ypfb + gobierno -> combustibles (#3 < #13)", v2("El gobierno y YPFB sobre el diesel"), "combustibles")
check("soya + exportacion -> exportaciones (#6 < #9)", v2("Exportacion de soya rompe record"), "exportaciones")

print("== (ii) LÍMITE DE PALABRA (no substring crudo) ==")
check("_gal_wb('oro') en 'ahorro' (mecanismo)", bool(_gal_wb('oro').search(_gal_norm('el ahorro'))), False)
check("_gal_wb('oro') en 'tesoro' (mecanismo)", bool(_gal_wb('oro').search(_gal_norm('tesoro general'))), False)
check("_gal_wb('oro') en 'deterioro' (mecanismo)", bool(_gal_wb('oro').search(_gal_norm('deterioro fiscal'))), False)
check("_gal_wb('oro') en 'precio del oro' (mecanismo)", bool(_gal_wb('oro').search(_gal_norm('precio del oro'))), True)
# 'paro' (bloqueos) NO debe matchear 'disparo'/'reparo'; 'surtidor' (combustibles) sí debe ganar
check("'disparo'/'reparo' NO disparan bloqueos; 'surtidor' -> combustibles",
      v2("Se reparo el disparo en el surtidor", tema='', category=None), "combustibles")

print("== (iii) MULTIPALABRA (frase con límite de palabra) ==")
check("'tipo de cambio paralelo' -> tipo-cambio", v2("Sube el tipo de cambio paralelo", tema='', category=None), "tipo-cambio")
check("'reservas internacionales' -> inversion", v2("Caen las reservas internacionales del BCB", tema='', category=None), "inversion")
check("'cambio climatico' NO matchea la frase 'tipo de cambio' (fallback)",
      v2("El cambio climatico afecta", tema='', category=None), None)

print("== (iv) FALLBACK a `tema` cuando no hay keyword ==")
check("sin keyword + tema fino -> slug del tema", v2("Reporte trimestral del sector", tema='Combustibles / YPFB'), "combustibles")
check("sin keyword + General + economia -> economia", v2("Actualidad nacional", tema='General', category='economia'), "economia")
check("sin keyword + General + politica -> politica", v2("Agenda de la jornada", tema='General', category='politica'), "politica")
check("sin keyword + sin tema + sin category -> None (placeholder)", v2("Texto neutro", tema='', category=None), None)

print("== (v) LATAM -> 'internacional' (el pass keyword NO aplica) ==")
check("latam con keyword 'eleccion' igual -> internacional", v2("Eleccion en la region", tema='', category=None, carril='latam'), "internacional")
check("latam neutro -> internacional", v2("Mercados globales", carril='latam'), "internacional")

print("== (vi) ENTIDAD gana a TEMA GENERAL (banda de entidades, proxy provisional) ==")
check("'banco central' + 'pib' -> inversion (ENT #4) no economia (#16)", v2("El banco central revisa el pib", tema='', category=None), "inversion")
check("'fmi' + 'gobierno' -> deuda (ENT #3) no politica (#17)", v2("El gobierno negocia con el fmi", tema='', category=None), "deuda")
check("'banco mundial' -> deuda (ENT #5 multilaterales)", v2("Desembolso del banco mundial", tema='', category=None), "deuda")
check("'asfi' -> inversion (ENT #6 proxy flojo)", v2("La ASFI regula la banca", tema='', category=None), "inversion")

print("== (vii) ENTIDAD: límite de palabra + multipalabra ==")
check("'fmi' standalone -> deuda", v2("acuerdo con el fmi", tema='', category=None), "deuda")
check("'fmi' NO matchea dentro de otra palabra", bool(_gal_wb('fmi').search(_gal_norm('confmiado xfmi'))), False)
check("'banco central' como FRASE -> inversion", v2("decision del banco central boliviano", tema='', category=None), "inversion")
check("'banco' suelto (sin central/mundial) NO dispara entidad -> None", v2("el banco privado presta", tema='', category=None), None)

print("== (viii) REGRESIÓN: sin keyword de entidad, orden de temas = v1 ==")
check("bloqueo + inflacion -> bloqueos (= v1)", v2("Bloqueo de rutas dispara la inflacion"), "bloqueos")
check("ypfb + gobierno -> combustibles (= v1)", v2("El gobierno y YPFB sobre el diesel"), "combustibles")
check("deuda externa sin entidad -> deuda (regla general; 'fmi' ya no vive acá)", v2("Sube la deuda externa", tema='', category=None), "deuda")

print("== GUARDA: ningún slug fuera de las 14 imágenes ==")
emitidos = set()
for t in ['eleccion', 'bloqueo', 'fmi', 'banco central', 'banco mundial', 'asfi', 'ypfb', 'litio',
          'deuda', 'exportacion', 'inflacion', 'alimento', 'agro', 'reservas internacionales',
          'dolar', 'pib', 'gobierno']:
    s = v2(t, tema='', category=None)
    if s:
        emitidos.add(s)
emitidos |= {v2("x", carril='latam'), v2("x", tema='General', category='economia'), v2("x", tema='General', category='politica')}
leak = emitidos - VALID_GALLERY_SLUGS
check("slugs emitidos <= VALID_GALLERY_SLUGS (14, subset)", leak, set())
print(f"          emitidos: {sorted(emitidos)}")

print(f"\nRESULTADO: {PASS} OK, {FAIL} FALLA")
sys.exit(1 if FAIL else 0)
