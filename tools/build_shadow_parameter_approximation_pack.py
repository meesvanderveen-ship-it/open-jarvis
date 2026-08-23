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

from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402
from bot.phase_shadow_parameter_approximation_pack import (  # noqa: E402
    build_shadow_parameter_approximation_pack,
    render_shadow_parameter_approximation_pack_markdown,
)


def _write(path: Path, text: str) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe.with_name(f".{safe.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, safe)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build report-only shadow parameter approximation pack.")
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument(
        "--preflight-report",
        default="reports/d6/all-ticker-live-readonly-preflight-20260609.json",
    )
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    report = build_shadow_parameter_approximation_pack(
        root=args.root,
        preflight_report_path=args.preflight_report,
    )
    js = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    md = render_shadow_parameter_approximation_pack_markdown(report)
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
        print(
            "shadow_parameter_approximation_pack "
            f"ready={flags.get('shadow_parameter_approximation_pack_ready')} "
            f"parameter_change_allowed={flags.get('parameter_change_allowed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
