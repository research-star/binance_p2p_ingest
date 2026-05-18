"""
bbv_ingest.py — Bolsa Boliviana de Valores daily ingest.

Two data sources, combined into a single bbv_data.json:

  1. Boletín diario PDF (rates table by issuer/instrument/term)
     https://www.bbv.com.bo/Media/Default/Home/Resumen.pdf

  2. Instrumentos negociados (static HTML, today's bond movers)
     https://www2.bbv.com.bo/mercados/montos-negociados/instrumentos-negociados/

Output schema (bbv_data.json):
    {
      "date": "YYYY-MM-DD",
      "generated_at": "ISO timestamp",
      "rates":  [{issuer, currency, type, term, rate, scope}, ...],
      "bonds":  {
        "top_gainers": [{code, issuer, price, rate, vpct}, ...],
        "top_losers":  [...],
        "most_traded": [{code, issuer, ops}, ...]
      }
    }

Each source is independent — if one fails, the other still produces data and
the failed key is left as an empty default. dashboard.py reads the JSON and
injects into the dashboard template; the dashboard has a hardcoded
BBV_DATA_FALLBACK so the UI never breaks.

Usage:
    python bbv_ingest.py
    python bbv_ingest.py --pdf bbv_snapshots/2026-05-15.pdf  # offline PDF
    python bbv_ingest.py --skip-pdf                          # only scrape bonds
    python bbv_ingest.py --skip-bonds                        # only parse PDF
    python bbv_ingest.py --debug

Designed to run in GitHub Actions, but works anywhere with python+pdfplumber.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Iterable

try:
    import pdfplumber
except ImportError:
    sys.exit("ERROR: pdfplumber not installed. Run: pip install pdfplumber>=0.10.0")


PDF_URL = "https://www.bbv.com.bo/Media/Default/Home/Resumen.pdf"
BONDS_URL = "https://www2.bbv.com.bo/mercados/montos-negociados/instrumentos-negociados/"

REPO_ROOT = pathlib.Path(__file__).resolve().parent
SNAPSHOTS_DIR = REPO_ROOT / "bbv_snapshots"
OUTPUT_JSON = REPO_ROOT / "bbv_data.json"

UA = "research-bbv-ingest/0.2 (+https://github.com/research-star/binance_p2p_ingest)"

ANNUAL_COLS = ["1-15", "16-30", "31-45", "46-90", "91-135", "136-180",
               "181-270", "271-360", "361-540", "541-720", "721-1080", "1081+"]
REPORTO_COLS = ["1-7", "8-15", "16-22", "23-30", "31-37", "38-45"]

PDF_LABEL_NORM = {
    "1081-MÁS": "1081+", "1081-MAS": "1081+", "1081+": "1081+",
}

CURRENCIES = {"BOB", "USD", "UFV", "DMV"}
TYPES = {"DPF", "LRS", "BBS", "BEC", "BLP", "BRS", "PGB"}

RATE_RE = re.compile(r"^-?\d+(?:\.\d+)?%$")
ISSUER_RE = re.compile(r"^[A-Z]{2,4}$")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ────────────────────────────────────────────────────────────────────────────
# PDF rates parser (from boletin diario)
# ────────────────────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_pdf(dest: pathlib.Path) -> None:
    """Atomic download via temp file."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(_http_get(PDF_URL))
    tmp.replace(dest)
    log(f"  · downloaded {len(dest.read_bytes())} bytes → {dest}")


def _rows_by_y(page, tolerance: int = 3) -> dict[int, list]:
    raw = page.extract_words(use_text_flow=False)
    rows: dict[int, list] = {}
    for w in raw:
        key = int(round(w["top"] / tolerance) * tolerance)
        rows.setdefault(key, []).append(w)
    for k in rows:
        rows[k].sort(key=lambda w: w["x0"])
    return rows


def _find_header_row(rows, required_labels, debug=False):
    for y in sorted(rows.keys()):
        line = " ".join(w["text"] for w in rows[y])
        if all(lbl in line for lbl in required_labels):
            col_x = {}
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


def _col_for_x(x, col_x_sorted, tol=30):
    best, best_dist = None, 1e9
    for label, cx in col_x_sorted:
        d = abs(x - cx)
        if d < best_dist and d < tol:
            best_dist = d
            best = label
    return best


