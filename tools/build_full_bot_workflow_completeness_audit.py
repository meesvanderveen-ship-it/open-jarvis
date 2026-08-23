#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.full_bot_workflow_completeness_audit import (  # noqa: E402
    build_full_bot_workflow_completeness_audit,
    render_full_bot_workflow_completeness_audit_markdown,
)
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Full Bot workflow completeness audit. Report-only: no Coinbase writes and no trading-state writes."
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--json-out", required=True, help="JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", required=True, help="Markdown output path under reports/d6/.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_full_bot_workflow_completeness_audit(root=Path(args.root))
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_full_bot_workflow_completeness_audit_markdown(report)

    _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))

    if args.markdown:
        print(markdown_text, end="")
    elif args.json:
        print(json_text, end="")
    else:
        print(
            "full_bot_workflow_completeness_audit "
            f"classification={report.get('classification')} "
            f"readiness_verdict={report.get('readiness_verdict')} "
            f"any_ticker_phase_c_ready_now={report.get('any_ticker_phase_c_ready_now')} "
            f"first_real_maker_buy_live_submit_allowed_now={report.get('first_real_maker_buy_live_submit_allowed_now')} "
            f"live_order_submit_attempted={report.get('live_order_submit_attempted')} "
            f"coinbase_write_attempted={report.get('coinbase_write_attempted')} "
            f"state_write_performed={report.get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
