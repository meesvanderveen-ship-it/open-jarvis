#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_all_ticker_24h_monitor import build_all_ticker_24h_monitor_report, render_all_ticker_24h_monitor_markdown  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Local all-ticker 24h monitor scaffold. No Coinbase calls.")
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--since-utc", default="")
    args = parser.parse_args()
    report = build_all_ticker_24h_monitor_report(root=args.root)
    if args.markdown:
        print(render_all_ticker_24h_monitor_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
