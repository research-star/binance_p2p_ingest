# Créditos — galería de imágenes temáticas (Noticias)

Las imágenes `static/gal-<slug>.webp` son fotos de stock libres bajo la **Pexels
License** (uso comercial permitido, atribución **no** requerida). Se documentan acá
por trazabilidad de licencia. Cada una se recortó a 16:10 horizontal y se convirtió a
`.webp` (< 150 KB) para el slot `.np-imgph` del front (matching por `tema`, ver
`dashboard.py` `GALLERY_TEMA_SLUGS`).

**Pexels License** — <https://www.pexels.com/license/>: "Free to use. Attribution is
not required." Permite uso comercial y modificación sin permiso del autor. (Algunas
fotos llegaron a Pexels desde Pixabay con licencia equivalente CC0.)

**Para swap de una foto:** dropeá tu `.webp` con el mismo nombre `gal-<slug>.webp` en
`static/` y actualizá la fila de abajo. Un slug sin archivo cae al placeholder cálido
del front (no rompe nada).

| slug | Tema / uso | Fotógrafo (Pexels) | Pexels ID | URL imagen |
|------|-----------|--------------------|-----------|------------|
| `combustibles`  | Combustibles / YPFB              | ddlogg            | 34636185 | <https://images.pexels.com/photos/34636185/pexels-photo-34636185.jpeg> |
| `tipo-cambio`   | Tipo de cambio / Dólar           | Pixabay           | 259027   | <https://images.pexels.com/photos/259027/pexels-photo-259027.jpeg> |
| `litio`         | Litio / Minería (Salar de Uyuni) | Jean-Paul Montanaro | 30612994 | <https://images.pexels.com/photos/30612994/pexels-photo-30612994.jpeg> |
| `agro`          | Agropecuario / Soya              | Dan Hamill        | 13821931 | <https://images.pexels.com/photos/13821931/pexels-photo-13821931.jpeg> |
| `deuda`         | Deuda / Finanzas                 | Pixabay           | 534216   | <https://images.pexels.com/photos/534216/pexels-photo-534216.jpeg> |
| `inflacion`     | Inflación / Precios              | Tara Clark        | 9070106  | <https://images.pexels.com/photos/9070106/pexels-photo-9070106.jpeg> |
| `exportaciones` | Exportaciones / Comercio         | Nezaket           | 31244440 | <https://images.pexels.com/photos/31244440/pexels-photo-31244440.jpeg> |
| `inversion`     | Inversión / Infraestructura      | vahapdmr          | 17297091 | <https://images.pexels.com/photos/17297091/pexels-photo-17297091.jpeg> |
| `elecciones`    | Elecciones / Política económica  | Fatima Yusuf      | 15993793 | <https://images.pexels.com/photos/15993793/pexels-photo-15993793.jpeg> |
| `bloqueos`      | Bloqueos / Conflictos            | Mohammed Abubakr  | 19488920 | <https://images.pexels.com/photos/19488920/pexels-photo-19488920.jpeg> |
| `alimentos`     | EMAPA / Alimentos                | Ninobur           | 17109241 | <https://images.pexels.com/photos/17109241/pexels-photo-17109241.jpeg> |
| `economia`      | Genérica · economía              | Steve             | 1006060  | <https://images.pexels.com/photos/1006060/pexels-photo-1006060.jpeg> |
| `politica`      | Genérica · política              | Keelan Clemens    | 4157284  | <https://images.pexels.com/photos/4157284/pexels-photo-4157284.jpeg> |
| `internacional` | Carril Latam · internacional     | Willian Justen    | 36024141 | <https://images.pexels.com/photos/36024141/pexels-photo-36024141.jpeg> |

14/14 slugs con foto real. 0 quedaron a placeholder.
