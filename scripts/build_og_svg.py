"""Regenera static/og.svg con el texto OUTLINEADO a paths (font-independiente).

Por qué outline: cairosvg (el rasterizador de generate_static_assets.py) no tiene
Newsreader/Inter instaladas y caería a un sans genérico. Outlineando con la fuente
REAL, el SVG no depende de fuentes en el host → el raster es byte-determinista en
cualquier máquina (cierra el byte-drift). Fuente del wordmark = la del nameplate
(.fb-nameplate: var(--font-display)=Newsreader serif, weight 500, ls -0.01em);
texto de apoyo = Inter (var(--font-body), weight 400).

Flujo: este script reescribe og.svg; después correr generate_static_assets.py
para regenerar og.png desde el SVG. Para re-editar la copy del card: cambiar SPEC
abajo y re-correr ambos. Requiere `fonttools` + `brotli`; descarga las fuentes
variables de google/fonts a un cache temporal si no están.
"""
import os
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen

REPO = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("TEMP", "/tmp")) / "fbfonts"
FONTS = {
    "Newsreader": "https://github.com/google/fonts/raw/main/ofl/newsreader/Newsreader%5Bopsz,wght%5D.ttf",
    "Inter": "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
}


def load(name, axes):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.ttf"
    if not path.exists():
        urllib.request.urlretrieve(FONTS[name], path)
    f = TTFont(str(path))
    instantiateVariableFont(f, axes, inplace=True)
    return f


def text_to_paths(font, s, size, x, y, letter_spacing=0.0, anchor="start"):
    upm = font["head"].unitsPerEm
    sc = size / upm
    cmap = font.getBestCmap()
    gs = font.getGlyphSet()
    hmtx = font["hmtx"]
    total = 0.0
    for i, ch in enumerate(s):
        g = cmap.get(ord(ch))
        if g is None:
            continue
        total += hmtx[g][0] * sc
        if i < len(s) - 1:
            total += letter_spacing
    penx = (x - total) if anchor == "end" else x
    paths = []
    for i, ch in enumerate(s):
        g = cmap.get(ord(ch))
        if g is None:
            penx += size * 0.3
            continue
        pen = SVGPathPen(gs)
        gs[g].draw(pen)
        d = pen.getCommands()
        if d:
            paths.append(
                f'<path transform="translate({penx:.2f} {y:.2f}) '
                f'scale({sc:.5f} {-sc:.5f})" d="{d}"/>'
            )
        penx += hmtx[g][0] * sc
        if i < len(s) - 1:
            penx += letter_spacing
    return paths


NEWS = load("Newsreader", {"wght": 500, "opsz": 72})
INTER = load("Inter", {"wght": 400, "opsz": 14})

W, H = 1200, 630
# SPEC del card: (fuente, fill, texto, size, x, y, kwargs) — geometría intacta vs
# la composición previa (bg durazno + 3 barras negras + wordmark + 3 líneas).
els = [
    ("#211E1B", text_to_paths(NEWS, "FinanzasBo", 100, 380, 295, letter_spacing=-1.0)),
    ("#211E1B", text_to_paths(INTER, "Inteligencia económica de Bolivia", 32, 380, 350)),
    ("#6B6256", text_to_paths(INTER, "Noticias económicas · Datos macro · Análisis financiero", 22, 380, 392)),
    ("#6B6256", text_to_paths(INTER, "finanzasbo.com", 24, 1100, 580, anchor="end")),
]

lines = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
    '  <!-- Texto OUTLINEADO a paths (font-independiente). Wordmark = Newsreader 500',
    '       (=.fb-nameplate); apoyo = Inter 400. Re-generar: scripts/build_og_svg.py. -->',
    f'  <rect width="{W}" height="{H}" fill="#F7E4D7"/>',
    '  <rect x="100" y="315" width="48" height="120" rx="6" fill="#211E1B"/>',
    '  <rect x="168" y="275" width="48" height="160" rx="6" fill="#211E1B"/>',
    '  <rect x="236" y="235" width="48" height="200" rx="6" fill="#211E1B"/>',
]
for fill, paths in els:
    lines.append(f'  <g fill="{fill}">')
    lines += ["    " + p for p in paths]
    lines.append("  </g>")
lines.append("</svg>")

(REPO / "static" / "og.svg").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("og.svg escrito:", (REPO / "static" / "og.svg").stat().st_size, "bytes")
