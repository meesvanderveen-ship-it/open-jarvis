#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_report_bundle_writer import (  # noqa: E402
    build_phase_d6_report_bundle,
    serialize_report,
    write_phase_d6_report_bundle,
)
from bot.phase_d6_coinbase_candle_ingest import assert_research_path  # noqa: E402


def _load_content(path: str) -> dict | str:
    if not path:
        return {}
    safe = assert_research_path(path)
    text = safe.read_text(encoding="utf-8")
    if safe.suffix.lower() == ".json":
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else {"items": loaded}
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="D.6 atomic report bundle writer. Reports only; no Coinbase calls.")
    parser.add_argument("--report-type", default="generic_research_report")
    parser.add_argument("--content", default="", help="Optional JSON or text content path")
    parser.add_argument("--source-path", action="append", default=[], help="Repeatable explicit source path")
    parser.add_argument("--output", default="", help="Optional output path; must be under reports/d6/")
    parser.add_argument("--markdown", action="store_true", help="Emit Markdown instead of JSON")
    parser.add_argument("--metadata-sidecar", action="store_true", help="Write output.metadata.json next to report")
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview only; no files written")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_report_bundle(
        report_type=args.report_type,
        content=_load_content(args.content),
        source_paths=args.source_path,
    )
    if args.output:
        result = write_phase_d6_report_bundle(
            report,
            args.output,
            markdown=args.markdown,
            metadata_sidecar=args.metadata_sidecar,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    elif args.markdown:
        print(serialize_report(report, markdown=True).decode("utf-8"), end="")
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
