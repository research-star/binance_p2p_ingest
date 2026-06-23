"""Startup dependency check for the Noticias Inspector.

The inspector imports the REAL criterion code (scraper.py / ingest_noticias.py /
transform.py / dashboard.py), which pulls heavy deps. We check them at startup and
report what's missing instead of crashing (acceptance #7). The frontend surfaces this
banner so Diego knows the tool is running degraded (e.g. no trafilatura -> no cuerpos
ni og:image; no sklearn -> scoring cae a keywords/degradado, igual que prod).
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field


# (import_name, pip_name, tier, why-it-matters)
#   tier "fetch"    -> needed to fetch/parse real candidates (bodies, og:image)
#   tier "tool"     -> needed for the inspector server itself (Flask + cron)
#   tier "scoring"  -> optional: present -> TF-IDF scoring; absent -> degraded keywords
_REQUIRED = [
    ("trafilatura", "trafilatura", "fetch", "extrae el CUERPO del artículo; sin esto no hay detail ni og:image"),
    ("feedparser", "feedparser", "fetch", "parsea los RSS (Google News + portales)"),
    ("bs4", "beautifulsoup4", "fetch", "parsing HTML auxiliar"),
    ("rapidfuzz", "rapidfuzz", "fetch", "similitud fuzzy para dedupe inter-día y por evento"),
    ("cloudscraper", "cloudscraper", "fetch", "fetch tolerante a anti-bot en algunos portales"),
    ("curl_cffi", "curl_cffi", "fetch", "fetch con fingerprint TLS para portales quisquillosos"),
    ("googlenewsdecoder", "googlenewsdecoder", "fetch", "decodifica las URLs de Google News a la real"),
    ("flask", "flask", "tool", "sirve el HTML + la API del inspector"),
    ("apscheduler", "apscheduler", "tool", "cron horario in-process (start/stop/run-now)"),
    ("sklearn", "scikit-learn", "scoring", "carga modelo_relevancia.pkl (TF-IDF); ausente -> scoring degradado por keywords"),
]


@dataclass
class DepReport:
    present: list[str] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)

    @property
    def ok_to_run(self) -> bool:
        """Tool can boot as long as Flask is importable. Everything else degrades."""
        return not any(m["import"] == "flask" for m in self.missing)

    @property
    def fetch_ok(self) -> bool:
        return not any(m["tier"] == "fetch" for m in self.missing)

    def as_dict(self) -> dict:
        return {
            "present": self.present,
            "missing": self.missing,
            "ok_to_run": self.ok_to_run,
            "fetch_ok": self.fetch_ok,
        }


def check() -> DepReport:
    rep = DepReport()
    for imp, pip_name, tier, why in _REQUIRED:
        try:
            importlib.import_module(imp)
            rep.present.append(imp)
        except Exception as exc:  # ModuleNotFoundError or a broken transitive import
            rep.missing.append(
                {"import": imp, "pip": pip_name, "tier": tier, "why": why, "error": f"{type(exc).__name__}: {exc}"}
            )
    return rep


def banner(rep: DepReport) -> str:
    if not rep.missing:
        return "deps OK — todas las dependencias presentes."
    lines = ["⚠ Dependencias faltantes (la tool corre degradada, no crashea):"]
    for m in rep.missing:
        lines.append(f"  [{m['tier']}] {m['import']} (pip install {m['pip']}) — {m['why']}")
    return "\n".join(lines)


if __name__ == "__main__":
    r = check()
    print(banner(r))
    print(f"\nok_to_run={r.ok_to_run}  fetch_ok={r.fetch_ok}")
