# STATUS — design-system/

> ⚠️ **Parcialmente stale tras el reskin editorial cálido (#81/#83).** `DESIGN-SYSTEM.md`
> (el spec en markdown) está **sincronizado a la paleta CÁLIDA vigente** (tema único `paper`).
> Los snapshots HTML (`design-reference.html`, `template.snapshot.html`) siguen **congelados
> en navbar v3 (paleta FRÍA) @ `b787584`** y quedan **pendientes de regenerar** contra `main`.

## Provenance

- **`design-reference.html`**: CSS (`<style>`) + objeto `THEMES` copiados **verbatim**
  de `template.html`, pero **congelado en navbar v3 (paleta FRÍA `#fafbfe` / `#2c4a6b`,
  Outfit)** — anterior al reskin cálido. **Stale: pendiente de regenerar** contra `main`.
- **`template.snapshot.html`**: copia fiel de `template.html` **al estado navbar v3**
  (4983 líneas). **Stale** por la misma razón — pendiente de regenerar.
- **`DESIGN-SYSTEM.md`**: ✅ **sincronizado a la paleta CÁLIDA vigente**
  (`--bg-primary:#FBEDE3`, `--text-primary:#211E1B`, `--text-secondary:#6B6256`, tema único
  `paper`, tipografía Newsreader/Inter/IBM Plex Mono) y catálogo con refs de línea al
  template actual.

## Mantenimiento

Foto **manual one-off** (decisión cerrada: sin generador automático; si se vuelve
recurrente → tech debt aparte). Si `template.html` cambia de forma **estructural**
(nuevos componentes o cambio de tokens), regenerar contra `main` y actualizar el
`@commit` de arriba. Los cambios de datos (`chore(bcb)`) no afectan al design system.
