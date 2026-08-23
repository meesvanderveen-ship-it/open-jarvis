#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_human_review_export import (  # noqa: E402
    build_phase_d6_human_review_export,
    human_review_export_to_markdown,
    write_human_review_export,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="D.6 human-review-only export. No parameter approvals.")
    parser.add_argument("--review-pack", default="", help="Optional parameter review pack JSON path")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown instead of JSON")
    parser.add_argument("--output", default="", help="Optional output path; must be under reports/d6/")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    export = build_phase_d6_human_review_export(parameter_review_pack_path=args.review_pack or None)
    if args.output:
        write_human_review_export(export, args.output, markdown=args.markdown)
    if args.markdown:
        print(human_review_export_to_markdown(export), end="")
    else:
        print(json.dumps(export, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
