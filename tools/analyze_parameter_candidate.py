#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.parameter_candidate_analysis import build_parameter_candidate_analysis, write_parameter_candidate_analysis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only parameter candidate analysis.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    report = build_parameter_candidate_analysis(root=root)
    outputs = write_parameter_candidate_analysis(report, root=root)
    report["outputs"] = outputs
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "parameter_candidate_analysis "
            f"candidate_available={report.get('candidate_available')} "
            f"recommendation={report.get('recommendation')} "
            f"reason={report.get('reason')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