def _parse_section(rows, start_y, end_y, col_x, scope, debug=False):
    col_x_sorted = sorted(col_x.items(), key=lambda kv: kv[1])
    out = []
    current_currency = None
    current_type = None

    for y in sorted(rows.keys()):
        if y <= start_y:
            continue
        if end_y is not None and y >= end_y:
            continue
        words = rows[y]
        labels = [w for w in words if not RATE_RE.match(w["text"])]
        rates = [w for w in words if RATE_RE.match(w["text"])]

        if not rates:
            continue

        ccy = typ = issuer = None
        for lbl in labels:
            t = lbl["text"].strip()
            if t in CURRENCIES and ccy is None:
                ccy = t
            elif t in TYPES and typ is None:
                typ = t
            elif ISSUER_RE.match(t) and issuer is None:
                issuer = t

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
                log(f"  · y={y}: no issuer; tokens={[w['text'] for w in labels]}")
            continue

        for r in rates:
            term = _col_for_x(r["x0"], col_x_sorted)
            if not term:
                if debug:
                    log(f"  · y={y}: rate {r['text']} at x={r['x0']:.1f} no col match")
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


def parse_pdf_rates(pdf_path: pathlib.Path, debug: bool = False) -> list[dict]:
    """Parse the Tasas de Rendimiento section from page 1."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        rows = _rows_by_y(page)

    if not rows:
        log("WARN: no words extracted from page 1")
        return []

    annual_header = _find_header_row(rows, ["1-15", "16-30"], debug=debug)
    if not annual_header:
        log("WARN: annual rates header not found")
        return []
    annual_y, annual_col_x = annual_header

    reporto_header = _find_header_row(rows, ["1-7", "8-15"], debug=debug)
    reporto_y, reporto_col_x = (reporto_header if reporto_header else (None, {}))

    end_annual = reporto_y
    annual_rates = _parse_section(rows, annual_y, end_annual, annual_col_x, "yield", debug=debug)
    reporto_rates = []
    if reporto_y is not None:
        reporto_rates = _parse_section(rows, reporto_y, None, reporto_col_x, "reporto", debug=debug)

    log(f"  · parsed rates: yield={len(annual_rates)} reporto={len(reporto_rates)}")
    return annual_rates + reporto_rates


def parse_pdf_date(pdf_path: pathlib.Path) -> str | None:
    """Extract YYYY-MM-DD from the PDF's date header (e.g., '15/05/2026')."""
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


# ────────────────────────────────────────────────────────────────────────────
# Bonds HTML scraper (from /instrumentos-negociados/)
# ────────────────────────────────────────────────────────────────────────────

# Each bond row is: CODE ISSUER (multi-word) NUMBER NUMBER NUMBER  (for movers)
# Or:              CODE ISSUER (multi-word) NUMBER                  (for traded)
# The issuer name is a known string, so we anchor on a list of known issuer names.

# Issuer names that appear in the bonds page. Map: substring → ticker.
# When we see one of these substrings in the HTML text, we know that's the issuer.
ISSUER_PATTERNS = [
    ("Banco Nacional de Bolivia S.A.",    "BNB"),
    ("Banco Económico S.A.",              "BEC"),
    ("Mercantil Santa Cruz S.A.",         "BME"),
    ("Banco PyME Ecofuturo S.A.",         "FEF"),
    ("BANCO CENTRAL DE BOLIVIA",          "BCB"),
    ("PROLEGA S.A.",                      "POL"),
    ("San Lucas S.A.",                    "MSL"),
    ("Nutrioil S.A.",                     "NUT"),
    ("Industrias de Aceite S.A.",         "FIN"),
    ("Gravetal Bolivia S.A.",             "GRB"),
    ("Industrias Oleaginosas S.A.",       "IOL"),
    ("YPFB Andina S.A.",                  "EPA"),
    ("YPFB Chaco S.A.",                   "PCH"),
    ("YPFB Transporte S.A.",              "TRD"),
    ("Ingenio Sucroalcoholero Aguaí S.A.", "AGU"),
    ("FANCESA",                           "FAN"),
    ("SOBOCE S.A.",                       "SBC"),
    ("ITACAMBA CEMENTO S.A.",             "ITA"),
    ("ENDE Corani S.A.",                  "COR"),
    ("DELAPAZ S.A.",                      "ELP"),
    ("ELFEC S.A.",                        "ELF"),
    ("Sociedad Hotelera",                 "HLT"),
    ("Clínica Metropolitana",             "CTM"),
    ("BNB Leasing S.A.",                  "BNL"),
    ("BISA Leasing S.A.",                 "BIL"),
    ("Tigre S.A.",                        "PLR"),
    ("TOYOSA S.A.",                       "TYS"),
    ("Industria Textil TSM S.A.",         "TSM"),
    ("Ferroviaria Oriental S.A.",         "EFO"),
    ("Ferroviaria Andina S.A.",           "FCA"),
    ("Bodegas y Viñedos",                 "BVC"),
    ("Telecel S.A.",                      "TCB"),
]

