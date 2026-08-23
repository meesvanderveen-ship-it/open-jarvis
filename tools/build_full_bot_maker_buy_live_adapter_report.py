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

from bot.full_bot_maker_buy_live_adapter import (  # noqa: E402
    EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
    build_full_bot_maker_buy_live_adapter_report,
    load_json_file,
    load_latest_full_bot_orchestrator_report,
    render_full_bot_maker_buy_live_adapter_markdown,
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
        description="Build ACK-gated Full Bot maker-BUY Phase-C live adapter report. Default is preview-only."
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--orchestrator-report", default="", help="Full Bot Orchestrator JSON report. Defaults to latest reports/d6/full-bot-orchestrator-*.json.")
    parser.add_argument("--ack", default="", help="Exact ACK required for actual submit.")
    parser.add_argument("--actual-submit", action="store_true", help="Attempt live submit only when exact ACK is also present and all guards pass.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/.")
    return parser.parse_args(argv)


def _coinbase_client_for_actual_submit(*, actual_submit: bool, ack: str):
    if not actual_submit or str(ack or "").strip() != EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK:
        return None
    from bot.coinbase_client import CoinbaseClient

    return CoinbaseClient()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root)
    source_paths = []
    if args.orchestrator_report:
        orch_path = Path(args.orchestrator_report)
        orchestrator_report = load_json_file(orch_path)
        source_paths.append(orch_path)
    else:
        orchestrator_report, latest_path = load_latest_full_bot_orchestrator_report(root)
        if latest_path:
            source_paths.append(latest_path)

    client = _coinbase_client_for_actual_submit(actual_submit=bool(args.actual_submit), ack=args.ack)
    report = build_full_bot_maker_buy_live_adapter_report(
        orchestrator_report=orchestrator_report,
        ack=args.ack,
        actual_submit_requested=bool(args.actual_submit),
        coinbase_client=client,
        source_paths=source_paths,
    )

    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_full_bot_maker_buy_live_adapter_markdown(report)
    if args.json_out:
        _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))

    if args.markdown:
        print(markdown_text, end="")
    elif args.json or not (args.json_out or args.markdown_out):
        print(json_text, end="")
    else:
        print(
            "full_bot_maker_buy_live_adapter "
            f"status={report.get('status')} "
            f"classification={report.get('classification')} "
            f"preview_only={report.get('preview_only')} "
            f"selected={len(report.get('selected_entry_candidates') or [])} "
            f"phase_c_all_passed={(report.get('phase_c_guard_summary') or {}).get('all_phase_c_guards_passed')} "
            f"actual_submit_attempted={report.get('actual_submit_attempted')} "
            f"coinbase_write_attempted={report.get('coinbase_write_attempted')} "
            f"state_write_performed={report.get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
