#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_dataset_quality_known_gap_semantics import build_dataset_quality_known_gap_semantics  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build D.6 dataset-quality known-gap semantics.")
    parser.add_argument("--policy-review", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    loaded = json.loads(Path(args.policy_review).read_text(encoding="utf-8"))
    policy = dict(loaded.get("content") or loaded)
    report = build_dataset_quality_known_gap_semantics(policy_review=policy)
    bundle = build_phase_d6_report_bundle(report_type="dataset_quality_known_gap_semantics_v1", content=report, source_paths=[args.policy_review])
    write_phase_d6_report_bundle(bundle, args.report, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, Path(args.report).with_suffix(".md"), markdown=True)
    print(json.dumps({"status": report["status"], "continuation_allowed": report["chunk_continuation_allowed_if_downstream_ranges_independently_validate"], "report": args.report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
