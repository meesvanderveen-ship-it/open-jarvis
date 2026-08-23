from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.full_bot_failure_determination_matrix import (
    CONFIGURED_USDC_TICKERS,
    load_json_file,
    load_latest_report,
)
from bot.full_bot_maker_buy_live_adapter import EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK
from bot.full_bot_orchestrator import ORCHESTRATOR_POLICY, FUTURE_ACKS, sha256_file


FULL_BOT_WORKFLOW_COMPLETENESS_AUDIT_PHASE = "full_bot_workflow_completeness_audit_v1"

REQUIRED_MODULES = {
    "d6_multi_order_intent_preview": "bot/phase_d6_multi_order_intent_preview.py",
    "full_bot_orchestrator": "bot/full_bot_orchestrator.py",
    "full_bot_maker_buy_live_adapter": "bot/full_bot_maker_buy_live_adapter.py",
    "full_bot_near_miss_phase_c_review": "bot/full_bot_near_miss_phase_c_review.py",
    "full_bot_failure_determination_matrix": "bot/full_bot_failure_determination_matrix.py",
    "phase_c_guard": "bot/phase_c_live_guard.py",
    "phase_c_submitter": "bot/phase_c_live_submitter.py",
    "d2_position_executor": "bot/phase_d2_position_executor.py",
    "d3_controlled_exit": "bot/phase_d3_controlled_live_exits.py",
    "d3_open_exit_lifecycle_manager": "bot/phase_d3_open_exit_lifecycle_manager.py",
    "d4_cancel_replace": "bot/phase_d3_cancel_replace_pilot.py",
    "open_order_lifecycle": "bot/phase_c43_lifecycle_service.py",
    "c45_fill_apply": "bot/phase_c45_live_fill_pilot.py",
    "controlled_learning_governance": "bot/phase_controlled_learning_governance.py",
}

OPTIONAL_MODULES = {
    "fresh_phase_c_evidence_builder": "bot/full_bot_fresh_phase_c_evidence.py",
}

REQUIRED_TOOLS = {
    "d6_multi_order_intent_preview": "tools/build_d6_multi_order_intent_preview.py",
    "full_bot_orchestrator": "tools/build_full_bot_orchestrator_report.py",
    "full_bot_maker_buy_live_adapter": "tools/build_full_bot_maker_buy_live_adapter_report.py",
    "full_bot_near_miss_phase_c_review": "tools/build_full_bot_near_miss_phase_c_review.py",
    "full_bot_failure_determination_matrix": "tools/build_full_bot_failure_determination_matrix.py",
    "open_orders_readonly": "tools/show_open_orders.py",
    "function_preservation_audit": "tools/show_function_preservation_audit.py",
}

OPTIONAL_TOOLS = {
    "fresh_phase_c_evidence_builder": "tools/build_full_bot_fresh_phase_c_evidence.py",
}

REQUIRED_TESTS = {
    "d6_multi_order_intent_preview": "tests/test_phase_d6_multi_order_intent_preview.py",
    "full_bot_orchestrator": "tests/test_full_bot_orchestrator.py",
    "full_bot_maker_buy_live_adapter": "tests/test_full_bot_maker_buy_live_adapter.py",
    "full_bot_near_miss_phase_c_review": "tests/test_full_bot_near_miss_phase_c_review.py",
    "full_bot_failure_determination_matrix": "tests/test_full_bot_failure_determination_matrix.py",
    "full_bot_workflow_completeness_audit": "tests/test_full_bot_workflow_completeness_audit.py",
}

OPTIONAL_TESTS = {
    "fresh_phase_c_evidence_builder": "tests/test_full_bot_fresh_phase_c_evidence.py",
}

DOCS = {
    "project_context": "docs/CODEX_PROJECT_CONTEXT.md",
    "full_bot_orchestrator": "docs/FULL_BOT_ORCHESTRATOR.md",
    "full_bot_failure_determination": "docs/FULL_BOT_FAILURE_DETERMINATION.md",
    "operator_24h_runbook": "docs/OPERATOR_24H_LIVE_TEST_RUNBOOK.md",
}

