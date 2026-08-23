#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.agent_context_quality import build_agent_context_quality_report
from bot.atomic_io import atomic_write_json, atomic_write_text

DEFAULT_JSON = Path("reports/audits/agent-decision-context-audit-latest.json")
DEFAULT_MD = Path("reports/audits/agent-decision-context-audit-latest.md")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "most_common"):
        return dict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _md(report: dict[str, Any]) -> str:
    proof = report["runtime_proof"]
    lines = [
        "# Agent Decision Context Audit",
        "",
        "Report-only; no Coinbase calls and no state mutation.",
        "",
        "## Runtime Proof",
        f"- decision rows: {proof['decision_rows']}",
        f"- tickers considered: {proof['tickers_overconsidered']}",
        f"- judge called: {proof['judge_called']}",
        f"- valid trade plans: {proof['valid_trade_plans']}",
        f"- opportunity-memory candidates estimated: {proof['opportunity_memory_candidates_estimated']}",
        f"- submit attempts seen: {proof['submit_attempts_seen']}",
        f"- analysis rows with product_rules: {proof.get('analysis_rows_with_product_rules', 0)}",
        f"- analysis rows with recent_exchange_rejections: {proof.get('analysis_rows_with_recent_exchange_rejections', 0)}",
        f"- analysis rows with execution_feasibility: {proof.get('analysis_rows_with_execution_feasibility', 0)}",
        "",
        "## Context Matrix",
    ]
    for row in report["matrix"]:
        lines.append(f"- `{row['priority']}` {row['context_field']}: logs={row['available_in_logs']} judge={row['available_to_final_judge']} submitter={row['available_to_submitter']}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build agent context quality audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = _jsonable(build_agent_context_quality_report(args.root, limit=args.limit))
    atomic_write_json(args.json_out, report)
    atomic_write_text(args.md_out, _md(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "rows": report["runtime_proof"]["decision_rows"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
