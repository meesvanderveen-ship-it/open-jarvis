#!/usr/bin/env python3
"""Build the Parameter Proposal Funnel report.

Reshapes the per-parameter evidence from
``bot.adaptive_learning_intelligence`` into a maturity funnel: how many of
the ~50 learnable parameters sit at each tier (observed_signal ..
operator_review_candidate), grouped by category, with a one-line reason for
every parameter that is not yet further along.

Read-only, no LLM calls, no Coinbase calls, no state mutation. Writes:

  reports/learning/parameter-proposal-funnel-latest.json
  reports/learning/parameter-proposal-funnel-latest.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.adaptive_learning_intelligence import build_adaptive_learning_intelligence
from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.parameter_proposal_scoring import TIERS

REPORT_JSON_PATH = Path("reports/learning/parameter-proposal-funnel-latest.json")
REPORT_MD_PATH = Path("reports/learning/parameter-proposal-funnel-latest.md")


def build_parameter_proposal_funnel(*, root: str | Path = ".") -> Dict[str, Any]:
    intelligence = build_adaptive_learning_intelligence(root=root)
    parameter_evidence = intelligence.get("parameter_evidence", [])

    funnel: Dict[str, List[Dict[str, Any]]] = {tier: [] for tier in TIERS}
    by_category: Dict[str, Dict[str, int]] = defaultdict(lambda: {tier: 0 for tier in TIERS})

    for item in parameter_evidence:
        tier = item.get("tier", "observed_signal")
        row = {
            "parameter": item["parameter"],
            "category": item["category"],
            "direction": item["direction"],
            "confidence": item["confidence"],
            "proposal_score": item["proposal_score"],
            "evidence_count": item["evidence_count"],
            "overfit_risk": item["overfit_risk"],
            "regimes_seen": item["regimes_seen"],
            "tickers_seen": item["tickers_seen"],
            "why_no_proposal": item.get("next_data_needed") or "",
        }
        funnel.setdefault(tier, []).append(row)
        by_category[item["category"]][tier] += 1

    return {
        "schema_version": "parameter_proposal_funnel_v1",
        "generated_at": intelligence["generated_at"],
        "read_only": True,
        "llm_call_made": False,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "automatic_parameter_apply_enabled": False,
        "tier_order": list(TIERS),
        "funnel": funnel,
        "funnel_counts": {tier: len(rows) for tier, rows in funnel.items()},
        "by_category": dict(by_category),
        "total_parameters": len(parameter_evidence),
        "apply_ready_policy": (
            "apply_ready_candidate is intentionally never populated by this learning layer. "
            "Activation always requires the existing autonomous_parameter_governor ACK flow and "
            "approved_parameter_profile gate."
        ),
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = ["# Parameter Proposal Funnel", ""]
    lines.append(f"Generated: `{report.get('generated_at')}`")
    lines.append("")
    lines.append(f"Total learnable parameters tracked: `{report.get('total_parameters')}`")
    lines.append("")
    lines.append("## Funnel counts")
    for tier in report.get("tier_order", []):
        lines.append(f"- `{tier}`: {report['funnel_counts'].get(tier, 0)}")
    lines.append("")
    lines.append(f"_{report.get('apply_ready_policy')}_")
    lines.append("")

    for tier in report.get("tier_order", []):
        rows = report["funnel"].get(tier, [])
        lines.append(f"## {tier} ({len(rows)})")
        if not rows:
            lines.append("- none")
            lines.append("")
            continue
        lines.append("| parameter | category | direction | confidence | evidence | overfit_risk | why_no_proposal |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in sorted(rows, key=lambda r: r["parameter"]):
            lines.append(
                f"| {row['parameter']} | {row['category']} | {row['direction']} | "
                f"{row['confidence']:.4g} | {row['evidence_count']} | {row['overfit_risk']} | "
                f"{row['why_no_proposal']} |"
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
    report = build_parameter_proposal_funnel(root=root_path)
    if not args.no_write:
        write_reports(report, root=root_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Funnel counts: {report['funnel_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
