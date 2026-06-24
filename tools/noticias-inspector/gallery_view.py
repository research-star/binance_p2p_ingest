"""Tab Galería (FASE C-3): inverse view of the REAL gallery routing.

For each slug/webp that exists, shows which KEYWORDS (GALLERY_KEYWORD_PRIORITY) and which
TEMAS (GALLERY_TEMA_SLUGS) route a note to it — read LIVE from dashboard.py so it auto-syncs
with prod. The inspector never re-derives the routing; it reflects the config.
"""
from __future__ import annotations

import insp_config as cfg  # noqa: F401  (sys.path -> repo root)
import dashboard


def _parse_webp(name: str):
    """'gal-banco-central-2.webp' -> ('banco-central', 2); 'gal-litio.webp' -> ('litio', None)."""
    stem = name[len("gal-"):-len(".webp")]
    base, sep, k = stem.rpartition("-")
    if sep and k.isdigit():
        return base, int(k)
    return stem, None


def inverse() -> dict:
    gkp = list(getattr(dashboard, "GALLERY_KEYWORD_PRIORITY", []))   # [(keywords[], slug), ...] ordered
    tema_slugs = dict(getattr(dashboard, "GALLERY_TEMA_SLUGS", {}))  # tema -> slug
    valid = set(getattr(dashboard, "VALID_GALLERY_SLUGS", set()))
    sets = dict(getattr(dashboard, "GALLERY_SETS", {}))              # slug -> nº de imágenes (v2)

    # Galería v2: cada slug tiene un SET gal-<slug>-<k>.webp. Agrupar por slug base.
    present = {}  # slug -> [(k, filename), ...] ordenado
    for p in cfg.GALLERY_DIR.glob("gal-*.webp"):
        base, k = _parse_webp(p.name)
        present.setdefault(base, []).append((k if k is not None else 0, p.name))
    for b in present:
        present[b].sort()

    slugs = sorted(valid | set(present) | set(sets))
    rows = []
    for slug in slugs:
        keyword_rules = [{"priority": i, "keywords": list(kws)}
                         for i, (kws, s) in enumerate(gkp) if s == slug]
        temas = sorted(t for t, sv in tema_slugs.items() if sv == slug)
        imgs = [{"k": k, "file": f} for (k, f) in present.get(slug, [])]
        rows.append({
            "slug": slug,
            "set_count": sets.get(slug, 0),          # cuántas espera dashboard.GALLERY_SETS
            "n_images": len(imgs),                   # cuántas hay en disco
            "images": imgs,                          # el set rotativo [{k, file}, ...]
            "webp": imgs[0]["file"] if imgs else f"gal-{slug}.webp",  # representativa (compat)
            "exists": bool(imgs),
            "valid": slug in valid,
            "keyword_rules": keyword_rules,
            "temas": temas,
        })
    return {
        "slugs": rows,
        "n_keyword_rules": len(gkp),
        "n_temas": len(tema_slugs),
        "n_valid_slugs": len(valid),
        "n_webp_present": sum(len(v) for v in present.values()),
        "gallery_dir": str(cfg.GALLERY_DIR),
        "orphans": sorted(set(present) - valid),                  # webp sin slug válido
        "missing_webp": sorted(s for s in sets if sets[s] > len(present.get(s, []))),  # set incompleto
    }
