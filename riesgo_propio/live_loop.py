#!/usr/bin/env python3
"""
live_loop.py - capture the live Bolivia own-math number every INTERVAL seconds,
appending a timestamped point so the dashboard's intraday line densifies.

Each tick runs live_bolivia.main() (scrape -> compute -> append to the store, which
is mirrored into the served site so the chart self-refreshes). Errors are logged
and the loop continues. Stop with Ctrl+C or by killing the process.
"""
import os, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import live_bolivia  # noqa: E402

INTERVAL = int(os.environ.get("RIESGO_LIVE_INTERVAL_S", "60"))

def main():
    print(f"live loop start; interval {INTERVAL}s")
    while True:
        t0 = time.monotonic()
        try:
            live_bolivia.main()
        except Exception:
            traceback.print_exc()
        time.sleep(max(2.0, INTERVAL - (time.monotonic() - t0)))

if __name__ == "__main__":
    main()
