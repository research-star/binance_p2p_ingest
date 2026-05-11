"""Genera todos los rasters del favicon + OG image desde los SVG fuente."""
import cairosvg
from PIL import Image
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def svg_to_png(svg_name: str, png_name: str, size: int) -> None:
    cairosvg.svg2png(
        url=str(STATIC / svg_name),
        write_to=str(STATIC / png_name),
        output_width=size,
        output_height=size,
    )
    print(f"  {png_name} ({size}x{size})")


# Favicon en distintos tamaños
print("[favicon] PNG sizes:")
for size in (16, 32, 48, 180, 192, 512):
    suffix = {180: "apple-touch-icon", 192: "icon-192", 512: "icon-512"}.get(size, f"favicon-{size}")
    svg_to_png("favicon.svg", f"{suffix}.png", size)

# favicon.ico multi-resolución (16+32+48)
print("[favicon] ICO multi-res:")
ico_path = STATIC / "favicon.ico"
img = Image.open(STATIC / "favicon-48.png")
img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
print(f"  favicon.ico")

# OG image 1200x630
print("[og image]:")
cairosvg.svg2png(
    url=str(STATIC / "og.svg"),
    write_to=str(STATIC / "og.png"),
    output_width=1200,
    output_height=630,
)
print("  og.png (1200x630)")

print("\nListo. Archivos en static/")
