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

from bot.full_bot_orchestrator import (  # noqa: E402
    build_full_bot_orchestrator_report,
    load_or_build_d6_preview,
    render_full_bot_orchestrator_markdown,
)
from bot.phase_d6_multi_order_intent_preview import load_json_file  # noqa: E402
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Full Bot Orchestrator v1 dry-run report. Report-only: no Coinbase writes and no trading-state writes."
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--d6-preview-json", default="", help="Optional existing D.6 multi-order preview JSON.")
    parser.add_argument("--open-orders", default="state/open_orders.json")
    parser.add_argument("--positions", default="state/positions.json")
    parser.add_argument("--analysis-log", default="logs/analysis.jsonl")
    parser.add_argument("--max-analysis-lines", type=int, default=80)
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root)
    open_orders_path = root / args.open_orders
    positions_path = root / args.positions
    d6_path = Path(args.d6_preview_json) if args.d6_preview_json else None

    open_orders_state = load_json_file(open_orders_path) if open_orders_path.exists() else {"orders": {}}
    positions_state = load_json_file(positions_path) if positions_path.exists() else {}
    d6_preview = load_json_file(d6_path) if d6_path and d6_path.exists() else load_or_build_d6_preview(root, analysis_log=args.analysis_log, max_analysis_lines=args.max_analysis_lines)
    source_paths = [open_orders_path, positions_path]
    if d6_path:
        source_paths.append(d6_path)
    report = build_full_bot_orchestrator_report(
        d6_preview_report=d6_preview,
        open_orders_state=open_orders_state,
        positions_state=positions_state,
        source_paths=source_paths,
    )

    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_full_bot_orchestrator_markdown(report)
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
            "full_bot_orchestrator "
            f"classification={report.get('classification')} "
            f"dry_run={report.get('full_function_dry_run')} "
            f"entry_candidates={len(report.get('entry_action_candidates') or [])} "
            f"exit_candidates={len(report.get('exit_action_candidates') or [])} "
            f"market_candidates={len(report.get('market_action_candidates') or [])} "
            f"state_write_performed={report.get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
