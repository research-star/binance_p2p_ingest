# Créditos — galería de imágenes temáticas (Noticias)

La mayoría de las imágenes `static/gal-<slug>.webp` (14 temáticas) son fotos de stock libres bajo la
**Pexels License** (uso comercial permitido, atribución **no** requerida). Tres slugs de **entidad**
(`fmi`, `banco-central`, `gobierno`) provienen de **Wikimedia Commons** (PD / CC0 / CC-BY-SA) — ver la
sección al final. Se documentan acá por trazabilidad de licencia. Cada una se recortó a 16:10 horizontal
y se convirtió a `.webp` (< 150 KB) para el slot `.np-imgph` del front (matching por keyword/`tema`, ver
`dashboard.py` `gallery_slug_v2` / `GALLERY_KEYWORD_PRIORITY` / `GALLERY_TEMA_SLUGS`).

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

## Imágenes de entidad — Wikimedia Commons

Tres slugs de **entidad** (`fmi`, `banco-central`, `gobierno`) NO usan Pexels: son sedes
institucionales de **Wikimedia Commons**, con licencia **verificada archivo por archivo**. Los
créditos CC se publican además en el sitio en **`/creditos-imagenes.html`** (link en el footer de
Inicio). PD/CC0 no requieren atribución; se listan por trazabilidad.

| slug | Tema / uso | Archivo (Commons) | Autor | Licencia | ¿Crédito? | URL |
|------|-----------|-------------------|-------|----------|-----------|-----|
| `fmi`           | Entidad · FMI (sede, Washington DC)                   | File:IMF building HR.jpg                      | International Monetary Fund | **Dominio público** | No      | <https://commons.wikimedia.org/wiki/File:IMF_building_HR.jpg> |
| `banco-central` | Entidad · Banco Central de Bolivia (edificio, La Paz) | File:Edificio del Banco Central de Bolivia.jpg | Qhanaaru                   | **CC0 1.0**         | No      | <https://commons.wikimedia.org/wiki/File:Edificio_del_Banco_Central_de_Bolivia.jpg> |
| `gobierno`      | Entidad · Palacio Quemado / Palacio de Gobierno (La Paz) | File:El Palacio Quemado en La Paz Bolivia.jpg | Parallelepiped09           | **CC BY-SA 4.0**    | **Sí**  | <https://commons.wikimedia.org/wiki/File:El_Palacio_Quemado_en_La_Paz_Bolivia.jpg> |

**CC BY-SA 4.0** (`gobierno`) — <https://creativecommons.org/licenses/by-sa/4.0/>: requiere atribución al
autor + indicar cambios (recortada/redimensionada a 1200×750) + compartir derivados bajo la misma
licencia. Atribución cumplida en `/creditos-imagenes.html`. Procesadas igual que las Pexels (recorte 16:10
1200×750, `.webp` < 150 KB, Pillow).

17/17 slugs con foto real (14 Pexels + 3 entidad Wikimedia). 0 quedaron a placeholder.
