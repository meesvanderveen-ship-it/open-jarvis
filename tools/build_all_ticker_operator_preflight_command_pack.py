#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_all_ticker_operator_preflight_command_pack import build_all_ticker_operator_preflight_command_pack, render_all_ticker_operator_preflight_command_pack_markdown  # noqa: E402
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _write(path: Path, text: str) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe.with_name(f".{safe.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, safe)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    report = build_all_ticker_operator_preflight_command_pack(root=args.root)
    js = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    md = render_all_ticker_operator_preflight_command_pack_markdown(report)
    if args.json_out:
        _write(Path(args.json_out), js)
    if args.markdown_out:
        _write(Path(args.markdown_out), md)
    if args.markdown:
        print(md, end="")
    elif args.json or not (args.json_out or args.markdown_out):
        print(js, end="")
    else:
        flags = report.get("governance_flags") or {}
        print(f"all_ticker_operator_preflight_command_pack ready={flags.get('all_ticker_operator_preflight_command_pack_ready')} live_authorized={flags.get('all_ticker_live_authorized')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
