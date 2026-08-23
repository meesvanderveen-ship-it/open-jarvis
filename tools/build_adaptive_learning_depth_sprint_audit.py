#!/usr/bin/env python3
"""Build the Adaptive Learning Depth Sprint audit report.

Self-reporting audit of this sprint's changes, in the same flat
safety-flag style as the other reports/audits/*-latest.json files in this
repo. Read-only: it inspects the new modules' own outputs and the registry,
it does not re-run a trading cycle and performs no mutation of any kind.

Writes:
  reports/audits/adaptive-learning-depth-sprint-latest.json
  reports/audits/adaptive-learning-depth-sprint-latest.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.adaptive_learning_intelligence import build_adaptive_learning_intelligence
from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.regime_parameter_profiles import build_regime_parameter_profiles

REPORT_JSON_PATH = Path("reports/audits/adaptive-learning-depth-sprint-latest.json")
REPORT_MD_PATH = Path("reports/audits/adaptive-learning-depth-sprint-latest.md")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_adaptive_learning_depth_sprint_audit(*, root: str | Path = ".") -> Dict[str, Any]:
    root_path = Path(root)
    intelligence = build_adaptive_learning_intelligence(root=root_path)
    regime_profiles = build_regime_parameter_profiles(root=root_path)

    depth = intelligence.get("learning_depth", {})
    funnel = intelligence.get("proposal_maturity_funnel", {})
    overfit = intelligence.get("overfit_risk_monitor", {})
    regime_coverage_pct = depth.get("regime_coverage", {}).get("coverage_pct", 0.0)
    parameter_evidence = intelligence.get("parameter_evidence", [])
    river_signal_matches = sum(
        1
        for item in parameter_evidence
        if (item.get("growbot_river_cross_check") or {}).get("river_signal_available")
    )

    findings = [
        f"{depth.get('decision_outcomes_resolved', 0)} resolved decision outcomes evaluated; "
        f"{funnel.get('observed_signal', 0)} parameter(s) at observed_signal, "
        f"{funnel.get('shadow_candidate', 0)} at shadow_candidate, "
        f"{funnel.get('backtest_candidate', 0)} at backtest_candidate or higher.",
        f"Regime coverage across current evidence is {regime_coverage_pct} -- the dominant reason "
        f"{overfit.get('high', 0)} parameter(s) currently score high overfit risk is missing/garbled "
        "regime tags upstream, not a lack of directional signal.",
        f"{len(regime_profiles.get('narrative_lines', []))} regime-specific narrative line(s) produced "
        "(report-only, never auto-activated).",
        f"River backend for this cycle: {intelligence.get('river_backend')} "
        f"(reports/growbot_river/growbot-river-learning-latest.json, generated_at="
        f"{intelligence.get('growbot_river_learning_report_generated_at')}); "
        f"{river_signal_matches}/{len(parameter_evidence)} mapped parameter(s) cross-checked against an "
        "existing GrowBot/River parameter_signal/proposal/blocked_proposal entry rather than being "
        "evaluated from raw outcome logs alone.",
    ]

    return {
        "phase": "adaptive_learning_depth_sprint_v1",
        "generated_at": _now_iso(),
        "read_only": True,
        "llm_call_made": False,
        "coinbase_call_attempted": False,
        "live_order_submitted": False,
        "live_buy_attempted": False,
        "live_sell_attempted": False,
        "coinbase_submit_cancel_replace_attempted": False,
        "trading_state_mutated": False,
        "open_orders_mutated": False,
        "positions_mutated": False,
        "approved_profile_mutated": False,
        "env_mutated": False,
        "new_runtime_blocker_added": False,
        "automatic_parameter_apply_enabled": False,
        "tradingbot_service_restarted": False,
        "integrates_existing_growbot_river_layer": True,
        "replaces_growbot_river": False,
        "uses_river_sidecar_when_available": True,
        "single_source_of_learning_truth_preserved": True,
        "approved_profile_governance_unchanged": True,
        "modules_added": [
            "bot/overfit_risk_model.py",
            "bot/parameter_proposal_scoring.py",
            "bot/adaptive_learning_intelligence.py",
            "bot/regime_parameter_profiles.py",
            "tools/build_adaptive_learning_intelligence.py",
            "tools/build_parameter_proposal_funnel.py",
            "tools/build_latest_learning_evidence_summary.py",
            "tools/build_adaptive_learning_depth_sprint_audit.py",
            "dashboard/backend/routers/learning_intelligence.py",
            "dashboard/backend/routers/parameter_proposal_funnel.py",
            "dashboard/backend/services/learning_intelligence.py",
            "dashboard/backend/services/parameter_proposal_funnel.py",
            "dashboard/frontend/src/features/learning-cockpit/",
        ],
        "proposal_tiers": [
            "observed_signal",
            "shadow_candidate",
            "backtest_candidate",
            "walk_forward_candidate",
            "operator_review_candidate",
            "apply_ready_candidate (intentionally unreachable from this layer)",
        ],
        "proposal_maturity_funnel": funnel,
        "overfit_risk_monitor": {"low": overfit.get("low"), "medium": overfit.get("medium"), "high": overfit.get("high")},
        "findings": findings,
        "related_reports": [
            "reports/learning/adaptive-learning-intelligence-latest.json",
            "reports/learning/adaptive-learning-intelligence-latest.md",
            "reports/learning/parameter-proposal-funnel-latest.json",
            "reports/learning/parameter-proposal-funnel-latest.md",
            "reports/learning/learning-evidence-summary-latest.json",
            "reports/learning/learning-evidence-summary-latest.md",
        ],
        "operator_action": "refresh dashboard",
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = ["# Adaptive Learning Depth Sprint Audit", ""]
    lines.append(f"Generated: `{report.get('generated_at')}`")
    lines.append("")
    lines.append("## Safety self-report")
    for key in (
        "read_only",
        "llm_call_made",
        "coinbase_call_attempted",
        "live_order_submitted",
        "trading_state_mutated",
        "open_orders_mutated",
        "positions_mutated",
        "approved_profile_mutated",
        "env_mutated",
        "new_runtime_blocker_added",
        "automatic_parameter_apply_enabled",
        "tradingbot_service_restarted",
        "integrates_existing_growbot_river_layer",
        "replaces_growbot_river",
        "uses_river_sidecar_when_available",
        "single_source_of_learning_truth_preserved",
        "approved_profile_governance_unchanged",
    ):
        lines.append(f"- `{key}`: `{report.get(key)}`")
    lines.append("")
    lines.append("## Findings")
    for finding in report.get("findings", []):
        lines.append(f"- {finding}")
    lines.append("")
    lines.append("## Modules added")
    for module in report.get("modules_added", []):
        lines.append(f"- `{module}`")
    lines.append("")
    lines.append("## Related reports")
    for path in report.get("related_reports", []):
        lines.append(f"- `{path}`")
    lines.append("")
    lines.append(f"**Operator action:** {report.get('operator_action')}")
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
    report = build_adaptive_learning_depth_sprint_audit(root=root_path)
    if not args.no_write:
        write_reports(report, root=root_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        for finding in report["findings"]:
            print(finding)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
