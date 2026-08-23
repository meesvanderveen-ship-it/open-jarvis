#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_state_hygiene_cleanup_preview import (  # noqa: E402
    build_state_hygiene_cleanup_preview_from_files,
    render_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build read-only state hygiene cleanup preview. No state repair/apply is performed."
    )
    parser.add_argument(
        "--orders-file",
        default=str(PROJECT_ROOT / "state" / "open_orders.json"),
        help="Local open-orders JSON file to inspect.",
    )
    parser.add_argument(
        "--positions-file",
        default=str(PROJECT_ROOT / "state" / "positions.json"),
        help="Local positions JSON file to inspect.",
    )
    parser.add_argument("--json-out", default="", help="Optional JSON report output path.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown report output path.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown to stdout.")
    return parser.parse_args()


def _write_text(path: str, text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    report = build_state_hygiene_cleanup_preview_from_files(
        orders_file=args.orders_file,
        positions_file=args.positions_file,
    )
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    markdown_text = render_markdown(report)

    if args.json_out:
        _write_text(args.json_out, json_text)
    if args.markdown_out:
        _write_text(args.markdown_out, markdown_text)

    if args.markdown:
        print(markdown_text, end="")
    else:
        if args.json or not (args.json_out or args.markdown_out):
            print(json_text, end="")
        else:
            print(
                f"state_hygiene_cleanup_preview status={report.get('status')} "
                f"cleanup_preview_count={report.get('cleanup_preview_count')} "
                f"state_write_performed={report.get('state_write_performed')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
