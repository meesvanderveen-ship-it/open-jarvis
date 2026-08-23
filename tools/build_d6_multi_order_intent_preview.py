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

from bot.phase_d6_multi_order_intent_preview import (  # noqa: E402
    build_multi_order_intent_preview_report,
    load_json_file,
    load_recent_analysis_candidates,
    render_multi_order_intent_preview_markdown,
)
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def _load_candidates(args: argparse.Namespace) -> list[dict]:
    if args.candidates_json:
        payload = load_json_file(args.candidates_json)
        if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
            return [x for x in payload["candidates"] if isinstance(x, dict)]
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []
    return load_recent_analysis_candidates(args.analysis_log, max_lines=args.max_analysis_lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build D.6 multi-order intent preview report. Report-only: no Coinbase calls, no live submit, "
            "no market order, no SELL execution and no trading-state writes."
        )
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--analysis-log", default="logs/analysis.jsonl")
    parser.add_argument("--candidates-json", default="")
    parser.add_argument("--open-orders", default="state/open_orders.json")
    parser.add_argument("--positions", default="state/positions.json")
    parser.add_argument("--max-analysis-lines", type=int, default=80)
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root)
    candidates = _load_candidates(args)
    open_orders_path = root / args.open_orders
    positions_path = root / args.positions
    open_orders_state = load_json_file(open_orders_path) if open_orders_path.exists() else {}
    positions_state = load_json_file(positions_path) if positions_path.exists() else {}
    source_paths = [open_orders_path, positions_path]
    if args.candidates_json:
        source_paths.append(Path(args.candidates_json))
    else:
        source_paths.append(root / args.analysis_log)

    report = build_multi_order_intent_preview_report(
        candidates=candidates,
        open_orders_state=open_orders_state,
        positions_state=positions_state,
        source_paths=source_paths,
    )
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_multi_order_intent_preview_markdown(report)

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
            "d6_multi_order_intent_preview "
            f"classification={report.get('classification')} "
            f"preview_only={report.get('preview_only')} "
            f"preview_ready={report.get('preview_ready_intent_count')} "
            f"near_miss={report.get('near_miss_intent_count')} "
            f"hard_rejected={report.get('hard_rejected_candidate_count')} "
            f"rejected={report.get('rejected_candidate_count')} "
            f"state_write_performed={report.get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
