"""Tab Galería (FASE C-3): inverse view of the REAL gallery routing.

For each slug/webp that exists, shows which KEYWORDS (GALLERY_KEYWORD_PRIORITY) and which
TEMAS (GALLERY_TEMA_SLUGS) route a note to it — read LIVE from dashboard.py so it auto-syncs
with prod. The inspector never re-derives the routing; it reflects the config.
"""
from __future__ import annotations

import insp_config as cfg  # noqa: F401  (sys.path -> repo root)
import dashboard


def inverse() -> dict:
    gkp = list(getattr(dashboard, "GALLERY_KEYWORD_PRIORITY", []))   # [(keywords[], slug), ...] ordered
    tema_slugs = dict(getattr(dashboard, "GALLERY_TEMA_SLUGS", {}))  # tema -> slug
    valid = set(getattr(dashboard, "VALID_GALLERY_SLUGS", set()))

    webp_present = {p.name[len("gal-"):-len(".webp")] for p in cfg.GALLERY_DIR.glob("gal-*.webp")}
    slugs = sorted(valid | webp_present)

    rows = []
    for slug in slugs:
        keyword_rules = [{"priority": i, "keywords": list(kws)}
                         for i, (kws, s) in enumerate(gkp) if s == slug]
        temas = sorted(t for t, sv in tema_slugs.items() if sv == slug)
        webp = f"gal-{slug}.webp"
        rows.append({
            "slug": slug,
            "webp": webp,
            "exists": slug in webp_present,
            "valid": slug in valid,
            "keyword_rules": keyword_rules,
            "temas": temas,
        })
    return {
        "slugs": rows,
        "n_keyword_rules": len(gkp),
        "n_temas": len(tema_slugs),
        "n_valid_slugs": len(valid),
        "n_webp_present": len(webp_present),
        "gallery_dir": str(cfg.GALLERY_DIR),
        "orphans": sorted(webp_present - valid),       # webp without a valid-slug entry
        "missing_webp": sorted(valid - webp_present),  # valid slug without a webp file
    }
