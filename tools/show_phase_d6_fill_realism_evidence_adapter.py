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

from bot.phase_d6_fill_realism_evidence_adapter import build_phase_d6_fill_realism_evidence_report  # noqa: E402


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
        description="D.6 research-only fill-realism evidence adapter. No recommendations or live instructions."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fill-realism-report", action="append", help="Comma-separated or repeatable fill-realism report JSON")
    source.add_argument("--input", action="append", help="Comma-separated or repeatable raw local JSON/JSONL input path")
    parser.add_argument("--maker-fee-pct", default="0.004", help="Research placeholder maker fee pct, not a live fee schedule")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_fill_realism_evidence_report(
        fill_realism_report_paths=_split_csv(args.fill_realism_report or []),
        input_paths=_split_csv(args.input or []),
        maker_fee_pct=args.maker_fee_pct,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
