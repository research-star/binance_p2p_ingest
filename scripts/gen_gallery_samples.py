#!/usr/bin/env python3
"""Genera los 14 .webp de ejemplo de la galería temática (v1) — dev-only.

Placeholders INTERINOS: color temático + label legible + eyebrow "muestra
ilustrativa". Obvios como no-foto a propósito; Diego los swapea por fotos
reales con el MISMO nombre (`static/gal-<slug>.webp`) → drop-in sin tocar código.

NO es parte del pipeline de producción. Pillow es la única dependencia y no
entra a requirements de prod. Reproducible: `python scripts/gen_gallery_samples.py`.

Slugs FIJOS (14) — deben matchear dashboard.py GALLERY_TEMA_SLUGS + genéricas +
'internacional', y el front arma /gal-<slug>.webp.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "static"
W, H = 1600, 1000  # 16:10, igual que el slot .np-imgph del front

# slug, label visible, color superior (RGB), color inferior (RGB)
SAMPLES = [
    ("combustibles",  "Combustibles · YPFB",         (178, 90, 42),  (110, 52, 23)),
    ("tipo-cambio",   "Tipo de cambio · Dólar",      (47, 107, 79),  (23, 58, 42)),
    ("litio",         "Litio · Minería",             (31, 110, 120), (14, 58, 64)),
    ("agro",          "Agropecuario · Soya",         (92, 122, 46),  (51, 71, 26)),
    ("deuda",         "Deuda · Finanzas",            (58, 63, 122),  (32, 35, 74)),
    ("inflacion",     "Inflación · Precios",         (158, 59, 59),  (92, 34, 34)),
    ("exportaciones", "Exportaciones · Comercio",    (47, 92, 143),  (24, 48, 76)),
    ("inversion",     "Inversión · Infraestructura", (74, 90, 110),  (42, 53, 64)),
    ("elecciones",    "Elecciones · Política econ.", (107, 58, 122), (62, 33, 71)),
    ("bloqueos",      "Bloqueos · Conflictos",       (162, 73, 42),  (92, 41, 23)),
    ("alimentos",     "EMAPA · Alimentos",           (154, 122, 46), (92, 74, 26)),
    ("economia",      "Economía",                    (78, 97, 113),  (46, 58, 69)),
    ("politica",      "Política",                    (90, 78, 110),  (51, 43, 64)),
    ("internacional", "Internacional",               (44, 74, 99),   (22, 39, 58)),
]

# Fuentes del sistema (Windows). Cae a la default bitmap si ninguna existe.
_BOLD = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
_REG = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]


def _font(paths, size):
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _fit(draw, text, paths, max_w, start=104, lo=44):
    size = start
    while size >= lo:
        f = _font(paths, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(paths, lo)


def _gradient(top, bottom):
    base = Image.new("RGB", (W, H))
    px = base.load()
    for y in range(H):
        t = y / (H - 1)
        col = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = col
    # hatch sutil para que se lea como muestra, no foto
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for x in range(-H, W, 26):
        od.line([(x, 0), (x + H, H)], fill=(255, 255, 255, 16), width=1)
    return Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")


def render(slug, label, top, bottom):
    img = _gradient(top, bottom)
    d = ImageDraw.Draw(img)
    margin = 70

    # eyebrow: marca de muestra
    eb_font = _font(_REG, 30)
    d.text((margin, margin), "M U E S T R A   I L U S T R A T I V A",
           font=eb_font, fill=(255, 255, 255, 235))

    # label central (auto-fit), con sombra suave
    lab_font = _fit(d, label, _BOLD, W - 2 * margin)
    bb = d.textbbox((0, 0), label, font=lab_font)
    lw, lh = bb[2] - bb[0], bb[3] - bb[1]
    lx = (W - lw) / 2 - bb[0]
    ly = (H - lh) / 2 - bb[1]
    d.text((lx + 3, ly + 3), label, font=lab_font, fill=(0, 0, 0))
    d.text((lx, ly), label, font=lab_font, fill=(255, 255, 255))

    # slug abajo-derecha
    sl_font = _font(_REG, 28)
    sw = d.textlength(f"gal-{slug}.webp", font=sl_font)
    d.text((W - margin - sw, H - margin - 28), f"gal-{slug}.webp",
           font=sl_font, fill=(255, 255, 255))

    out = OUT_DIR / f"gal-{slug}.webp"
    img.save(out, "WEBP", quality=82, method=6)
    return out, out.stat().st_size


def main():
    OUT_DIR.mkdir(exist_ok=True)
    print(f"Generando {len(SAMPLES)} .webp en {OUT_DIR} ...")
    for slug, label, top, bottom in SAMPLES:
        out, size = render(slug, label, top, bottom)
        print(f"  {out.name:28s} {size/1024:5.1f} KB  «{label}»")
    print("Listo. Drop-in: reemplazá un gal-<slug>.webp por la foto real (mismo nombre).")


if __name__ == "__main__":
    main()
