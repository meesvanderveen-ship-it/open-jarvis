#!/usr/bin/env python3
"""Build the compact, report-only GrowBot/River live-cycle readiness snapshot."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.growbot_river_readiness import build_live_cycle_readiness_report, write_live_cycle_readiness_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the report-only GrowBot/River live-cycle readiness snapshot; no service, profile or exchange action.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    report = build_live_cycle_readiness_report(root=root)
    output = write_live_cycle_readiness_report(report, root=root)
    report["output"] = output
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "growbot_river_live_cycle_readiness "
            f"tuning_phase={report['current_phase']['tuning_phase']} "
            f"stabilization_ready={report['stabilization_readiness'].get('ready')} "
            f"ranked_candidates={len(report['ranked_parameter_candidates'])} "
            f"episodes_needed={report['forward_episode_requirements']['episodes_needed_rollover_model']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
