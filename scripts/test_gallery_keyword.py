#!/usr/bin/env python3
"""Verificación del motor de galería v1.1 (keyword-priority) — dashboard.gallery_slug_v2.

Reproducible y sin deps: `python scripts/test_gallery_keyword.py` (exit 0 = OK, 1 = falla).
Cubre los 5 casos del brief: (i) prioridad ante co-ocurrencia, (ii) límite de palabra,
(iii) multipalabra, (iv) fallback a tema sin keyword, (v) latam→internacional; las
entidades con foto dedicada (fmi/banco-central/gobierno); más dos guardas: ningún slug
fuera de las 17 imágenes, y que cada gal-<slug>.webp exista en static/.
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
check("'reservas internacionales' -> inversion", v2("Caen las reservas internacionales del pais", tema='', category=None), "inversion")  # sin 'bcb': ahora 'bcb' es entidad banco-central
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

print("== (vi) ENTIDAD gana a TEMA GENERAL (fmi/banco-central con FOTO DEDICADA) ==")
check("'banco central' + 'pib' -> banco-central (ENT) no economia", v2("El banco central revisa el pib", tema='', category=None), "banco-central")
check("'fmi' + 'gobierno' -> fmi (ENT, gana a la entidad gobierno y a politica)", v2("El gobierno negocia con el fmi", tema='', category=None), "fmi")
check("'banco mundial' -> deuda (ENT multilaterales, proxy provisional)", v2("Desembolso del banco mundial", tema='', category=None), "deuda")
check("'asfi' -> inversion (ENT proxy flojo)", v2("La ASFI regula la banca", tema='', category=None), "inversion")

print("== (vii) ENTIDAD: límite de palabra + multipalabra ==")
check("'fmi' standalone -> fmi", v2("acuerdo con el fmi", tema='', category=None), "fmi")
check("'fmi' NO matchea dentro de otra palabra", bool(_gal_wb('fmi').search(_gal_norm('confmiado xfmi'))), False)
check("'banco central' como FRASE -> banco-central", v2("decision del banco central boliviano", tema='', category=None), "banco-central")
check("'banco' suelto (sin central/mundial) NO dispara entidad -> None", v2("el banco privado presta", tema='', category=None), None)

print("== (vii.b) ENTIDAD gobierno: foto dedicada, SOBRE las generales y BAJO los temas concretos ==")
check("'gobierno' standalone -> gobierno (ya no politica)", v2("El gobierno anuncia medidas", tema='', category=None), "gobierno")
check("'ministerio' -> gobierno", v2("El ministerio confirma el plan", tema='', category=None), "gobierno")
check("'ministro' -> gobierno (antes politica)", v2("Habla el ministro del area", tema='', category=None), "gobierno")
check("'plaza murillo' (frase) -> gobierno", v2("Concentracion en plaza murillo", tema='', category=None), "gobierno")
check("'asamblea legislativa' (frase) -> gobierno", v2("Sesion en la asamblea legislativa", tema='', category=None), "gobierno")
check("'casa grande del pueblo' (frase) -> gobierno", v2("Acto en la casa grande del pueblo", tema='', category=None), "gobierno")
# gobierno NO override un tema concreto de arriba:
check("'gobierno' + 'diesel' -> combustibles (tema concreto gana a gobierno)", v2("El gobierno sube el diesel", tema='', category=None), "combustibles")
check("'gobierno' + 'litio' -> litio (tema concreto gana a gobierno)", v2("El gobierno y el litio del salar", tema='', category=None), "litio")
# 'ley'/'decreto'/'asamblea' suelta NO migran a la sede: siguen en la regla politica general:
check("'decreto' suelto -> politica (regla general intacta)", v2("Nuevo decreto presidencial", tema='', category=None), "politica")
check("'ley' suelta -> politica (regla general intacta)", v2("Aprueban la ley de la republica", tema='', category=None), "politica")

print("== (viii) REGRESIÓN: sin keyword de entidad, orden de temas = v1 ==")
check("bloqueo + inflacion -> bloqueos (= v1)", v2("Bloqueo de rutas dispara la inflacion"), "bloqueos")
check("ypfb + gobierno -> combustibles (= v1)", v2("El gobierno y YPFB sobre el diesel"), "combustibles")
check("deuda externa sin entidad -> deuda (regla general; 'fmi' ya no vive acá)", v2("Sube la deuda externa", tema='', category=None), "deuda")

print("== (ix) FIXES DE TABLA APROBADOS (post-review) ==")
check("plural 'combustibles' ahora matchea -> combustibles", v2("Escasez de combustibles en el pais", tema='', category=None), "combustibles")
check("'marcha' fuera de bloqueos: 'marcha atras al diesel' -> combustibles", v2("Dan marcha atras al alza del diesel", tema='', category=None), "combustibles")
check("'marcha' fuera: 'la marcha de la economia' YA NO -> bloqueos", v2("La buena marcha de la economia", tema='', category=None) != "bloqueos", True)
check("'divisas' movido: 'mercado de divisas' -> tipo-cambio (no exportaciones)", v2("El mercado de divisas se tensa", tema='', category=None), "tipo-cambio")
check("'divisa' singular sigue -> tipo-cambio", v2("compra de divisa extranjera", tema='', category=None), "tipo-cambio")

print("== GUARDA: ningún slug fuera de las 17 imágenes ==")
emitidos = set()
for t in ['eleccion', 'bloqueo', 'fmi', 'banco central', 'banco mundial', 'asfi', 'gobierno',
          'ministerio', 'plaza murillo', 'ypfb', 'litio', 'deuda', 'exportacion', 'inflacion',
          'alimento', 'agro', 'reservas internacionales', 'dolar', 'pib']:
    s = v2(t, tema='', category=None)
    if s:
        emitidos.add(s)
emitidos |= {v2("x", carril='latam'), v2("x", tema='General', category='economia'), v2("x", tema='General', category='politica')}
leak = emitidos - VALID_GALLERY_SLUGS
check("slugs emitidos <= VALID_GALLERY_SLUGS (17, subset)", leak, set())
print(f"          emitidos: {sorted(emitidos)}")

print("== GUARDA FAIL-FAST: cada slug emisible tiene su gal-<slug>.webp en static/ ==")
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
faltan = sorted(s for s in VALID_GALLERY_SLUGS
                if not os.path.isfile(os.path.join(STATIC_DIR, f'gal-{s}.webp')))
check("todos los VALID_GALLERY_SLUGS tienen archivo (incl. fmi/banco-central/gobierno)", faltan, [])

print(f"\nRESULTADO: {PASS} OK, {FAIL} FALLA")
sys.exit(1 if FAIL else 0)
