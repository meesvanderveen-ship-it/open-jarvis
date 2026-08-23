#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402
from bot.phase_replication_lifecycle_golden_payloads import (  # noqa: E402
    build_replication_lifecycle_golden_payload_report,
    render_replication_lifecycle_golden_markdown,
)


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build read-only replication lifecycle golden payloads and validate them through the paper simulator."
    )
    parser.add_argument("--root", default=".", help="Project root; defaults to current directory.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown instead of JSON.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_replication_lifecycle_golden_payload_report(root=Path(args.root))
    if args.json_out:
        _atomic_write(
            Path(args.json_out),
            (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8"),
        )
    if args.markdown_out:
        _atomic_write(
            Path(args.markdown_out),
            (render_replication_lifecycle_golden_markdown(report) + "\n").encode("utf-8"),
        )
    if args.markdown:
        print(render_replication_lifecycle_golden_markdown(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
