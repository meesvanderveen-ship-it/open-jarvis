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

from bot.phase_d6_evidence_review_bundle import build_phase_d6_evidence_review_bundle  # noqa: E402


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 human-review-only combined evidence bundle. No recommendations or live instructions."
    )
    parser.add_argument("--d5-evidence", action="append", default=[], help="Comma-separated or repeatable D.5 evidence report JSON")
    parser.add_argument("--regime-report", action="append", default=[], help="Comma-separated or repeatable regime report JSON")
    parser.add_argument(
        "--fill-realism-evidence",
        action="append",
        default=[],
        help="Comma-separated or repeatable fill-realism evidence report JSON",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_evidence_review_bundle(
        d5_evidence_paths=_split_csv(args.d5_evidence),
        regime_report_paths=_split_csv(args.regime_report),
        fill_realism_evidence_paths=_split_csv(args.fill_realism_evidence),
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
