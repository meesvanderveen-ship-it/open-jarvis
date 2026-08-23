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

from bot.phase_d6_research_index_export import (  # noqa: E402
    build_phase_d6_research_index_export,
    research_index_export_to_markdown,
    write_research_index_export,
)


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="D.6 research index export. No parameter approvals.")
    parser.add_argument("--manifest", default="", help="Optional manifest JSON path")
    parser.add_argument("--lineage", default="", help="Optional lineage JSON path")
    parser.add_argument("--safety-validation", default="", help="Optional safety validation JSON path")
    parser.add_argument("--report", action="append", default=[], help="Comma-separated or repeatable direct report path")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown instead of JSON")
    parser.add_argument("--output", default="", help="Optional output path under reports/d6/")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_research_index_export(
        manifest_path=args.manifest or None,
        lineage_path=args.lineage or None,
        safety_validation_path=args.safety_validation or None,
        report_paths=_split_csv(args.report),
    )
    if args.output:
        write_research_index_export(report, args.output, markdown=args.markdown)
    if args.markdown:
        print(research_index_export_to_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