# Sentinel strings that delimit the three tables in the page text.
T_GAINERS_START = "presentan las mayores variaciones positivas"
T_LOSERS_START  = "presentan las mayores variaciones negativas"
T_TRADED_START  = "con mayor cantidad de negociaciones"
T_END_MARKER    = "Nota:"  # text right after the last table

ROW_HEADER_MOVERS = "CLAVE DE PIZARRA NOMBRE CORTO EMISOR PRECIO %TASA %VAR"
ROW_HEADER_TRADED = "CLAVE DE PIZARRA NOMBRE CORTO EMISOR NÚMERO DE OPERACIONES"


def _strip_html(html: str) -> str:
    """Remove scripts/styles/tags, collapse whitespace."""
    html = re.sub(r'<script[\s\S]*?</script>', ' ', html)
    html = re.sub(r'<style[\s\S]*?</style>', ' ', html)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'\s+', ' ', html)
    return html.strip()


def _slice_between(text: str, start: str, end_candidates: list[str]) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    i = text.find(".", i)  # skip to end of opening sentence
    if i < 0:
        return ""
    j = len(text)
    for end in end_candidates:
        k = text.find(end, i)
        if 0 < k < j:
            j = k
    return text[i:j].strip()


def _find_issuer_in_chunk(chunk: str) -> tuple[str, str, int]:
    """Find the longest issuer-name substring that's at the START of chunk.
    Returns (issuer_ticker, issuer_display_name, length_consumed).
    If no known issuer matches, returns ("", "", 0).
    """
    best = ("", "", 0)
    for name, ticker in ISSUER_PATTERNS:
        if chunk.startswith(name) and len(name) > best[2]:
            best = (ticker, name, len(name))
    return best


_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?")


