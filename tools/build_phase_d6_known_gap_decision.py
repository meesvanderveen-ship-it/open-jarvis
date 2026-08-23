#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_known_gap_decision_tool import build_known_gap_decision  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build D.6 known-gap decision report.")
    parser.add_argument("--chunk-id", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--existing", required=True)
    parser.add_argument("--failed-candidate", required=True)
    parser.add_argument("--adjusted-result", default="")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = build_known_gap_decision(chunk_id=args.chunk_id, expected_start=args.start, expected_end_exclusive=args.end, existing_path=args.existing, failed_candidate_path=args.failed_candidate, adjusted_result_path=args.adjusted_result or None)
    bundle = build_phase_d6_report_bundle(report_type="chunk52_known_gap_decision_v1", content=report, source_paths=[args.existing, args.failed_candidate, args.adjusted_result] if args.adjusted_result else [args.existing, args.failed_candidate])
    write_phase_d6_report_bundle(bundle, args.report, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, Path(args.report).with_suffix(".md"), markdown=True)
    print(json.dumps({"status": report["status"], "classification": report["classification"], "report": args.report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
