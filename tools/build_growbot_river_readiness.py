#!/usr/bin/env python3
"""Build the report-only GrowBot/River product-readiness gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.growbot_river_readiness import build_growbot_river_readiness, write_growbot_river_readiness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only GrowBot/River readiness; no service, profile or exchange action.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    report = build_growbot_river_readiness(root=root)
    output = write_growbot_river_readiness(report, root=root)
    report["output"] = output
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "growbot_river_readiness "
            f"report_only_ready={report['readiness']['report_only_ready']} "
            f"stabilization_ready={report['readiness']['stabilization_ready']} "
            f"blockers={len(report['blockers'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