def _parse_number(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None


def parse_bonds(html: str, debug: bool = False) -> dict:
    """Parse the 3 tables (gainers, losers, most_traded) from instrumentos page HTML."""
    text = _strip_html(html)

    gainers_chunk = _slice_between(text, T_GAINERS_START, [T_LOSERS_START, T_TRADED_START, T_END_MARKER])
    losers_chunk  = _slice_between(text, T_LOSERS_START,  [T_TRADED_START, T_END_MARKER])
    traded_chunk  = _slice_between(text, T_TRADED_START,  [T_END_MARKER])

    def parse_movers_chunk(chunk: str, label: str) -> list[dict]:
        # Strip the table header if present
        for hdr in [ROW_HEADER_MOVERS, "CLAVE DE PIZARRA NOMBRE CORTO EMISOR PRECIO %TASA %VAR"]:
            chunk = chunk.replace(hdr, "")
        chunk = chunk.strip(". ").strip()
        # Each row pattern: CODE [issuer name] PRICE RATE VAR
        rows = []
        # Tokenize: split by whitespace, scan as state machine
        tokens = chunk.split(" ")
        i = 0
        while i < len(tokens):
            code = tokens[i]
            # Skip if not a plausible bond code (alphanumeric, contains digits or dashes)
            if not re.match(r"^[A-Z0-9\-]{5,}$", code):
                i += 1
                continue
            # Try to consume an issuer name starting from i+1
            rest = " ".join(tokens[i+1:])
            ticker, name, consumed = _find_issuer_in_chunk(rest)
            if not ticker:
                if debug:
                    log(f"  · no issuer match after code={code}, rest starts: {rest[:60]!r}")
                i += 1
                continue
            # Now consume the 3 numbers (price, rate, var) after the issuer name
            after_name = rest[consumed:].strip()
            nums = _NUM_RE.findall(after_name)
            if len(nums) < 3:
                if debug:
                    log(f"  · code={code} issuer={ticker} only {len(nums)} nums in {after_name[:60]!r}")
                i += 1
                continue
            price = _parse_number(nums[0])
            rate  = _parse_number(nums[1])
            vpct  = _parse_number(nums[2])
            if price is None or rate is None or vpct is None:
                i += 1
                continue
            rows.append({"code": code, "issuer": ticker, "price": price, "rate": rate, "vpct": vpct})
            # Advance i past code + issuer-name tokens + 3 number tokens
            name_token_count = len(name.split(" "))
            i += 1 + name_token_count + 3
        log(f"  · {label}: parsed {len(rows)} bonds")
        return rows

    def parse_traded_chunk(chunk: str) -> list[dict]:
        for hdr in [ROW_HEADER_TRADED, "CLAVE DE PIZARRA NOMBRE CORTO EMISOR NÚMERO DE OPERACIONES"]:
            chunk = chunk.replace(hdr, "")
        chunk = chunk.strip(". ").strip()
        rows = []
        tokens = chunk.split(" ")
        i = 0
        while i < len(tokens):
            code = tokens[i]
            if not re.match(r"^[A-Z0-9\-]{5,}$", code):
                i += 1
                continue
            rest = " ".join(tokens[i+1:])
            ticker, name, consumed = _find_issuer_in_chunk(rest)
            if not ticker:
                i += 1
                continue
            after_name = rest[consumed:].strip()
            m = re.match(r"^\s*(\d+)", after_name)
            if not m:
                i += 1
                continue
            ops = int(m.group(1))
            rows.append({"code": code, "issuer": ticker, "ops": ops})
            name_token_count = len(name.split(" "))
            i += 1 + name_token_count + 1
        log(f"  · most_traded: parsed {len(rows)} bonds")
        return rows

    return {
        "top_gainers": parse_movers_chunk(gainers_chunk, "top_gainers") if gainers_chunk else [],
        "top_losers":  parse_movers_chunk(losers_chunk,  "top_losers")  if losers_chunk  else [],
        "most_traded": parse_traded_chunk(traded_chunk)                  if traded_chunk  else [],
    }


def fetch_bonds(debug: bool = False) -> dict:
    log(f"· fetching {BONDS_URL}")
    html = _http_get(BONDS_URL, timeout=30).decode("utf-8", errors="replace")
    return parse_bonds(html, debug=debug)


# ────────────────────────────────────────────────────────────────────────────
# Orchestration
# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="BBV daily ingest (PDF rates + bonds HTML)")
    ap.add_argument("--pdf", type=pathlib.Path, help="Use a local PDF instead of downloading")
    ap.add_argument("--skip-pdf",   action="store_true", help="Skip PDF rates parsing")
    ap.add_argument("--skip-bonds", action="store_true", help="Skip bonds HTML scrape")
    ap.add_argument("--debug",      action="store_true", help="Extra logging")
    ap.add_argument("--output",     type=pathlib.Path, default=OUTPUT_JSON, help="Output JSON path")
    args = ap.parse_args()

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    rates: list[dict] = []
    bonds: dict = {"top_gainers": [], "top_losers": [], "most_traded": []}
    date_str: str | None = None

    # ── PDF rates ──
    if not args.skip_pdf:
        try:
            if args.pdf:
                pdf_path = args.pdf
                log(f"· using local PDF: {pdf_path}")
            else:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                pdf_path = SNAPSHOTS_DIR / f"{today}.pdf"
                log(f"· downloading {PDF_URL}")
                download_pdf(pdf_path)
            date_str = parse_pdf_date(pdf_path)
            log(f"· PDF report date: {date_str}")
            rates = parse_pdf_rates(pdf_path, debug=args.debug)
        except Exception as e:
            log(f"ERROR parsing PDF: {e}")
            if args.debug:
                import traceback
                traceback.print_exc(file=sys.stderr)

    # ── Bonds HTML ──
    if not args.skip_bonds:
        try:
            bonds = fetch_bonds(debug=args.debug)
        except Exception as e:
            log(f"ERROR fetching bonds: {e}")
            if args.debug:
                import traceback
                traceback.print_exc(file=sys.stderr)

    out = {
        "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "rates": rates,
        "bonds": bonds,
    }
    args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"· wrote {args.output} (rates={len(rates)}, "
        f"gainers={len(bonds['top_gainers'])}, losers={len(bonds['top_losers'])}, "
        f"traded={len(bonds['most_traded'])})")

    # Non-zero exit if BOTH sources produced no data
    if not rates and not any(bonds.values()):
        log("WARN: both rates and bonds empty — check selectors/format changes")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
