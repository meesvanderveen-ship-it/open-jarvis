#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_cost_assumptions import (  # noqa: E402
    build_phase_d6_cost_assumption_catalog,
    build_phase_d6_cost_assumption_report,
    list_cost_scenarios,
    write_cost_assumption_report,
)


def parse_args() -> argparse.Namespace:
    scenario_choices = ["all", *list_cost_scenarios()]
    parser = argparse.ArgumentParser(
        description="D.6 research-only fee/slippage/spread assumption reports. No Coinbase calls."
    )
    parser.add_argument("--scenario", choices=scenario_choices, default="all")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="", help="Optional explicit JSON report output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = (
        build_phase_d6_cost_assumption_catalog()
        if args.scenario == "all"
        else build_phase_d6_cost_assumption_report(scenario_name=args.scenario)
    )
    if args.output:
        write_cost_assumption_report(report, args.output)
    if args.json or not args.output:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
