#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_historical_gap_validator import validate_historical_gap  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate D.6 historical candle gaps.")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--existing", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = validate_historical_gap(candidate_path=args.candidate, existing_path=args.existing, product_id=args.product, timeframe=args.timeframe, expected_start=args.start, expected_end_exclusive=args.end)
    bundle = build_phase_d6_report_bundle(report_type="historical_gap_validator_v1", content=report, source_paths=[args.candidate, args.existing])
    write_phase_d6_report_bundle(bundle, args.report, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, Path(args.report).with_suffix(".md"), markdown=True)
    print(json.dumps({"status": report["status"], "blocks_merge": report["blocks_merge"], "report": args.report}, indent=2))
    return 1 if report["blocks_merge"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
