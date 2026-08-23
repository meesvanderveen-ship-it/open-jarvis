from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_ROADMAP_READINESS_DECISION_MAP = "roadmap_readiness_decision_map_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _route(
    *,
    route: str,
    current_status: str,
    current_decision: str,
    blockers: List[str],
    allowed_next_step: str,
    forbidden_actions: List[str],
    blocks_BTC_24h: bool,
    blocks_full_workflow: bool,
    requires_ACK: bool,
    recommended_priority: str,
) -> Dict[str, Any]:
    return {
        "route": route,
        "current_status": current_status,
        "current_decision": current_decision,
        "blockers": blockers,
        "allowed_next_step": allowed_next_step,
        "forbidden_actions": forbidden_actions,
        "blocks_BTC_24h": blocks_BTC_24h,
        "blocks_full_workflow": blocks_full_workflow,
        "requires_ACK": requires_ACK,
        "recommended_priority": recommended_priority,
        "live_trading_authorized": False,
        "parameter_change_allowed": False,
        "learning_to_execution_ready": False,
    }


def build_roadmap_readiness_decision_map_report(
    *, root: str | Path = ".", generated_at: Optional[str] = None
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    harness = _load_json(project_root / "reports/d6/safe-regression-harness-20260609.json")
    replay = _load_json(project_root / "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json")
    acceptance = _load_json(project_root / "reports/d6/d6-acceptance-policy-20260609.json")
    label_export = _load_json(project_root / "reports/d6/d6-backlearning-label-export-pack-20260609.json")
    controlled = _load_json(project_root / "reports/d6/controlled-learning-governance-20260609.json")
    shadow = _load_json(project_root / "reports/d6/d6-shadow-learning-report-20260609.json")
    prerun = _load_json(project_root / "reports/d6/operator-24h-prerun-build-checklist-20260609.json")
    ledger = _load_json(project_root / "reports/d6/unresolved-blocker-ledger-20260609.json")
    all_ticker_pack = _load_json(project_root / "reports/d6/all-ticker-24h-workflow-readiness-pack-20260609.json")
    all_ticker_commands = _load_json(project_root / "reports/d6/all-ticker-operator-preflight-command-pack-20260609.json")
    all_ticker_guard = _load_json(project_root / "reports/d6/all-ticker-live-scope-guard-20260609.json")
    all_ticker_preflight = _load_json(project_root / "reports/d6/all-ticker-live-readonly-preflight-20260609.json")
    shadow_params = _load_json(project_root / "reports/d6/shadow-parameter-approximation-pack-20260609.json")
    follower = _load_json(project_root / "reports/d6/follower-receiver-api-audit-20260609.json")
    exit_report = _load_json(project_root / "reports/d6/exit-workflow-readiness-report-20260609.json")
    flags = harness.get("readiness_flags") if isinstance(harness.get("readiness_flags"), dict) else {}
    replay_gate = replay.get("gate_decision") if isinstance(replay.get("gate_decision"), dict) else {}
    acceptance_flags = acceptance.get("governance_flags") if isinstance(acceptance.get("governance_flags"), dict) else {}
    label_flags = label_export.get("governance_flags") if isinstance(label_export.get("governance_flags"), dict) else {}
    controlled_flags = controlled.get("governance_flags") if isinstance(controlled.get("governance_flags"), dict) else {}
    shadow_flags = shadow.get("governance_flags") if isinstance(shadow.get("governance_flags"), dict) else {}
    prerun_flags = prerun.get("governance_flags") if isinstance(prerun.get("governance_flags"), dict) else {}
    ledger_flags = ledger.get("governance_flags") if isinstance(ledger.get("governance_flags"), dict) else {}
    all_ticker_gate = (
        all_ticker_pack.get("gate_decision") if isinstance(all_ticker_pack.get("gate_decision"), dict) else {}
    )
    all_ticker_command_flags = (
        all_ticker_commands.get("governance_flags")
        if isinstance(all_ticker_commands.get("governance_flags"), dict)
        else {}
    )
    all_ticker_guard_flags = (
        all_ticker_guard.get("governance_flags")
        if isinstance(all_ticker_guard.get("governance_flags"), dict)
        else {}
    )
    all_ticker_preflight_gate = (
        all_ticker_preflight.get("gate_decision")
        if isinstance(all_ticker_preflight.get("gate_decision"), dict)
        else {}
    )
    shadow_param_flags = (
        shadow_params.get("governance_flags")
        if isinstance(shadow_params.get("governance_flags"), dict)
        else {}
    )
    follower_flags = follower.get("readiness_flags") if isinstance(follower.get("readiness_flags"), dict) else {}
    btc_monitor_test_present = (project_root / "tests/test_btc_usdc_24h_monitor.py").exists()

    routes = [
        _route(
            route="evidence_to_human_review",
            current_status="ready_report_only",
            current_decision="allowed_report_only",
            blockers=["does not authorize parameter proposal", "does not authorize execution"],
            allowed_next_step="Continue human-review evidence classification using local reports only.",
            forbidden_actions=["propose parameter values", "mutate parameters", "connect learning to execution"],
            blocks_BTC_24h=False,
            blocks_full_workflow=False,
            requires_ACK=False,
            recommended_priority="high",
        ),
        _route(
            route="human_review_to_parameter_review_candidate",
            current_status="blocked",
            current_decision="blocked",
            blockers=["parameter_review_candidate=false", "sample-size/OOS/walk-forward sufficiency ledger not accepted"],
            allowed_next_step="Build a report-only policy sufficiency ledger; do not promote candidate status.",
            forbidden_actions=["approve parameter review", "propose parameter values", "optimize"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="high",
        ),
        _route(
            route="parameter_review_to_parameter_proposal",
            current_status="blocked",
            current_decision="blocked",
            blockers=["parameter_review_candidate=false", "explicit proposal ACK missing"],
            allowed_next_step="No action now; wait for a separate ACK-gated parameter proposal sprint.",
            forbidden_actions=["propose parameter values", "rank strategies for live use"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="blocked",
        ),
        _route(
            route="parameter_proposal_to_parameter_change",
            current_status="blocked_by_ACK",
            current_decision="blocked_by_ACK",
            blockers=["parameter_values_proposed=false", "parameter_review_approved=false", "exact parameter-change ACK missing"],
            allowed_next_step="No parameter change; future change requires exact before/after diff and ACK.",
            forbidden_actions=["mutate config", "mutate prompts/risk thresholds", "edit runtime parameters"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="blocked",
        ),
        _route(
            route="parameter_change_to_shadow_learning",
            current_status="ready_report_only_no_execution_bridge" if shadow_flags.get("report_only_shadow_learning_ready") else "blocked",
            current_decision="allowed_report_only" if shadow_flags.get("report_only_shadow_learning_ready") else "blocked",
            blockers=["parameter_change_allowed=false", "execution_bridge_created=false", "learning_to_execution_ready=false"],
            allowed_next_step="Use shadow learning report only as isolated offline design; do not create execution bridge.",
            forbidden_actions=["write learned parameters", "drive runtime decisions", "start learning process"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="medium",
        ),
        _route(
            route="shadow_learning_to_execution_bridge",
            current_status="blocked",
            current_decision="blocked",
            blockers=["execution_bridge_candidate=false", "learning_to_execution_ready=false"],
            allowed_next_step="Keep execution bridge absent.",
            forbidden_actions=["connect labels to order decisions", "enable learning-to-execution"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="blocked",
        ),
        _route(
            route="execution_bridge_to_live_learning",
            current_status="blocked",
            current_decision="blocked",
            blockers=["live_learning_allowed=false", "live_learning_candidate=false", "exact ACK missing"],
            allowed_next_step="None; live learning remains forbidden.",
            forbidden_actions=["enable live learning", "start live learning", "rank strategies for live deployment"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="blocked",
        ),
        _route(
            route="BTC-USDC 24h live-start decision",
            current_status="blocked_by_ACK_possible_if_operator_explicitly_asks",
            current_decision="blocked_by_ACK",
            blockers=["fresh operator preflight not run", "exact live-start ACK missing", "operator_manual_start_required=true", "master_ready_for_operator_live_start=false"],
            allowed_next_step="Operator may request a fresh decision/preflight pack; Codex must not start the 24h run.",
            forbidden_actions=["start live trading", "call Coinbase without ACK", "submit orders", "mutate state"],
            blocks_BTC_24h=True,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="blocked",
        ),
        _route(
            route="all-ticker lifecycle parity",
            current_status="local_workflow_built_live_blocked"
            if all_ticker_gate.get("all_ticker_workflow_built_locally")
            else "blocked",
            current_decision="blocked",
            blockers=[
                "non-BTC evidence is fixture-only for product rules",
                "all_ticker_lifecycle_parity_ready=false",
                "all_ticker_live_allowed_now=false",
                "follower/live parity missing",
            ],
            allowed_next_step="Continue report-only evidence work or design ACK-gated live-readonly product-rule preflight.",
            forbidden_actions=["enable all-ticker live", "promote fixture evidence to live proof"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="medium",
        ),
        _route(
            route="all-ticker 24h workflow readiness",
            current_status="built_report_only_live_blocked"
            if all_ticker_gate.get("all_ticker_24h_workflow_readiness_pack_ready")
            else "missing_local_pack",
            current_decision="blocked",
            blockers=[
                "fresh all-ticker live-readonly product-rule preflight not run",
                "fresh all-ticker balance/min-notional preflight not run",
                "exact all-ticker live ACK missing",
                "all_ticker_live_authorized=false",
            ],
            allowed_next_step="Operator may run all-ticker fresh preflight manually only after exact scoped ACK; Codex must not run it.",
            forbidden_actions=["start all-ticker live", "call Coinbase without ACK", "promote fixture evidence to live proof"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="high",
        ),
        _route(
            route="all-ticker live-readonly preflight",
            current_status="preflight_passed_report_only"
            if all_ticker_preflight_gate.get("all_ticker_live_readonly_preflight_passed")
            else ("tool_ready_not_run" if all_ticker_preflight_gate.get("all_ticker_live_readonly_preflight_tool_ready") else "missing_tool"),
            current_decision="blocked" if not all_ticker_preflight_gate.get("all_ticker_live_readonly_preflight_passed") else "allowed_report_only",
            blockers=[
                "all_ticker_live_readonly_preflight_attempted=false"
                if not all_ticker_preflight_gate.get("all_ticker_live_readonly_preflight_attempted")
                else "review per-ticker readonly preflight blockers",
                "all_ticker_live_authorized=false",
                "exact all-ticker ACK missing",
            ],
            allowed_next_step="Use the tool/report for operator planning; actual Coinbase readonly preflight requires future exact scoped ACK.",
            forbidden_actions=["submit orders", "cancel/replace/reprice", "start all-ticker live", "mutate state"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="high",
        ),
        _route(
            route="parameter review candidate status",
            current_status="blocked",
            current_decision="blocked",
            blockers=[
                "d6 acceptance policy is defined but not passed",
                "sample-size/OOS/walk-forward ledger missing",
                "parameter_review_candidate=false",
            ],
            allowed_next_step="Use label export and acceptance policy to build evidence ledgers for human review.",
            forbidden_actions=["propose parameter values", "optimize", "rank strategies", "mutate parameters"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="high",
        ),
        _route(
            route="shadow parameter approximation",
            current_status="ready_report_only"
            if shadow_param_flags.get("shadow_parameter_approximation_pack_ready")
            else "missing",
            current_decision="allowed_report_only"
            if shadow_param_flags.get("shadow_parameter_approximation_pack_ready")
            else "blocked",
            blockers=[
                "parameter_values_approved=false",
                "parameter_change_allowed=false",
                "safe_to_mutate_parameters_now=false",
            ],
            allowed_next_step="Use review-only approximations for observation planning; keep parameters unchanged.",
            forbidden_actions=["apply approximate values", "mutate config", "optimize", "rank for live use"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="medium",
        ),
        _route(
            route="live learning governance",
            current_status="blocked",
            current_decision="blocked",
            blockers=["learning_to_execution_ready=false", "live_learning_allowed=false", "no governance bridge approved"],
            allowed_next_step="Design controlled learning governance only, without execution bridge.",
            forbidden_actions=["enable live learning", "connect labels to execution", "mutate runtime parameters"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="medium",
        ),
        _route(
            route="master SELL/exit readiness",
            current_status="blocked",
            current_decision="blocked_by_ACK",
            blockers=[
                f"master_live_exit_ready={exit_report.get('master_live_exit_ready', False)}",
                "no open live position requiring D3 exit",
                "live SELL requires exact ACK",
            ],
            allowed_next_step="Keep exit workflow readiness report current; only build live exit decision pack after explicit request.",
            forbidden_actions=["submit live SELL", "apply lifecycle fill", "alter reservation/no-oversell rules"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="blocked",
        ),
        _route(
            route="follower/replication readiness",
            current_status="blocked",
            current_decision="blocked",
            blockers=[
                f"follower_receiver_code_accessible={follower_flags.get('follower_receiver_code_accessible', False)}",
                f"follower_ready_for_live={follower_flags.get('follower_ready_for_live', False)}",
                "receiver/API code not accessible locally",
            ],
            allowed_next_step="Provide follower repo/path, then run local static receiver/API audit without HTTP.",
            forbidden_actions=["enable replication", "send HTTP to follower", "enable follower live"],
            blocks_BTC_24h=False,
            blocks_full_workflow=True,
            requires_ACK=True,
            recommended_priority="blocked",
        ),
        _route(
            route="state hygiene cleanup",
            current_status="blocked_by_ACK",
            current_decision="blocked_by_ACK",
            blockers=["state_hygiene_apply_ready=false", "exact cleanup ACK missing"],
            allowed_next_step="Review existing cleanup preview; apply only with exact ACK.",
            forbidden_actions=["write state", "manual state edit", "repair apply without ACK"],
            blocks_BTC_24h=False,
            blocks_full_workflow=False,
            requires_ACK=True,
            recommended_priority="low",
        ),
        _route(
            route="regression harness/operator workflow",
            current_status="mostly_ready_watch",
            current_decision="allowed_report_only",
            blockers=["not a live preflight"] if btc_monitor_test_present else ["optional BTC 24h monitor test missing", "not a live preflight"],
            allowed_next_step="Keep selected harness green; add only deterministic local tests.",
            forbidden_actions=["treat harness as live authorization", "start services"],
            blocks_BTC_24h=False,
            blocks_full_workflow=False,
            requires_ACK=False,
            recommended_priority="medium",
        ),
        _route(
            route="operator 24h pre-run build closure",
            current_status="build_complete_report_only" if prerun_flags.get("build_complete_for_operator_live_start_review") else "build_incomplete",
            current_decision="allowed_report_only",
            blockers=["live_start_authorized=false", "operator_manual_start_required=true"],
            allowed_next_step="Use checklist for operator review; do not start live run from Codex.",
            forbidden_actions=["start 24h test", "treat checklist as live ACK", "call Coinbase"],
            blocks_BTC_24h=False,
            blocks_full_workflow=False,
            requires_ACK=False,
            recommended_priority="high",
        ),
        _route(
            route="unresolved blocker ledger",
            current_status="complete_report_only" if ledger_flags.get("unresolved_blocker_ledger_ready") else "missing",
            current_decision="allowed_report_only",
            blockers=[
                f"remaining_locally_buildable_item_count={ledger_flags.get('remaining_locally_buildable_item_count', 'unknown')}",
                "remaining live/ACK/external dependencies still blocked",
            ],
            allowed_next_step="Use ledger to decide whether more local build work exists before operator live steps.",
            forbidden_actions=["treat ledger as live authorization", "bypass ACK blockers"],
            blocks_BTC_24h=False,
            blocks_full_workflow=False,
            requires_ACK=False,
            recommended_priority="high",
        ),
    ]
    report = {
        "phase": PHASE_ROADMAP_READINESS_DECISION_MAP,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "decision_map_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_proposed": False,
            "parameter_proposal_candidate": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
            "btc_24h_monitor_test_present": btc_monitor_test_present,
        },
        "classification": "WATCH",
        "routes": routes,
        "route_count": len(routes),
        "ready_route_count": sum(1 for row in routes if row["current_decision"] in {"allowed", "allowed_report_only"}),
        "blocked_route_count": sum(1 for row in routes if str(row["current_decision"]).startswith("blocked")),
        "watch_route_count": sum(1 for row in routes if row["current_status"] == "mostly_ready_watch"),
        "governance_flags": {
            "roadmap_readiness_decision_map_ready": True,
            "controlled_learning_governance_ready": bool(
                controlled_flags.get("controlled_learning_governance_ready", False)
            ),
            "current_max_allowed_learning_stage": controlled_flags.get(
                "current_max_allowed_learning_stage", "acceptance_policy_ready"
            ),
            "d6_acceptance_policy_ready": bool(acceptance_flags.get("d6_acceptance_policy_ready", False)),
            "d6_backlearning_label_export_pack_ready": bool(label_flags.get("d6_backlearning_label_export_pack_ready", False)),
            "fixture_evidence_consumed": bool(replay_gate.get("fixture_evidence_consumed", False)),
            "multi_ticker_paper_lifecycle_replay_ready": bool(replay_gate.get("multi_ticker_paper_lifecycle_replay_ready", False)),
            "paper_lifecycle_replay_ready_count": replay_gate.get("paper_lifecycle_replay_ready_count", 0),
            "parameter_review_candidate": False,
            "parameter_proposal_candidate": False,
            "d6_shadow_learning_report_ready": bool(shadow_flags.get("d6_shadow_learning_report_ready", False)),
            "report_only_shadow_learning_ready": bool(shadow_flags.get("report_only_shadow_learning_ready", False)),
            "execution_bridge_created": False,
            "operator_24h_prerun_build_checklist_ready": bool(
                prerun_flags.get("operator_24h_prerun_build_checklist_ready", False)
            ),
            "build_complete_for_operator_live_start_review": bool(
                prerun_flags.get("build_complete_for_operator_live_start_review", False)
            ),
            "live_start_authorized": False,
            "operator_manual_start_required": bool(prerun_flags.get("operator_manual_start_required", True)),
            "unresolved_blocker_ledger_ready": bool(ledger_flags.get("unresolved_blocker_ledger_ready", False)),
            "remaining_locally_buildable_item_count": int(
                ledger_flags.get("remaining_locally_buildable_item_count") or 0
            ),
            "all_ticker_24h_workflow_readiness_pack_ready": bool(
                all_ticker_gate.get("all_ticker_24h_workflow_readiness_pack_ready", False)
            ),
            "all_ticker_operator_preflight_command_pack_ready": bool(
                all_ticker_command_flags.get("all_ticker_operator_preflight_command_pack_ready", False)
            ),
            "all_ticker_live_scope_guard_ready": bool(
                all_ticker_guard_flags.get("all_ticker_live_scope_guard_ready", False)
            ),
            "all_ticker_live_readonly_preflight_tool_ready": bool(
                all_ticker_preflight_gate.get("all_ticker_live_readonly_preflight_tool_ready", False)
            ),
            "all_ticker_live_readonly_preflight_attempted": bool(
                all_ticker_preflight_gate.get("all_ticker_live_readonly_preflight_attempted", False)
            ),
            "all_ticker_live_readonly_preflight_passed": bool(
                all_ticker_preflight_gate.get("all_ticker_live_readonly_preflight_passed", False)
            ),
            "all_ticker_workflow_built_locally": bool(
                all_ticker_gate.get("all_ticker_workflow_built_locally", False)
            ),
            "all_ticker_ready_for_operator_fresh_preflight": bool(
                all_ticker_preflight_gate.get("all_ticker_ready_for_operator_fresh_preflight", False)
            ),
            "all_ticker_live_authorized": False,
            "shadow_parameter_approximation_pack_ready": bool(
                shadow_param_flags.get("shadow_parameter_approximation_pack_ready", False)
            ),
            "safe_to_mutate_parameters_now": False,
            "parameter_values_proposed": False,
            "parameter_review_approved": False,
            "parameter_change_allowed": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
        },
        "recommended_next_sprint": "policy sufficiency ledger or dry-run shadow-learning report design; live-start decision pack only if operator explicitly asks",
        "does_not_authorize_live_trading": True,
    }
    return _json_safe(report)


def render_roadmap_readiness_decision_map_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    flags = report.get("governance_flags") or {}
    lines = [
        "# Roadmap Readiness Decision Map",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- decision_map_only: `{meta.get('decision_map_only')}`",
        f"- parameter_values_proposed: `{meta.get('parameter_values_proposed')}`",
        f"- state_write_performed: `{meta.get('state_write_performed')}`",
        "",
        "## Governance Flags",
        "",
    ]
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Routes", ""])
    for row in report.get("routes") or []:
        lines.append(
            f"- {row.get('route')}: status=`{row.get('current_status')}`, "
            f"decision=`{row.get('current_decision')}`, "
            f"priority=`{row.get('recommended_priority')}`, requires_ACK=`{row.get('requires_ACK')}`, "
            f"allowed_next_step=`{row.get('allowed_next_step')}`"
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_ROADMAP_READINESS_DECISION_MAP",
    "build_roadmap_readiness_decision_map_report",
    "render_roadmap_readiness_decision_map_markdown",
]
