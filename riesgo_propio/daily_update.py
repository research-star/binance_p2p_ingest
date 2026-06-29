#!/usr/bin/env python3
"""
daily_update.py - one-shot daily pipeline for the Bolivia own-math riesgo-pais line.

Run by Windows Task Scheduler once a day. Steps:
  1. live_bolivia.py     -> scrape live venue prices, append today's REAL own-math
                            point to riesgo_propio_live.json (history accrues).
  2. build_historical.py -> regenerate riesgo_propio.json (reconstruction re-anchored
                            to the latest live point + the growing live_points array).
  3. git restore + inject_into_site.py -> re-patch the locally-served dashboard so
                            the new live point shows on the Riesgo Pais chart.

Idempotent and self-contained (absolute paths). No git push.
"""
import os, subprocess, sys

PY = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = r"C:\Users\RodrigoRosasGuzman\finanzasbo_site"

def run(desc, args, cwd=HERE):
    print(f"\n=== {desc} ===")
    r = subprocess.run([PY] + args, cwd=cwd)
    print(f"({desc}) exit {r.returncode}")
    return r.returncode

def main():
    run("record live own-math point", [os.path.join(HERE, "live_bolivia.py")])
    run("rebuild historical series", [os.path.join(HERE, "build_historical.py")])
    # restore a clean served index.html, then re-inject (inject refuses if already patched)
    try:
        subprocess.run(["git", "checkout", "--", "index.html"], cwd=SITE_DIR)
    except FileNotFoundError:
        print("git not on PATH; skipping site re-inject")
        return 0
    run("re-inject dashboard line", [os.path.join(HERE, "inject_into_site.py")])
    print("\ndaily_update complete")
    return 0

if __name__ == "__main__":
    sys.exit(main())
