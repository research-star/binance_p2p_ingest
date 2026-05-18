"""
bbv_ingest.py — Bolsa Boliviana de Valores daily ingest.

Downloads the daily resume PDF, parses the 'Tasas de Rendimiento' section
on page 1, and writes structured data to bbv_data.json.

Usage:
    python bbv_ingest.py
    python bbv_ingest.py --pdf bbv_snapshots/2026-05-15.pdf  # parse a local PDF
    python bbv_ingest.py --debug                              # extra logging

On VPS, schedule via cron:
    30 17 * * 1-5 cd /opt/binance_p2p && .venv/bin/python bbv_ingest.py
"""
from __future__ import annotations
import argparse
import json
import pathlib
import re
import sys
import urllib.request
from datetime import datetime

try:
    import pdfplumber
except ImportError:
    sys.exit("ERROR: pdfplumber not installed. Run: pip install pdfplumber>=0.10.0")


PDF_URL = "https://www.bbv.com.bo/Media/Default/Home/Resumen.pdf"
REPO_ROOT = pathlib.Path(__file__).resolve().parent
SNAPSHOTS_DIR = REPO_ROOT / "bbv_snapshots"
OUTPUT_JSON = REPO_ROOT / "bbv_data.json"

# Normalized column labels we'll emit in the output JSON.
ANNUAL_COLS = ["1-15", "16-30", "31-45", "46-90", "91-135", "136-180",
               "181-270", "271-360", "361-540", "541-720", "721-1080", "1081+"]
REPORTO_COLS = ["1-7", "8-15", "16-22", "23-30", "31-37", "38-45"]

# In the PDF the "1081-MÁS" column may render with or without accent.
PDF_LABEL_NORM = {
    "1081-MÁS": "1081+", "1081-MAS": "1081+", "1081+": "1081+",
}

# Known token categories. Extend as we see more.
CURRENCIES = {"BOB", "USD", "UFV", "DMV"}
TYPES = {"DPF", "LRS", "BBS", "BEC", "BLP", "BRS", "PGB"}

RATE_RE = re.compile(r"^-?\d+(?:\.\d+)?%$")
ISSUER_RE = re.compile(r"^[A-Z]{2,4}$")


def log(msg: str, *, debug: bool = False) -> None:
    """Log to stderr. debug=True only emits when debug mode on (handled by caller)."""
    print(msg, file=sys.stderr)


def download_pdf(dest: pathlib.Path, url: str = PDF_URL) -> None:
    """Download the PDF with atomic write via tmp file."""
    req = urllib.request.Request(url, headers={"User-Agent": "research-bbv-ingest/0.1"})
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(req, timeout=30) as resp:
        tmp.write_bytes(resp.read())
    tmp.replace(dest)
    log(f"  · downloaded {len(dest.read_bytes())} bytes → {dest}")


def _rows_by_y(page, tolerance: int = 3) -> dict[int, list]:
    """Group words by approximate y-position (row).

    PDF text doesn't preserve exact alignment, so we bucket by rounded top.
    Tolerance handles minor font-baseline variations within the same visual row.
    """
    raw = page.extract_words(use_text_flow=False)
    rows: dict[int, list] = {}
    for w in raw:
        # Bucket by integer top rounded to tolerance
        key = int(round(w["top"] / tolerance) * tolerance)
        rows.setdefault(key, []).append(w)
    # Sort each row's words left-to-right
    for k in rows:
        rows[k].sort(key=lambda w: w["x0"])
    return rows


def _find_header_row(
    rows: dict, required_labels: list[str], debug: bool = False
) -> tuple[int, dict[str, float]] | None:
    """Find a row containing all required column headers. Return (y, {label: x0})."""
    for y in sorted(rows.keys()):
        line = " ".join(w["text"] for w in rows[y])
        if all(lbl in line for lbl in required_labels):
            col_x: dict[str, float] = {}
            for w in rows[y]:
                txt = w["text"].strip()
                norm = PDF_LABEL_NORM.get(txt, txt)
                if norm in ANNUAL_COLS or norm in REPORTO_COLS:
                    col_x[norm] = w["x0"]
            if col_x:
                if debug:
                    log(f"  · header at y={y}: {col_x}")
                return y, col_x
    return None


def _col_for_x(x: float, col_x_sorted: list[tuple[str, float]], tol: float = 30) -> str | None:
    """Find the column header closest to x, within tolerance."""
    best, best_dist = None, 1e9
    for label, cx in col_x_sorted:
        d = abs(x - cx)
        if d < best_dist and d < tol:
            best_dist = d
            best = label
    return best


