#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_candidate_coverage_validator import validate_candidate_coverage  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a D.6 candidate candle file covers an exact gap.")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--existing", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--gap-start", type=int, required=True)
    parser.add_argument("--gap-end-exclusive", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_candidate_coverage(
        candidate_path=args.candidate,
        existing_path=args.existing,
        product_id=args.product,
        timeframe=args.timeframe,
        gap_start=args.gap_start,
        gap_end_exclusive=args.gap_end_exclusive,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("validator_pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())
