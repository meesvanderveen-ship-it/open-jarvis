#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text

DEFAULT_JSON = Path("reports/audits/full-workflow-critical-review-latest.json")
DEFAULT_MD = Path("reports/audits/full-workflow-critical-review-latest.md")

INSPECTED_FILES = [
    "run_trader_loop.py",
    "bot/config.py",
    "bot/strategy_engine.py",
    "bot/market_data.py",
    "bot/indicators.py",
    "bot/chart_patterns.py",
    "bot/orderbook_analyzer.py",
    "bot/prompts.py",
    "bot/execution_planner.py",
    "bot/order_plan.py",
    "bot/phase_c_live_guard.py",
    "bot/phase_c_live_submitter.py",
    "bot/phase_c43_autonomous_entry_live.py",
    "bot/phase_c43_lifecycle_service.py",
    "bot/phase_c43_lifecycle_orchestrator.py",
    "bot/phase_d2_position_executor.py",
    "bot/phase_d3_controlled_live_exits.py",
    "bot/phase_d3_open_exit_lifecycle_manager.py",
    "bot/controlled_stop_market_exit_plan.py",
    "bot/state_store.py",
    "bot/order_store.py",
    "bot/pending_trade_plans.py",
    "bot/pending_order_intents.py",
    "bot/decision_outcome_tracker.py",
    "bot/execution_outcome_tracker.py",
    "bot/trade_reflection.py",
    "bot/live_learning_orchestrator.py",
    "bot/approved_parameter_profile.py",
    "bot/neural_shadow_policy.py",
    "bot/neural_reward_model.py",
    "bot/neural_feature_schema.py",
    "tools/build_live_decision_audit_report.py",
    "tools/show_autonomous_live_run_status.py",
    "tools/show_full_autonomous_run_readiness.py",
    "tools/show_neural_shadow_policy_status.py",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _contains(root: Path, rel: str, *needles: str) -> bool:
    text = _read(root, rel)
    return all(needle in text for needle in needles)


def build_full_workflow_critical_review(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root)
    missing = [rel for rel in INSPECTED_FILES if not (project_root / rel).exists()]
    checks = {
        "A_marketdata_agents_planner_judge_risk_execution_order": _contains(project_root, "bot/strategy_engine.py", "build_trade_planner_input", "_run_trade_planner_with_fallback", "evaluate_phase_c_live_entry_readiness"),
        "B_judge_approve_without_concrete_trade_plan_blocked": _contains(project_root, "bot/strategy_engine.py", "approve_trade_blocked_because_trade_plan_is_no_plan"),
        "C_no_plan_can_still_be_too_fast": True,
        "D_objective_score_visible_in_prompt": _contains(project_root, "bot/prompts.py", "objective_score"),
        "E_orderbook_execution_risk_context": _contains(project_root, "bot/phase_c_live_guard.py", "orderbook_summary", "orderbook_freshness"),
        "F_pending_plans_intents_safe_context": _contains(project_root, "bot/strategy_engine.py", "pending_trade_plan", "pending_order_intent"),
        "G_fills_connected_to_position_opening": _contains(project_root, "bot/phase_c43_autonomous_entry_live.py", "filled_to_position", "create_position"),
        "H_d2_d3_connected_to_open_positions": _contains(project_root, "bot/phase_d3_controlled_live_exits.py", "build_multi_exit_bracket_lite_plan", "selected_exit_intent"),
        "I_partial_exits_safe": _contains(project_root, "bot/phase_d3_controlled_live_exits.py", "exit_quote_below_min_live_order_quote"),
        "J_stop_exit_without_market_order": _contains(project_root, "bot/controlled_stop_market_exit_plan.py", "near_market_limit_ioc", "no_market_orders"),
        "K_market_orders_blocked": _contains(project_root, "bot/config.py", "MARKET_ORDER_ENABLED", "ALLOW_MARKET_ORDERS") and _contains(project_root, "bot/prompts.py", "Do not allow market orders."),
        "L_neural_shadow_soft_only": _contains(project_root, "bot/neural_shadow_policy.py", "execution_allowed", "shadow_only"),
        "M_one_class_passivity_warning": _contains(project_root, "bot/neural_shadow_policy.py", "neural_shadow_one_class_passivity_bias"),
        "N_backtesting_learning_approved_profile_connected": (project_root / "tools/summarize_backtest_parameter_candidates.py").exists(),
        "O_research_backtest_candidate_route": (project_root / "tools/build_research_prior_parameter_profile.py").exists() and (project_root / "tools/run_historical_parameter_backtest.py").exists(),
        "P_readiness_status_extended": _contains(project_root, "tools/show_full_autonomous_run_readiness.py", "live_order_size_policy", "bounded_exploration", "neural_shadow_passivity"),
    }
    safety_blockers = []
    if missing:
        safety_blockers.append("review_missing_expected_files:" + ",".join(missing))
    if not checks["K_market_orders_blocked"]:
        safety_blockers.append("market_order_block_not_verifiable")
    passivity_findings = [
        "recent audit showed approve_trade=0 and all reviewed tickers ended wait",
        "no_plan/wait remains a performance risk if planner does not produce prepare_buy for positive-EV defined-risk setups",
        "one-class prefer_no_trade neural data can reinforce passivity unless treated as weak shadow context",
    ]
    recommended_patch_scope = [
        "research_prior_parameter_profile",
        "btc_eth_historical_parameter_backtest",
        "approved_profile_candidate_from_backtest",
        "readiness_sections_for_research_and_backtest_bridge",
        "workflow_review_report",
    ]
    critical_findings = []
    if checks["C_no_plan_can_still_be_too_fast"]:
        critical_findings.append({
            "severity": "medium",
            "finding": "no_plan remains the main performance/passivity failure mode",
            "mitigation": "prompt handoff and backtest/live-learning candidate loop",
        })
    return {
        "generated_at": generated_at or _now_iso(),
        "read_only_review_first": True,
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "service_touched": False,
        "workflow_ok": not safety_blockers,
        "critical_findings": critical_findings,
        "patch_required": True,
        "recommended_patch_scope": recommended_patch_scope,
        "safety_blockers": safety_blockers,
        "passivity_findings": passivity_findings,
        "learning_parameter_connection": {
            "current": "live learning and backlearning are report/approved-profile-context only",
            "target": "research/backtest -> parameter candidate -> exact-hash operator review -> live run -> live fills/no-fills/outcomes refine future candidates",
            "direct_live_mutation_allowed": False,
        },
        "checks": checks,
        "inspected_files": INSPECTED_FILES,
        "missing_files": missing,
    }


def _markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Full Workflow Critical Review",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Workflow OK: `{report['workflow_ok']}`",
        f"- Safety blockers: `{len(report['safety_blockers'])}`",
        "- Read-only: no Coinbase calls, no state writes, no env writes, no service lifecycle.",
        "",
        "## A-P Checks",
        "",
    ]
    labels = {
        "A_marketdata_agents_planner_judge_risk_execution_order": "A. marketdata -> agents -> planner -> judge -> risk -> execution order",
        "B_judge_approve_without_concrete_trade_plan_blocked": "B. judge approve without concrete trade_plan blocked",
        "C_no_plan_can_still_be_too_fast": "C. no_plan can still be too fast",
        "D_objective_score_visible_in_prompt": "D. objective_score visible",
        "E_orderbook_execution_risk_context": "E. orderbook execution/risk context",
        "F_pending_plans_intents_safe_context": "F. pending plans/intents safe",
        "G_fills_connected_to_position_opening": "G. fills connected to position opening",
        "H_d2_d3_connected_to_open_positions": "H. D2/D3 connected",
        "I_partial_exits_safe": "I. partial exits safe",
        "J_stop_exit_without_market_order": "J. stop-exit without market order",
        "K_market_orders_blocked": "K. market orders blocked",
        "L_neural_shadow_soft_only": "L. neural shadow soft only",
        "M_one_class_passivity_warning": "M. one-class passivity warning",
        "N_backtesting_learning_approved_profile_connected": "N. backtesting/learning/profile connected",
        "O_research_backtest_candidate_route": "O. research/backtest/candidate route",
        "P_readiness_status_extended": "P. readiness/status extended",
    }
    for key, value in report["checks"].items():
        lines.append(f"- {labels.get(key, key)}: `{value}`")
    lines.extend(["", "## Passivity Findings", ""])
    lines.extend(f"- {item}" for item in report["passivity_findings"])
    lines.extend(["", "## Recommended Patch Scope", ""])
    lines.extend(f"- `{item}`" for item in report["recommended_patch_scope"])
    lines.append("")
    return "\n".join(lines)


def _assert_audit_path(path: Path) -> Path:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/audits").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/audits")
    return target


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only full workflow critical review.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_full_workflow_critical_review(root=args.root)
    atomic_write_json(_assert_audit_path(Path(args.json_out)), report)
    atomic_write_text(_assert_audit_path(Path(args.md_out)), _markdown(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "workflow_ok": report["workflow_ok"], "safety_blockers": report["safety_blockers"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_full_workflow_critical_review", "main", "parse_args"]
