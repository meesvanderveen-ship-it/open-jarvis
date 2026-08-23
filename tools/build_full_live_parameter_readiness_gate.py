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

from bot.full_live_parameter_readiness_gate import (  # noqa: E402
    build_full_live_parameter_readiness_gate,
    render_full_live_parameter_readiness_gate_markdown,
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
        description="Build report-only Full Live parameter readiness and start gate. No env/state/live mutation."
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--ack", default="", help="Exact ACK for diagnostics only. Actual submit is never attempted by this tool.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--json-out", required=True, help="JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", required=True, help="Markdown output path under reports/d6/.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_full_live_parameter_readiness_gate(root=Path(args.root), ack=args.ack)
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_full_live_parameter_readiness_gate_markdown(report)
    _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))

    if args.markdown:
        print(markdown_text, end="")
    elif args.json:
        print(json_text, end="")
    else:
        print(
            "full_live_parameter_readiness_gate "
            f"classification={report.get('classification')} "
            f"phase_c_ready={report.get('any_ticker_phase_c_ready_now')} "
            f"actual_submit_allowed={report.get('first_real_maker_buy_live_submit_allowed_now')} "
            f"full_start_allowed={report.get('full_autonomous_start_allowed_now')} "
            f"env_mutation_performed={report.get('env_mutation_performed')} "
            f"bot_start_attempted={report.get('bot_start_attempted')} "
            f"live_order_submit_attempted={report.get('live_order_submit_attempted')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
