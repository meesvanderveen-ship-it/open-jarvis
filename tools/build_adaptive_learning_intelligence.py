#!/usr/bin/env python3
"""Build the Adaptive Learning Intelligence report.

Read-only aggregation over existing evidence (decision outcomes, execution
outcomes, trade reflections, opportunity memory) into a per-parameter
evidence/tier/overfit-risk view, missed-opportunity learning, wait-decision
quality and overall learning depth/coverage.

This tool makes NO LLM calls, NO Coinbase calls, and performs NO state
mutation. It only reads existing local report/state/log data (via
bot.adaptive_learning_intelligence) and writes two report files:

  reports/learning/adaptive-learning-intelligence-latest.json
  reports/learning/adaptive-learning-intelligence-latest.md

Every proposal produced here tops out at "operator_review_candidate" --
nothing in this layer can mark a parameter "apply_ready" or change any
runtime value. The existing autonomous_parameter_governor ACK flow and
approved_parameter_profile gate remain the only activation route.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.adaptive_learning_intelligence import build_adaptive_learning_intelligence
from bot.atomic_io import atomic_write_json, atomic_write_text

REPORT_JSON_PATH = Path("reports/learning/adaptive-learning-intelligence-latest.json")
REPORT_MD_PATH = Path("reports/learning/adaptive-learning-intelligence-latest.md")


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def render_markdown(report: Dict[str, Any]) -> str:
    lines = ["# Adaptive Learning Intelligence", ""]
    lines.append(f"Generated: `{report.get('generated_at')}`")
    lines.append("")
    lines.append(
        "Read-only evidence aggregation. No LLM calls, no Coinbase calls, no state mutation. "
        "No proposal here is ever auto-applied -- the existing governor/approved-profile gate "
        "is the only activation route."
    )
    lines.append("")

    depth = report.get("learning_depth", {})
    lines.append("## Learning depth")
    lines.append(f"- Resolved decision outcomes: `{depth.get('decision_outcomes_resolved')}`")
    lines.append(f"- Pending decision outcomes: `{depth.get('decision_outcomes_pending')}`")
    lines.append(f"- Execution outcomes: `{depth.get('execution_outcomes_count')}`")
    lines.append(f"- Trade reflections: `{depth.get('trade_reflections_count')}`")
    regime_cov = depth.get("regime_coverage", {})
    lines.append(
        f"- Regime coverage: `{regime_cov.get('coverage_pct')}` "
        f"({regime_cov.get('distinct_known')} known regime(s) seen: {regime_cov.get('known_regimes_seen')})"
    )
    ticker_cov = depth.get("ticker_coverage", {})
    lines.append(f"- Ticker coverage: `{ticker_cov.get('distinct_known')}` ticker(s) seen")
    lines.append("")

    funnel = report.get("proposal_maturity_funnel", {})
    lines.append("## Proposal maturity funnel")
    for tier, count in funnel.items():
        lines.append(f"- `{tier}`: {count}")
    lines.append("")

    overfit = report.get("overfit_risk_monitor", {})
    lines.append("## Overfit risk monitor")
    lines.append(f"- low: {overfit.get('low')}, medium: {overfit.get('medium')}, high: {overfit.get('high')}")
    if overfit.get("high_risk_parameters"):
        lines.append(f"- High overfit-risk parameters: {', '.join(overfit['high_risk_parameters'])}")
    lines.append("")

    wait_quality = report.get("wait_decision_quality", {})
    lines.append("## Wait decision quality")
    lines.append(f"- Resolved wait-like decisions: `{wait_quality.get('resolved_wait_like_decisions')}`")
    lines.append(f"- Quality (correct / classified): `{wait_quality.get('wait_decision_quality_pct')}`")
    lines.append(f"- {wait_quality.get('interpretation')}")
    lines.append("")

    missed = report.get("missed_opportunity_learning", {})
    lines.append("## Missed opportunity learning")
    lines.append(f"- Missed opportunity count: `{missed.get('missed_opportunity_count')}`")
    if missed.get("by_ticker"):
        lines.append(f"- By ticker: {missed['by_ticker']}")
    if missed.get("by_setup_type"):
        lines.append(f"- By setup type: {missed['by_setup_type']}")
    lines.append("")

    lines.append("## Parameter evidence")
    lines.append("")
    lines.append("| parameter | tier | direction | confidence | evidence | overfit_risk | proposal_score |")
    lines.append("|---|---|---|---|---|---|---|")
    for item in report.get("parameter_evidence", []):
        lines.append(
            f"| {item['parameter']} | {item['tier']} | {item['direction']} | "
            f"{_fmt(item['confidence'])} | {item['evidence_count']} | {item['overfit_risk']} | "
            f"{_fmt(item['proposal_score'])} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_reports(report: Dict[str, Any], *, root: Path) -> None:
    atomic_write_json(root / REPORT_JSON_PATH, report)
    atomic_write_text(root / REPORT_MD_PATH, render_markdown(report))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="print JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="skip writing report files (used in tests)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root_path = Path(args.root)
    report = build_adaptive_learning_intelligence(root=root_path)
    if not args.no_write:
        write_reports(report, root=root_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        depth = report.get("learning_depth", {})
        print(f"Resolved decision outcomes: {depth.get('decision_outcomes_resolved')}")
        print(f"Proposal maturity funnel: {report.get('proposal_maturity_funnel')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
