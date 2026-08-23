#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.reflection_learning_context import build_reflection_learning_report, parse_time, write_report_outputs


def _windows(value: str) -> list[int]:
    return [int(part) for part in str(value).split(",") if part.strip().isdigit()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only reflection learning report.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--windows-hours", default="")
    parser.add_argument("--json-out")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--min-net-opportunity-pct", type=float)
    parser.add_argument("--max-acceptable-mae-pct", type=float)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_reflection_learning_report(
        root=Path(args.root),
        since=parse_time(args.since),
        until=parse_time(args.until),
        windows_hours=_windows(args.windows_hours) if args.windows_hours else None,
        no_network=True if args.no_network or args.fixture_only else True,
        fixture_only=args.fixture_only,
        min_net_opportunity_pct=args.min_net_opportunity_pct,
        max_acceptable_mae_pct=args.max_acceptable_mae_pct,
    )
    outputs = write_report_outputs(report, root=Path(args.root), json_out=Path(args.json_out) if args.json_out else None)
    report["outputs"] = outputs
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"reflection_learning available={report.get('available')} recommendation={(report.get('proposal') or {}).get('recommendation')} json={outputs['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