def _parse_section(
    rows: dict,
    start_y: int,
    end_y: int | None,
    col_x: dict[str, float],
    scope: str,
    debug: bool = False,
) -> list[dict]:
    """Parse rate rows in [start_y, end_y) using col_x as column → x0 map."""
    col_x_sorted = sorted(col_x.items(), key=lambda kv: kv[1])
    out: list[dict] = []
    current_currency: str | None = None
    current_type: str | None = None

    for y in sorted(rows.keys()):
        if y <= start_y:
            continue
        if end_y is not None and y >= end_y:
            continue
        words = rows[y]
        labels = [w for w in words if not RATE_RE.match(w["text"])]
        rates = [w for w in words if RATE_RE.match(w["text"])]

        if not rates:
            continue  # Skip rows without any rate (headers, notes, blank)

        # Identify (currency, type, issuer) from non-rate tokens.
        ccy: str | None = None
        typ: str | None = None
        issuer: str | None = None
        for lbl in labels:
            t = lbl["text"].strip()
            if t in CURRENCIES and ccy is None:
                ccy = t
            elif t in TYPES and typ is None:
                typ = t
            elif ISSUER_RE.match(t) and issuer is None:
                issuer = t
        # Carry over currency/type from previous row if missing (grouped layout).
        if ccy is None:
            ccy = current_currency
        if typ is None:
            typ = current_type
        if ccy:
            current_currency = ccy
        if typ:
            current_type = typ

        if not issuer:
            if debug:
                log(f"  · y={y}: no issuer found in {[w['text'] for w in labels]}")
            continue

        for r in rates:
            term = _col_for_x(r["x0"], col_x_sorted)
            if not term:
                if debug:
                    log(f"  · y={y}: rate {r['text']} at x={r['x0']:.1f} matched no column")
                continue
            try:
                rate_val = float(r["text"].rstrip("%"))
            except ValueError:
                continue
            out.append({
                "issuer": issuer,
                "currency": ccy or "?",
                "type": typ or "?",
                "term": term,
                "rate": rate_val,
                "scope": scope,
            })
    return out


def parse_pdf(pdf_path: pathlib.Path, debug: bool = False) -> list[dict]:
    """Parse page 1 of the BBV daily PDF into structured rate rows."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        rows = _rows_by_y(page)

    if not rows:
        log("WARN: no words extracted from page 1")
        return []

    annual_header = _find_header_row(rows, ["1-15", "16-30"], debug=debug)
    if not annual_header:
        log("WARN: annual rates header not found (looking for columns '1-15' and '16-30')")
        return []
    annual_y, annual_col_x = annual_header

    reporto_header = _find_header_row(rows, ["1-7", "8-15"], debug=debug)
    reporto_y, reporto_col_x = (reporto_header if reporto_header else (None, {}))

    end_annual = reporto_y if reporto_y is not None else None
    annual_rates = _parse_section(rows, annual_y, end_annual, annual_col_x, "yield", debug=debug)
    reporto_rates: list[dict] = []
    if reporto_y is not None:
        reporto_rates = _parse_section(rows, reporto_y, None, reporto_col_x, "reporto", debug=debug)

    log(f"  · parsed: yield={len(annual_rates)} reporto={len(reporto_rates)}")
    return annual_rates + reporto_rates


def parse_date(pdf_path: pathlib.Path) -> str | None:
    """Extract YYYY-MM-DD from the PDF's date header (e.g., '15/05/2026')."""
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


def main() -> int:
    ap = argparse.ArgumentParser(description="BBV daily ingest")
    ap.add_argument("--pdf", type=pathlib.Path,
                    help="Use a local PDF instead of downloading from BBV")
    ap.add_argument("--debug", action="store_true",
                    help="Extra logging of parse steps")
    args = ap.parse_args()

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.pdf:
        pdf_path = args.pdf
        log(f"· using local PDF: {pdf_path}")
    else:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        pdf_path = SNAPSHOTS_DIR / f"{today}.pdf"
        log(f"· downloading {PDF_URL} → {pdf_path}")
        download_pdf(pdf_path)

    date_str = parse_date(pdf_path) or pdf_path.stem
    log(f"· report date: {date_str}")

    rates = parse_pdf(pdf_path, debug=args.debug)

    data = {"date": date_str, "rates": rates, "generated_at": datetime.utcnow().isoformat() + "Z"}
    OUTPUT_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    log(f"· wrote {OUTPUT_JSON} ({len(rates)} rates)")

    if args.debug and rates:
        log("· first 10 rates:")
        for r in rates[:10]:
            log(f"    {r}")

    if not rates:
        log("WARN: no rates parsed. Re-run with --debug for diagnostics.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
