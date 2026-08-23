#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.trade_reflection import TradeReflectionStore


def _short(value: Any, max_len: int = 96) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").strip()
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _print_section(title: str, rows: Iterable[Dict[str, Any]], fields: List[str]) -> None:
    rows = list(rows)
    print(f"\n{title} ({len(rows)})")
    print("-" * max(8, len(title) + 4))
    if not rows:
        print("geen records")
        return
    for i, row in enumerate(rows, 1):
        bits = []
        for field in fields:
            bits.append(f"{field}={_short(row.get(field))}")
        print(f"{i:02d}. " + " | ".join(bits))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only trade reflection learning/analytics overview. Does not call Coinbase or any LLM."
    )
    parser.add_argument("--path", default="state/trade_reflections.jsonl", help="Path to trade_reflections.jsonl")
    parser.add_argument("--ticker", default=None, help="Optional ticker filter, e.g. ADA-USDC")
    parser.add_argument("--limit", type=int, default=200, help="Max records to include, newest first")
    parser.add_argument("--min-samples", type=int, default=3, help="Minimum sample size for repeated-context signals")
    parser.add_argument("--json", action="store_true", help="Print full JSON summary")
    parser.add_argument("--write-report", default=None, help="Optional output path for JSON report, e.g. logs/trade_learning_report.json")
    args = parser.parse_args()

    store = TradeReflectionStore(path=Path(args.path))
    summary = store.analytics_summary(
        ticker=args.ticker,
        limit=args.limit,
        min_samples_for_signal=args.min_samples,
    )

    if args.write_report:
        report = store.write_learning_report(
            output_path=Path(args.write_report),
            ticker=args.ticker,
            limit=args.limit,
            min_samples_for_signal=args.min_samples,
        )
        summary["written_report"] = str(args.write_report)
        summary["written_report_count"] = report.get("count")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    overall = summary.get("overall", {})
    print("Trade reflection learning overview")
    print("==================================")
    print(f"source_path: {summary.get('source_path')}")
    print(f"ticker:      {summary.get('ticker') or 'ALL'}")
    print(f"count:       {summary.get('count', 0)}")
    print(f"win_rate:    {overall.get('win_rate')}")
    print(f"net_pnl:     {overall.get('net_realized_pnl')}")
    print(f"avg_pnl_pct: {overall.get('avg_realized_pnl_pct')}")
    print(f"sample:      {overall.get('sample_strength')}")
    print(f"safety:      {summary.get('learning_policy')}")

    _print_section(
        "CANDIDATE AVOID CONTEXTS — soft context only",
        summary.get("candidate_avoid_contexts", []),
        ["dimension", "value", "sample_size", "wins", "losses", "lesson_weight"],
    )
    _print_section(
        "CANDIDATE PREFER CONTEXTS — soft context only",
        summary.get("candidate_prefer_contexts", []),
        ["dimension", "value", "sample_size", "wins", "losses", "lesson_weight"],
    )
    _print_section(
        "SURPRISE FLAGS — review thesis quality",
        summary.get("surprise_flags", []),
        ["ticker", "setup_type", "surprise_label", "surprise_ratio", "warning"],
    )

    if args.write_report:
        print(f"\nWrote report: {args.write_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
