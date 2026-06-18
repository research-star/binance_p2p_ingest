# STATUS — design-system/ (staleness)

> ⚠️ **NO usar como canon ni como fuente del sync hasta regenerar contra `main`.**

## Estado real

`design-reference.html`, `template.snapshot.html` y `DESIGN-SYSTEM.md` reflejan el
estado **PRE navbar v3**. El **navbar v3 está MERGEADO en `main`** (PR #77).

## Drift conocido (galería/snapshot vs `template.html` de main)

- **Estructural:** faltan los componentes del navbar v3 — `.fb-utility`,
  `.fb-masthead`, `.fb-nameplate`, `.fb-search`.
- **Token:** `THEMES.paper.bg-primary` `#f5f7fa` → `#fafbfe`.
- **Fuentes:** faltan pesos de Inter `600;700`.

## Pendiente

Regeneración de la galería contra `main` = **ticket aparte** (pendiente).
