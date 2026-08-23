#!/usr/bin/env python3
"""Show Shadow Outcome Accelerator learning status.

Read-only diagnostic tool. No Coinbase calls, no live orders,
no parameter mutation, no .env writes, no service restart.

Usage:
    python3 -m tools.show_shadow_outcome_learning_status
    python3 -m tools.show_shadow_outcome_learning_status --json
    python3 -m tools.show_shadow_outcome_learning_status --write-reports
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.shadow_outcome_accelerator import (  # noqa: E402
    SHADOW_STORE_PATH,
    REPORT_JSON_PATH,
    REPORT_MD_PATH,
    ShadowOutcomeStore,
    build_shadow_outcome_summary,
    write_shadow_outcome_reports,
)


def _render_markdown(summary: dict) -> str:
    lines = [
        "# Shadow Outcome Accelerator — Learning Status",
        "",
        f"Generated: {summary.get('generated_at', 'n/a')}",
        "",
        "## Overview",
        "",
        f"  Total shadow decisions  : {summary.get('total_shadow_decisions', 0)}",
        f"  Usable evidence count   : {summary.get('usable_evidence_count', 0)}",
        f"  Evidence quality score  : {summary.get('evidence_quality_score', 0.0):.1%}",
        f"  Sufficient for optim.   : {summary.get('sufficient_for_optimization', False)}",
        "",
        f"  Note: {summary.get('sufficiency_note', '')}",
        "",
        "## Status Breakdown",
        "",
    ]
    sc = summary.get("status_counts") or {}
    for k, v in sorted(sc.items()):
        lines.append(f"  {k:<12} : {v}")

    lines += [
        "",
        "## Pending / Complete by Horizon",
        "",
        f"  {'Horizon':<8} {'Pending':>8} {'Complete':>10} {'Insuf.Data':>12}",
        f"  {'-'*42}",
    ]
    for h in ("1h", "4h", "24h"):
        ev_c = (summary.get("evaluations_by_horizon") or {}).get(h) or {}
        lines.append(
            f"  {h:<8} {ev_c.get('pending', 0):>8} {ev_c.get('complete', 0):>10} "
            f"{ev_c.get('insufficient_data', 0):>12}"
        )

    lines += [
        "",
        "## Per-Ticker Coverage",
        "",
        f"  {'Ticker':<16} {'Records':>8}",
        f"  {'-'*26}",
    ]
    for ticker, count in sorted((summary.get("by_ticker") or {}).items()):
        lines.append(f"  {ticker:<16} {count:>8}")

    lines += [
        "",
        "## Per-Regime Coverage",
        "",
        f"  {'Regime':<40} {'Records':>8}",
        f"  {'-'*50}",
    ]
    for regime, count in sorted(
        (summary.get("by_regime") or {}).items(), key=lambda x: -x[1]
    ):
        lines.append(f"  {str(regime):<40} {count:>8}")

    missed = summary.get("top_missed_opportunity_patterns") or []
    if missed:
        lines += [
            "",
            "## Top Missed Opportunity Patterns",
            "",
            f"  {'Setup Type':<30} {'Count':>6}",
            f"  {'-'*38}",
        ]
        for p in missed:
            lines.append(f"  {str(p.get('setup_type')):<30} {p.get('count'):>6}")

    avoided = summary.get("top_bad_trade_avoided_patterns") or []
    if avoided:
        lines += [
            "",
            "## Top Bad Trade Avoided Patterns",
            "",
            f"  {'Decision':<30} {'Count':>6}",
            f"  {'-'*38}",
        ]
        for p in avoided:
            lines.append(f"  {str(p.get('decision')):<30} {p.get('count'):>6}")

    lines += [
        "",
        "## Evidence Quality Distribution",
        "",
        f"  {'Quality':<16} {'Count':>6}",
        f"  {'-'*24}",
    ]
    for q, c in sorted((summary.get("quality_distribution") or {}).items()):
        lines.append(f"  {q:<16} {c:>6}")

    lines += [
        "",
        "## Safety Guarantees",
        "",
        f"  no_live_orders      : {summary.get('no_live_orders', True)}",
        f"  no_coinbase_calls   : {summary.get('no_coinbase_calls', True)}",
        f"  no_parameter_mutation: {summary.get('no_parameter_mutation', True)}",
        "",
        f"  {summary.get('learning_policy', '')}",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Show Shadow Outcome Accelerator learning status. "
            "Read-only. No Coinbase calls. No live orders. No parameter mutation."
        )
    )
    parser.add_argument(
        "--json", action="store_true", help="Print JSON summary instead of human-readable output."
    )
    parser.add_argument(
        "--write-reports",
        action="store_true",
        help=(
            f"Write reports to {REPORT_JSON_PATH} and {REPORT_MD_PATH}. "
            "Read-only analytics only."
        ),
    )
    parser.add_argument(
        "--store-path",
        default=str(PROJECT_ROOT / SHADOW_STORE_PATH),
        help="Path to shadow_decision_outcomes.jsonl store.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    store = ShadowOutcomeStore(path=args.store_path, enabled=True)
    records = store.load_all()
    summary = build_shadow_outcome_summary(records)

    if args.write_reports:
        write_shadow_outcome_reports(
            records,
            json_path=PROJECT_ROOT / REPORT_JSON_PATH,
            md_path=PROJECT_ROOT / REPORT_MD_PATH,
        )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(_render_markdown(summary), end="")

    return 0


if __name__ == "__main__":
    sys.exit(main())
