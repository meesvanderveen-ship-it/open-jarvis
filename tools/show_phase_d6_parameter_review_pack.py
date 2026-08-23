#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_parameter_review_pack import build_phase_d6_parameter_review_pack  # noqa: E402


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="D.6 human-review-only parameter review pack scaffold. No approvals.")
    parser.add_argument("--parameter-inventory", default="", help="Optional parameter inventory report JSON path")
    parser.add_argument("--evidence-review-bundle", default="", help="Optional combined evidence review bundle JSON path")
    parser.add_argument("--d5-evidence", action="append", default=[], help="Comma-separated or repeatable D.5 evidence report JSON")
    parser.add_argument("--regime-report", action="append", default=[], help="Comma-separated or repeatable regime report JSON")
    parser.add_argument("--fill-realism-evidence", action="append", default=[], help="Comma-separated or repeatable fill-realism evidence JSON")
    parser.add_argument("--guardrail-summary", default="", help="Optional guardrail summary JSON path")
    parser.add_argument("--guardrail-report", action="append", default=[], help="Comma-separated or repeatable raw guardrail report JSON")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_parameter_review_pack(
        parameter_inventory_path=args.parameter_inventory or None,
        evidence_review_bundle_path=args.evidence_review_bundle or None,
        d5_evidence_paths=_split_csv(args.d5_evidence),
        regime_report_paths=_split_csv(args.regime_report),
        fill_realism_evidence_paths=_split_csv(args.fill_realism_evidence),
        guardrail_summary_path=args.guardrail_summary or None,
        guardrail_report_paths=_split_csv(args.guardrail_report),
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
