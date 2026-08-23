#!/usr/bin/env python3
"""Inventory historical logs/reports for GrowBot/River replay viability.

Report-only: writes reports/growbot_river/historical-source-audit-latest.{json,md}.
Never mutates any forward ledger, log or production River state.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.growbot_historical_replay import audit_historical_sources, write_source_audit_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit historical GrowBot/River source viability.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--max-per-source", type=int, default=1500)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    report = audit_historical_sources(root, max_per_source=max(1, args.max_per_source))
    outputs = write_source_audit_report(report, root=root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            "historical_source_audit "
            f"usable={summary['usable_for_historical_replay']} "
            f"no_gap={summary['no_gap_already_covered']} "
            f"skipped={len(summary['skipped_not_episode_shaped_or_empty'])} "
            f"-> {outputs['json']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
