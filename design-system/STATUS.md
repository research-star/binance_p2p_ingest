# STATUS — design-system/

> ✅ **Regenerado contra `main`** — refleja el estado real de `template.html`
> @ `b787584` (navbar v3 / chrome editorial incluido). Ya **no hay staleness**.

## Provenance

- **`design-reference.html`**: CSS (`<style>`) + objeto `THEMES` copiados **verbatim**
  de `template.html` (byte-idénticos, verificado por diff). Showcase con navbar v3
  (utility + masthead + nav + buscador), tokens fríos `#fafbfe` / `#2c4a6b`, Outfit.
- **`template.snapshot.html`**: copia fiel completa de `template.html` (4983 líneas).
- **`DESIGN-SYSTEM.md`**: tokens corregidos (`--bg-primary:#fafbfe`, `--border-color:.12`,
  `--text-secondary:#6b7d92`, `--radius-lg:2px`), pesos de fuente (Inter 400–700) y
  catálogo con refs de línea al template actual.

## Mantenimiento

Foto **manual one-off** (decisión cerrada: sin generador automático; si se vuelve
recurrente → tech debt aparte). Si `template.html` cambia de forma **estructural**
(nuevos componentes o cambio de tokens), regenerar contra `main` y actualizar el
`@commit` de arriba. Los cambios de datos (`chore(bcb)`) no afectan al design system.
