#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from tools.show_workflow_runtime_funnel import build_runtime_funnel

DEFAULT_JSON = Path("reports/audits/full-workflow-integrity-audit-latest.json")
DEFAULT_MD = Path("reports/audits/full-workflow-integrity-audit-latest.md")


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _text(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _stage(
    workflow_stage: str,
    intended_function: str,
    entrypoint: str,
    called_by: str,
    calls: List[str],
    state_inputs: List[str],
    state_outputs: List[str],
    logs_written: List[str],
    safety_gates: List[str],
    live_coinbase_possible: bool,
    currently_reachable: bool,
    test_coverage: str,
    known_risk: str,
    status: str,
) -> Dict[str, Any]:
    return locals()


def build_workflow_map(root: str | Path = ".") -> List[Dict[str, Any]]:
    root = Path(root)
    return [
        _stage("marketdata/context", "Fetch candles/orderbook/news/feature pack.", "bot/market_data.py", "run_trader_loop.py -> bot/strategy_engine.py", ["CoinbaseClient.get_product_book", "indicators", "market_intelligence_context"], ["Coinbase public/auth read endpoints"], ["analysis feature_pack"], ["logs/analysis.jsonl"], ["read-only fetch errors are non-fatal"], False, _exists(root, "bot/market_data.py"), "tests/test_coinbase_orderbook_context.py", "Read failures can degrade orderbook precision context.", "ok"),
        _stage("ranking/preselectie", "Rank candidates before expensive analysis.", "bot/strategy_engine.py", "StrategyEngine cycle", ["preselection_calibration", "DeepSeek optional gate"], ["allowed tickers", "market snapshots"], ["candidate list"], ["logs/cycle_summary.jsonl"], ["max_candidates caps"], False, "enable_candidate_ranking" in _text(root, "bot/config.py"), "tests/test_preselection_calibration.py", "Ranking drop-off visibility is audit-only.", "needs_test"),
        _stage("analysis/LLM/judge", "Build analysis, planner input and final judge.", "bot/strategy_engine.py", "run_cycle_full_analysis", ["bot/prompts.py", "llm_clients", "execution_planner"], ["feature_pack", "learning context", "pending intents"], ["judge", "trade_plan", "execution_plan"], ["logs/llm_raw.jsonl", "logs/analysis.jsonl", "logs/decision_outcomes.jsonl"], ["schema validation", "ticker match", "final judge"], False, "final_judge" in _text(root, "bot/strategy_engine.py"), "tests/test_final_judge_schema_contract.py tests/test_judge_funnel_audit.py", "Provider fallback/schema failures are logged but can stop candidate progression.", "ok"),
        _stage("tradeplan", "Turn approved/wait setup into structured entry/exit intent.", "bot/order_plan.py bot/execution_planner.py", "strategy_engine", ["build order plan", "read-only execution planner"], ["judge/trade_plan"], ["execution_action, size_quote, limit_price"], ["logs/execution_plans.jsonl"], ["BUY-only Phase C guard", "no market unless Mode C"], False, _exists(root, "bot/execution_planner.py"), "tests/test_execution_planner_read_only.py", "Wait plans may be useful but not always persisted as live opportunity memory.", "gap"),
        _stage("opportunity memory/watch", "Remember wait/retest/reclaim opportunities.", "bot/pending_order_intents.py bot/opportunity_memory.py", "strategy_engine / report-only tool", ["build_watchlist_intent_from_analysis", "evaluate_opportunities"], ["analysis", "state/opportunity_memory.json"], ["pending intent context", "trigger_ready promotion preview"], ["logs/pending_order_intents.jsonl"], ["fresh judge/risk required before order", "no live order authorization"], False, True, "tests/test_phase_b7_pending_intent_review_promotion.py tests/test_opportunity_memory.py", "Existing path is paper-intent; new memory POC is not wired into runtime order promotion yet.", "preview_only"),
        _stage("orderbook/resting-entry planning", "Classify wait/setup into maker limit candidate.", "bot/orderbook_entry_planner.py", "phase_c43 risk snapshot", ["build_resting_limit_entry_preview"], ["analysis feature_pack orderbook", "open positions/orders"], ["entry_level", "invalidation_level", "entry_route_type"], ["reports/audits/orderbook-entry-opportunity-audit-latest.json"], ["spread", "distance", "RR", "open ticker duplicate"], False, True, "tests/test_orderbook_entry_planner.py tests/test_orderbook_entry_opportunity_audit.py", "Can allow wait-without-approve when resting entry is eligible; needs precise trigger audit.", "ok"),
        _stage("live BUY limit submit", "Submit post-only BUY limit after deterministic gates.", "bot/phase_c43_autonomous_entry_live.py", "strategy_engine direct bridge", ["phase_c_live_guard", "phase_c_live_submitter", "CoinbaseClient.submit_limit_buy_order"], ["execution_plan", "product_rules", "state/open_orders.json"], ["open order with exchange_order_id only on accepted submit"], ["logs/phase_c_live_submit.jsonl", "logs/order_events.jsonl"], ["actual submit flag", "quote caps", "open-order caps", "post-only", "product precision"], True, True, "tests/test_phase_c43_autonomous_entry_live.py tests/test_phase_c_live_submitter.py", "Recent rejects were product precision/post-only; service restart needed if runtime still old.", "needs_test"),
        _stage("pending-entry lifecycle", "Poll open entry, detect fill/cancel/expire, create position only after fill evidence.", "bot/phase_c43_lifecycle_service.py", "scheduler/service hook", ["phase_c43_lifecycle_orchestrator", "reconcile_phase_c43_fills_to_positions"], ["state/open_orders.json", "Coinbase order snapshot"], ["state positions", "order status"], ["logs/phase_c43_lifecycle_service.jsonl", "logs/phase_c43_fill_reconciliation.jsonl"], ["poll/apply flags", "exchange id required", "fill evidence required"], False, True, "tests/test_phase_c43_lifecycle_service.py tests/test_pending_entry_lifecycle.py", "Cancel/replace for live entries remains governance/report-heavy; no autonomous cancel in this Codex run.", "ok"),
        _stage("D2 exit planning", "Create bracket/runner plan for filled position.", "bot/phase_d2_position_executor.py", "lifecycle orchestrator / position cycle", ["build_phase_d2_position_executor_report"], ["open position", "product rules"], ["D2 plan"], ["reports / order events"], ["protective risk complete", "min quote"], False, True, "tests/test_phase_d2_position_executor.py tests/test_phase_d21_pre_d3_hygiene.py", "Runner/trailing is planned but live trailing is deferred.", "ok"),
        _stage("D3 take-profit exits", "Submit at most one guarded SELL TP from proven base.", "bot/phase_d3_controlled_live_exits.py", "strategy_engine D3 bridge / lifecycle preview", ["live_exit_gate", "OrderStore", "CoinbaseClient.place_limit_order"], ["position", "D2 plan", "exchange_rules"], ["open D3 exit order"], ["logs/phase_d3_controlled_live_exits.jsonl"], ["ACK", "base reservation", "duplicate guard", "oversell guard", "exchange id required"], True, True, "tests/test_phase_d3_controlled_live_exits.py tests/test_phase_d3_open_exit_lifecycle_manager.py", "Spot lacks reduce_only; local reservation and exchange balance evidence remain critical.", "ok"),
        _stage("stop/protective watcher", "Detect stop breach and require cancel-first stop route.", "bot/protective_position_watcher.py bot/controlled_stop_market_exit_plan.py", "status tools / Mode B path", ["reserved_base_for_matching_open_d3_orders"], ["positions", "open D3 exits", "market"], ["preview plan"], ["reports/audits/protective-stop-open-order-workflow-audit-latest.json"], ["Mode B ACK for apply", "no naked sell", "cancel exchange confirmation"], True, True, "tests/test_protective_position_watcher.py tests/test_controlled_stop_market_exit_plan.py", "Mode A remains preview/report-only on stop breach.", "preview_only"),
        _stage("trailing stoploss", "Preview D4 trailing/cancel-replace candidate.", "bot/phase_d4_trailing_preview.py bot/trailing_stop_manager.py", "operator/status tools", ["build_phase_d4_trailing_preview_report", "build_trailing_stop_status"], ["position", "market", "open D3 order"], ["preview candidate"], ["reports/status only"], ["never move stop down", "cancel-first", "future D4 ACK"], False, True, "tests/test_phase_d4_trailing_preview.py tests/test_trailing_stop_manager.py", "Not live-wired; no exchange stop order or autonomous replace loop.", "preview_only"),
        _stage("learning/reflection/governor", "Learn from outcomes without direct execution bridge.", "bot/live_learning_orchestrator.py bot/autonomous_parameter_governor.py", "sidecars/tools", ["reflection", "backlearning", "approved profile tooling"], ["logs/decision_outcomes.jsonl", "research_data"], ["candidate profiles/reports"], ["reports/reflection", "reports/live_learning"], ["exact hash ACK", "no direct bridge"], False, True, "tests/test_live_learning_sidecar.py tests/test_autonomous_parameter_governor.py", "Data quality and overfitting guard remain P2.", "ok"),
        _stage("audit/status/logging", "Expose funnel, lifecycle and safety state.", "tools/show_autonomous_live_run_status.py", "operator", ["judge funnel", "orderbook audit", "runtime funnel"], ["logs/*.jsonl", "state/*.json"], ["reports/audits/*.json"], ["reports/audits/*.md"], ["read-only tools"], False, True, "tests/test_scheduler_cycle_status.py tests/test_full_workflow_integration_contracts.py", "Some reports mix pre/post restart windows; runtime funnel now surfaces attempts.", "ok"),
    ]


def build_backlog(root: str | Path = ".") -> List[Dict[str, Any]]:
    return [
        {"priority": "P0", "title": "Verify deployed runtime uses product-rule precision fix", "risk": "Coinbase rejects every BUY submit with INVALID_PRICE_PRECISION/INVALID_SIZE_PRECISION.", "evidence": "Recent logs show product_rules_used={} and precision rejects; current code/tests block missing increments.", "files": ["bot/phase_c_live_submitter.py", "bot/strategy_engine.py", "logs/phase_c_live_submit.jsonl"], "recommended_fix": "Restart service after tests; rerun funnel after next full cycle.", "tests_needed": ["tests/test_phase_c_live_submitter.py"], "safe_to_patch_now": False, "requires_operator_restart": True, "requires_live_ack": False},
        {"priority": "P0", "title": "No local open-order write without exchange_order_id", "risk": "Lifecycle cannot safely poll or cancel an order without exchange identity.", "evidence": "C43 writes submitted only on accepted response; rejected records are final submit_rejected.", "files": ["bot/phase_c43_autonomous_entry_live.py"], "recommended_fix": "Keep invariant; audit rejected rows separately.", "tests_needed": ["tests/test_phase_c43_autonomous_entry_live.py"], "safe_to_patch_now": False, "requires_operator_restart": False, "requires_live_ack": False},
        {"priority": "P1", "title": "Wire opportunity memory into existing judge/orderbook cadence", "risk": "Good wait setups can be forgotten or only paper-intent visible.", "evidence": "pending_order_intents exists; opportunity_memory POC is report-only.", "files": ["bot/pending_order_intents.py", "bot/opportunity_memory.py"], "recommended_fix": "Promote trigger_ready memory to fresh judge/orderbook input only, never directly to submit.", "tests_needed": ["tests/test_opportunity_memory.py"], "safe_to_patch_now": True, "requires_operator_restart": True, "requires_live_ack": False},
        {"priority": "P1", "title": "Trailing stop remains preview-only", "risk": "Profitable runner has no autonomous ratcheting stop protection.", "evidence": "D3 blocks trailing live submit; D4 preview requires future ACK.", "files": ["bot/phase_d4_trailing_preview.py", "bot/trailing_stop_manager.py"], "recommended_fix": "Build D4 cancel-first replace manager with exchange confirmation and one-replace cadence.", "tests_needed": ["tests/test_trailing_stop_manager.py", "tests/test_phase_d4_trailing_preview.py"], "safe_to_patch_now": True, "requires_operator_restart": True, "requires_live_ack": True},
        {"priority": "P2", "title": "Learning/backtesting data quality", "risk": "Parameter governor may overfit sparse live/no-fill samples.", "evidence": "Decision outcomes include false positives and plan_follow_through labels.", "files": ["bot/autonomous_parameter_governor.py", "reports/reflection"], "recommended_fix": "Require walk-forward/OOS evidence before profile candidate ACK.", "tests_needed": ["tests/test_phase_d6_overfitting_guardrails.py"], "safe_to_patch_now": True, "requires_operator_restart": False, "requires_live_ack": False},
        {"priority": "P3", "title": "Reduce duplicate historical phase tools", "risk": "Operator confusion about active runtime path.", "evidence": "Many phase_c/d tools and reports coexist.", "files": ["tools", "docs"], "recommended_fix": "Document active Mode A/B path and archive obsolete one-shot tools.", "tests_needed": ["tests/test_function_preservation_audit.py"], "safe_to_patch_now": False, "requires_operator_restart": False, "requires_live_ack": False},
    ]


def build_audit(root: str | Path = ".") -> Dict[str, Any]:
    root = Path(root)
    funnel = build_runtime_funnel(root)
    workflow_map = build_workflow_map(root)
    p0 = [x for x in build_backlog(root) if x["priority"] == "P0"]
    return {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "workflow_stage_count": len(workflow_map),
        "workflow_map": workflow_map,
        "runtime_funnel": funnel,
        "live_order_attempts": funnel.get("attempt_rows", []),
        "transition_findings": [
            {"transition": "submit attempt -> exchange accepted order id", "status": "currently failing in latest live evidence", "evidence": funnel.get("reject_reason_counts", {}), "blocker": "precision/post-only rejects until deployed fix and fresh cycle prove acceptance"},
            {"transition": "wait trigger_not_ready -> future promotion", "status": "partial", "evidence": "pending_order_intents exists; opportunity_memory is POC/report-only", "blocker": "not yet first-class runtime memory promotion"},
            {"transition": "D2 runner -> D4 trailing live management", "status": "preview_only", "evidence": "D3 blocks trailing_runner_live_submit_deferred_to_d4", "blocker": "no ACK-gated cancel/replace manager yet"},
        ],
        "safety_rails_intact": ["spot BUY-only entry guard", "quote caps", "max open orders", "post-only entry", "no local position without fill evidence", "D3 duplicate/oversell guards", "Mode B ACK for stop apply", "no learning direct bridge"],
        "p0_p1_p2_p3_backlog": build_backlog(root),
        "readiness": "STATUS B: Workflow mostly ready but P0 submit/order-lifecycle blocker remains.",
        "read_only": True,
        "coinbase_call_attempted_by_tool": False,
    }


def _md(report: Dict[str, Any]) -> str:
    lines = [
        "# Full Workflow Integrity Audit",
        "",
        f"- Readiness: `{report['readiness']}`",
        f"- Workflow stages: `{report['workflow_stage_count']}`",
        f"- Live attempts: `{report['runtime_funnel']['live_submission_attempted_count']}`",
        f"- Live submits: `{report['runtime_funnel']['live_order_submitted_count']}`",
        f"- Reject reasons: `{json.dumps(report['runtime_funnel']['reject_reason_counts'], sort_keys=True)}`",
        "",
        "## Critical Findings",
    ]
    for item in report["transition_findings"]:
        lines.append(f"- `{item['transition']}`: {item['status']} - {item['blocker']}")
    lines.extend(["", "## Backlog"])
    for item in report["p0_p1_p2_p3_backlog"]:
        lines.append(f"- `{item['priority']}` {item['title']}: {item['recommended_fix']}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only full workflow integrity audit.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_audit(args.root)
    atomic_write_json(args.json_out, report)
    atomic_write_text(args.md_out, _md(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "readiness": report["readiness"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
