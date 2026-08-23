#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_known_gap_policy_review import build_known_gap_policy_review  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build D.6 known-gap policy review.")
    parser.add_argument("--decision", required=True)
    parser.add_argument("--existing-cache", required=True)
    parser.add_argument("--failed-candidate", required=True)
    parser.add_argument("--adjusted-result", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = build_known_gap_policy_review(decision_report_path=args.decision, existing_cache_path=args.existing_cache, failed_candidate_path=args.failed_candidate, adjusted_result_path=args.adjusted_result)
    bundle = build_phase_d6_report_bundle(report_type="chunk52_known_gap_policy_review_v1", content=report, source_paths=[args.decision, args.existing_cache, args.failed_candidate, args.adjusted_result])
    write_phase_d6_report_bundle(bundle, args.report, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, Path(args.report).with_suffix(".md"), markdown=True)
    print(json.dumps({"status": report["status"], "classification": report["classification"], "allows_chunk53_continuation": report["policy_decision"]["allows_chunk53_continuation"], "report": args.report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