REPORT_PATTERNS = {
    "d6_multi_order_intent_preview": "d6-multi-order-intent-preview-calibrated-*.json",
    "full_bot_orchestrator": "full-bot-orchestrator-*.json",
    "full_bot_maker_buy_live_adapter": "full-bot-maker-buy-live-adapter-*.json",
    "full_bot_near_miss_phase_c_review": "full-bot-near-miss-phase-c-review-*.json",
    "full_bot_failure_determination_matrix": "full-bot-failure-determination-matrix-*.json",
    "fresh_phase_c_evidence": "full-bot-fresh-phase-c-evidence-*.json",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return value


def _presence(root: Path, mapping: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name, rel in mapping.items():
        path = root / rel
        out[name] = {"path": rel, "present": path.exists()}
    return out


def _latest_reports(root: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    presence: Dict[str, Dict[str, Any]] = {}
    payloads: Dict[str, Dict[str, Any]] = {}
    for name, pattern in REPORT_PATTERNS.items():
        payload, path = load_latest_report(root, pattern)
        presence[name] = {
            "pattern": f"reports/d6/{pattern}",
            "present": bool(path),
            "path": str(path) if path else "",
        }
        payloads[name] = payload
    return presence, payloads


def _orders(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    orders = raw.get("orders") if isinstance(raw, dict) else {}
    if isinstance(orders, dict):
        return [x for x in orders.values() if isinstance(x, dict)]
    if isinstance(orders, list):
        return [x for x in orders if isinstance(x, dict)]
    return []


def _positions(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(v, ticker=k) for k, v in (raw or {}).items() if isinstance(v, dict)]


def _open_order_count(open_orders_state: Dict[str, Any]) -> int:
    final = {"filled", "done", "completed", "cancelled", "canceled", "expired", "failed", "rejected", "submit_rejected", "replaced"}
    count = 0
    for order in _orders(open_orders_state):
        status = str(order.get("status") or order.get("order_status") or "").strip().lower()
        if status and status not in final:
            count += 1
    return count


def _open_position_count(positions_state: Dict[str, Any]) -> int:
    count = 0
    for pos in _positions(positions_state):
        status = str(pos.get("status") or "").strip().lower()
        base = str(pos.get("position_size_base") or pos.get("bot_managed_base") or pos.get("size_base") or "0")
        if status not in {"closed", "closed_tiny_residual"} and base not in {"", "0", "0.0", "0.00000000"}:
            count += 1
    return count


def _open_d3_exit_count(open_orders_state: Dict[str, Any]) -> int:
    count = 0
    for order in _orders(open_orders_state):
        side = str(order.get("side") or "").upper()
        label = str(order.get("label") or order.get("exit_label") or order.get("order_role") or "").upper()
        status = str(order.get("status") or order.get("order_status") or "").lower()
        if side == "SELL" and ("TP" in label or "EXIT" in label or "D3" in label) and status not in {"filled", "cancelled", "canceled", "expired", "rejected", "replaced"}:
            count += 1
    return count


def _module_missing(presence: Dict[str, Dict[str, Any]]) -> List[str]:
    return [name for name, item in presence.items() if not item.get("present")]


def _section(name: str, *, present: bool, connected: bool, status: str, blockers: Optional[List[str]] = None, next_fix: str = "") -> Dict[str, Any]:
    return {
        "name": name,
        "present": bool(present),
        "connected": bool(connected),
        "status": status,
        "blockers": blockers or [],
        "next_fix": next_fix,
    }


def _todo(priority: str, item: str, evidence: str, next_fix: str) -> Dict[str, str]:
    return {"priority": priority, "item": item, "evidence": evidence, "next_fix": next_fix}


def build_full_bot_workflow_completeness_audit(
    *,
    root: str | Path = ".",
    open_orders_state: Optional[Dict[str, Any]] = None,
    positions_state: Optional[Dict[str, Any]] = None,
    report_payloads: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    root_path = Path(root)
    modules = _presence(root_path, REQUIRED_MODULES)
    optional_modules = _presence(root_path, OPTIONAL_MODULES)
    tools = _presence(root_path, REQUIRED_TOOLS)
    optional_tools = _presence(root_path, OPTIONAL_TOOLS)
    tests = _presence(root_path, REQUIRED_TESTS)
    optional_tests = _presence(root_path, OPTIONAL_TESTS)
    docs = _presence(root_path, DOCS)
    report_presence, latest_payloads = _latest_reports(root_path)
    payloads = {**latest_payloads, **(report_payloads or {})}

    open_orders_path = root_path / "state/open_orders.json"
    positions_path = root_path / "state/positions.json"
    open_orders = open_orders_state if open_orders_state is not None else load_json_file(open_orders_path)
    positions = positions_state if positions_state is not None else load_json_file(positions_path)
    hashes = {}
    for path in (open_orders_path, positions_path):
        if path.exists():
            hashes[str(path)] = sha256_file(path)

    open_orders_count = _open_order_count(open_orders)
    open_positions_count = _open_position_count(positions)
    open_d3_exit_count = _open_d3_exit_count(open_orders)

    failure = payloads.get("full_bot_failure_determination_matrix") or {}
    failure_summary = failure.get("summary") if isinstance(failure.get("summary"), dict) else {}
    adapter = payloads.get("full_bot_maker_buy_live_adapter") or {}
    orchestrator = payloads.get("full_bot_orchestrator") or {}
    review = payloads.get("full_bot_near_miss_phase_c_review") or {}

    any_phase_c_ready = bool(failure_summary.get("any_ticker_phase_c_ready_now"))
    phase_c_ready_tickers = failure_summary.get("phase_c_ready_tickers") or []
    p0_safety_from_matrix = failure_summary.get("all_p0_items") or []
    fresh_judge_candidates = failure_summary.get("top_all_ticker_fresh_judge_candidates") or []
    deterministic_risk_candidates = failure_summary.get("top_all_ticker_deterministic_risk_candidates") or []
    refresh_candidates = failure_summary.get("top_all_ticker_refresh_candidates") or []

    missing_required_modules = _module_missing(modules)
    missing_required_tools = _module_missing(tools)
    missing_required_tests = _module_missing(tests)
    missing_docs = _module_missing(docs)

    p0: List[Dict[str, str]] = []
    if p0_safety_from_matrix:
        p0.append(_todo("P0", "Resolve hard safety blockers in failure matrix", str(p0_safety_from_matrix), "Keep live submit blocked until matrix P0 list is empty."))
    if open_d3_exit_count:
        p0.append(_todo("P0", "Do not start maker BUY sprint while D3 exit is open", f"open_d3_exit={open_d3_exit_count}", "Return to D3 lifecycle runbook and require exact ACK for any lifecycle branch."))

    p1: List[Dict[str, str]] = []
    if fresh_judge_candidates:
        p1.append(_todo("P1", "Provide fresh Phase-C BUY judge approval for selected candidates", str(fresh_judge_candidates), "Build/run fresh evidence for one current maker BUY candidate, then rerun near-miss review and adapter preview."))
    if deterministic_risk_candidates:
        p1.append(_todo("P1", "Provide deterministic live-risk approval for selected candidates", str(deterministic_risk_candidates), "Generate exact candidate live-risk evidence before any ACK-gated actual submit."))
    if refresh_candidates:
        p1.append(_todo("P1", "Refresh stale/cap-hidden D6 candidates", str(refresh_candidates), "Refresh candidate data and rerun D6 preview, orchestrator, adapter, near-miss review and matrix."))
    if not any_phase_c_ready:
        p1.append(_todo("P1", "Do not submit until a Phase-C-ready candidate exists", "any_ticker_phase_c_ready_now=false", "Create fresh candidate evidence and verify Phase-C guard passes in preview."))

    p2 = [
        _todo("P2", "Keep live caps unchanged for multi-order runs", "max_new_orders_per_cycle=2, max_open_orders_total=5, max_open_orders_per_ticker=1", "Use diagnostics to inspect cap-hidden tickers; do not widen caps without separate parameter/governance ACK."),
    ]
    p3 = [
        _todo("P3", "Keep SELL/exits disabled until a new position exists and D2/D3/D4 are revalidated", f"open_positions={open_positions_count}, open_d3_exit={open_d3_exit_count}", "Future SELL enablement requires separate D2 plan, D3 preview, oversell/duplicate/reservation checks and exact ACK."),
    ]
    p4 = [
        _todo("P4", "Keep market orders disabled", "market_orders_enabled=false", "Add taker-fee, slippage, spread/depth and emergency policy before any market-order ACK path."),
    ]
    p5 = [
        _todo("P5", "Keep learning/replication report-only", "learning_to_execution=false, replication=false", "Require separate evidence sufficiency, receiver/API audit and exact ACK before live linkage."),
    ]

    if missing_required_modules or missing_required_tools or missing_required_tests:
        classification = "incomplete_due_missing_module_tool_or_test"
        readiness_verdict = "blocked_by_missing_module_or_tool"
    elif p0:
        classification = "unsafe_or_safety_blocked"
        readiness_verdict = "blocked_by_safety_gap"
    elif fresh_judge_candidates or deterministic_risk_candidates:
        classification = "mostly_complete_but_blocked_by_fresh_evidence"
        readiness_verdict = "blocked_by_missing_fresh_judge_and_risk"
    elif refresh_candidates or not any_phase_c_ready:
        classification = "mostly_complete_but_blocked_by_fresh_evidence"
        readiness_verdict = "blocked_by_missing_fresh_candidate_refresh"
    else:
        classification = "ready_for_next_ack_gated_maker_buy_live_sprint"
        readiness_verdict = "ready_for_ack_gated_maker_buy_live_submit"

    if fresh_judge_candidates or deterministic_risk_candidates:
        exact_next_codex_task = (
            "Build or provide report-only fresh Phase-C judge and deterministic live-risk evidence for one current maker BUY "
            "candidate, then rerun near-miss review, maker BUY adapter preview and failure matrix; do not run actual submit."
        )
    elif refresh_candidates or not any_phase_c_ready:
        exact_next_codex_task = (
            "Refresh D.6 candidate evidence for current market data, rerun orchestrator, maker BUY adapter preview, "
            "near-miss review and failure matrix, then rerun this audit; do not run actual submit."
        )
    elif readiness_verdict == "ready_for_ack_gated_maker_buy_live_submit":
        exact_next_codex_task = (
            "Prepare an operator review packet for the Phase-C-ready maker BUY candidate and wait for exact ACK before any "
            "actual submit command."
        )
    else:
        exact_next_codex_task = (
            "Resolve missing module/tool/test or P0 safety blocker, rerun focused tests and rebuild the audit; do not run "
            "actual submit."
        )

    workflow_sections = [
        _section("A_entry_candidate_pipeline", present=True, connected=not (missing_required_modules or missing_required_tools), status="present_but_needs_fresh_evidence" if not any_phase_c_ready else "phase_c_ready_candidate_available", blockers=[x["item"] for x in p1], next_fix="Refresh D6 and provide fresh judge/risk evidence."),
        _section("B_live_buy_maker_path", present=modules["full_bot_maker_buy_live_adapter"]["present"], connected=True, status="default_off_ack_gated", blockers=[] if any_phase_c_ready else ["no_phase_c_ready_candidate"], next_fix="Use preview command first; actual submit only after exact ACK and passing Phase-C guard."),
        _section("C_sell_exit_workflow", present=True, connected=True, status="disabled_no_open_position", blockers=["live_exits_disabled", "d3_actual_exit_submit_disabled"], next_fix="Keep disabled until a new position exists and separate ACK is given."),
        _section("D_market_order_workflow", present=True, connected=True, status="preview_only_disabled", blockers=["market_orders_disabled"], next_fix="Define taker/slippage/depth policy before support."),
        _section("E_lifecycle_fill_workflow", present=True, connected=True, status="no_pending_apply", blockers=[] if open_orders_count == 0 else ["open_order_lifecycle_requires_trigger"], next_fix="Future fill apply requires valid evidence and exact ACK."),
        _section("F_learning_performance_workflow", present=True, connected=False, status="observe_report_only", blockers=["learning_to_execution_disabled", "parameter_mutation_disabled"], next_fix="Keep review-only until separate parameter governance."),
        _section("G_replication_follower_workflow", present=True, connected=False, status="disabled_not_required", blockers=["replication_disabled"], next_fix="Follower/API audit before any live replication."),
        _section("H_tests_reports", present=not missing_required_tests, connected=True, status="focused_tests_defined", blockers=missing_required_tests, next_fix="Run focused tests and py_compile."),
        _section("I_docs_runbooks", present=not missing_docs, connected=True, status="runbooks_present", blockers=missing_docs, next_fix="Add next live sprint section if ACK sprint proceeds."),
    ]

    all_todos = p0 + p1 + p2 + p3 + p4 + p5
    report = {
        "generated_at": now_iso(),
        "phase": FULL_BOT_WORKFLOW_COMPLETENESS_AUDIT_PHASE,
        "status": "workflow_completeness_audit_built",
        "classification": classification,
        "report_only": True,
        "live_order_submit_attempted": False,
        "coinbase_write_attempted": False,
        "state_write_performed": False,
        "workflow_sections": workflow_sections,
        "module_presence": {**modules, **{f"optional_{k}": v for k, v in optional_modules.items()}},
        "tool_presence": {**tools, **{f"optional_{k}": v for k, v in optional_tools.items()}},
        "test_presence": {**tests, **{f"optional_{k}": v for k, v in optional_tests.items()}},
        "report_artifact_presence": report_presence,
        "schema_connectivity": {
            "d6_to_orchestrator": bool(orchestrator.get("d6_preview_summary") or orchestrator.get("entry_action_candidates")),
            "orchestrator_to_adapter": bool(adapter.get("source_report_paths") or adapter.get("selected_entry_candidates") is not None),
            "adapter_to_near_miss_review": bool(review.get("fresh_review_results") is not None or report_presence["full_bot_near_miss_phase_c_review"]["present"]),
            "near_miss_review_to_failure_matrix": bool(failure.get("matrix")),
            "failure_matrix_to_audit": bool(failure_summary),
        },
        "safety_gate_status": {
            "open_orders": open_orders_count,
            "open_positions": open_positions_count,
            "open_d3_exit": open_d3_exit_count,
            "buy_only_for_next_sprint": True,
            "maker_limit_only": True,
            "post_only_required": True,
            "sell_enabled": False,
            "market_orders_enabled": False,
            "live_exits_enabled": False,
            "d3_actual_exit_submit_enabled": False,
            "replication_enabled": False,
            "learning_to_execution_enabled": False,
            "parameter_mutation_enabled": False,
            "exact_maker_buy_ack": EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
        },
        "entry_pipeline_status": workflow_sections[0],
        "maker_buy_live_path_status": workflow_sections[1],
        "sell_exit_path_status": workflow_sections[2],
        "market_order_path_status": workflow_sections[3],
        "lifecycle_path_status": workflow_sections[4],
        "learning_path_status": workflow_sections[5],
        "replication_path_status": workflow_sections[6],
        "docs_runbook_status": workflow_sections[8],
        "open_todo_items": all_todos,
        "p0_safety_gaps": p0,
        "p1_first_live_buy_blockers": p1,
        "p2_multi_order_blockers": p2,
        "p3_sell_exit_blockers": p3,
        "p4_market_order_blockers": p4,
        "p5_learning_replication_blockers": p5,
        "readiness_verdict": readiness_verdict,
        "phase_c_ready_tickers_now": phase_c_ready_tickers,
        "any_ticker_phase_c_ready_now": any_phase_c_ready,
        "first_real_maker_buy_live_submit_allowed_now": readiness_verdict == "ready_for_ack_gated_maker_buy_live_submit",
        "sell_market_should_remain_disabled": True,
        "exact_next_codex_task": exact_next_codex_task,
        "exact_next_operator_command_preview": "python3 tools/build_full_bot_maker_buy_live_adapter_report.py --json-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).json --markdown-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).md",
        "exact_next_operator_command_actual_submit_if_ready": (
            "DO NOT RUN NOW. Only after fresh Phase-C-ready candidate and exact ACK: "
            "python3 tools/build_full_bot_maker_buy_live_adapter_report.py --actual-submit --ack "
            f"{EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK} "
            "--json-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).json "
            "--markdown-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).md"
        ),
        "state_hashes": hashes,
        "policy_snapshot": {
            "orchestrator_policy": ORCHESTRATOR_POLICY,
            "future_acks": FUTURE_ACKS,
        },
        "root_cause_counts": failure_summary.get("count_by_root_cause_category") or {},
        "priority_counts": failure_summary.get("count_by_priority") or {},
    }
    return json_safe(report)


def render_full_bot_workflow_completeness_audit_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Full Bot Workflow Completeness Audit v1",
        "",
        "Report-only workflow audit. It does not submit orders, call Coinbase write endpoints, mutate config or write trading state.",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- readiness_verdict: `{report.get('readiness_verdict')}`",
        f"- report_only: `{report.get('report_only')}`",
        f"- live_order_submit_attempted: `{report.get('live_order_submit_attempted')}`",
        f"- coinbase_write_attempted: `{report.get('coinbase_write_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- any_ticker_phase_c_ready_now: `{report.get('any_ticker_phase_c_ready_now')}`",
        f"- first_real_maker_buy_live_submit_allowed_now: `{report.get('first_real_maker_buy_live_submit_allowed_now')}`",
        f"- sell_market_should_remain_disabled: `{report.get('sell_market_should_remain_disabled')}`",
        "",
        "## Safety Gate Status",
        "",
        "```json",
        json.dumps(report.get("safety_gate_status") or {}, indent=2, sort_keys=True),
        "```",
        "",
        "## Workflow Sections",
        "",
        "```json",
        json.dumps(report.get("workflow_sections") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Ordered To-Do",
        "",
        "```json",
        json.dumps(report.get("open_todo_items") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## P0/P1/P2/P3/P4/P5",
        "",
        f"- P0: `{report.get('p0_safety_gaps')}`",
        f"- P1: `{report.get('p1_first_live_buy_blockers')}`",
        f"- P2: `{report.get('p2_multi_order_blockers')}`",
        f"- P3: `{report.get('p3_sell_exit_blockers')}`",
        f"- P4: `{report.get('p4_market_order_blockers')}`",
        f"- P5: `{report.get('p5_learning_replication_blockers')}`",
        "",
        "## Commands",
        "",
        f"- next Codex task: `{report.get('exact_next_codex_task')}`",
        f"- preview: `{report.get('exact_next_operator_command_preview')}`",
        f"- actual submit: `{report.get('exact_next_operator_command_actual_submit_if_ready')}`",
        "",
        "## State Hashes",
        "",
        "```json",
        json.dumps(report.get("state_hashes") or {}, indent=2, sort_keys=True),
        "```",
        "",
        "## Presence",
        "",
        "```json",
        json.dumps(
            {
                "modules": report.get("module_presence"),
                "tools": report.get("tool_presence"),
                "tests": report.get("test_presence"),
                "reports": report.get("report_artifact_presence"),
            },
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "FULL_BOT_WORKFLOW_COMPLETENESS_AUDIT_PHASE",
    "build_full_bot_workflow_completeness_audit",
    "render_full_bot_workflow_completeness_audit_markdown",
]
