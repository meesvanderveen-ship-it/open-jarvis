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

from bot.phase_d6_guardrail_summary_adapter import build_phase_d6_guardrail_summary_report  # noqa: E402


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="D.6 research-only guardrail summary adapter. No Coinbase calls.")
    parser.add_argument("--report", action="append", required=True, help="Comma-separated or repeatable local guardrail/report JSON path")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_guardrail_summary_report(report_paths=_split_csv(args.report))
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
