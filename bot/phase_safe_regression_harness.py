from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from tools.show_function_preservation_audit import build_audit_report
from tools.show_open_orders import build_summary as build_open_order_summary
from tools.show_open_orders import load_orders


PHASE_SAFE_REGRESSION_HARNESS = "safe_regression_harness_v1"
DEFAULT_OPEN_ORDERS_HASH = "919115b9fbcc20e137a1cfb18e87a4858482ab5c06c3fdb3e5c0e61079066b60"
DEFAULT_POSITIONS_HASH = "d288bc7ca3a9b11fc78e29aa4407036c1e9f66b6b4597b4e0293d4bf615965c2"
OPEN_STATUSES = {
    "planned",
    "pending",
    "submitted",
    "open",
    "active",
    "new",
    "queued",
    "partially_filled",
    "partial",
    "cancel_pending",
    "replace_pending",
}
D3_EXIT_PHASE = "D3_controlled_live_reduce_only_exits"
SELECTED_TEST_ALLOWLIST = {
    "tests/test_safe_regression_harness.py": True,
    "tests/test_all_ticker_readiness_gate.py": True,
    "tests/test_phase_d5_d6_evidence_expansion.py": True,
    "tests/test_follower_receiver_api_audit.py": True,
    "tests/test_exit_workflow_readiness_report.py": True,
    "tests/test_state_hygiene_cleanup_preview.py": True,
    "tests/test_replication_lifecycle_golden_payloads.py": True,
    "tests/test_replication_paper_lifecycle_simulator.py": True,
    "tests/test_replication_lifecycle_publisher_scaffold.py": True,
    "tests/test_main_workflow_parity_report.py": True,
    "tests/test_multi_ticker_paper_lifecycle_replay.py": True,
    "tests/test_per_ticker_product_rule_evidence_cache.py": True,
    "tests/test_phase_d6_backlearning_parameter_evidence_plan.py": True,
    "tests/test_phase_d6_human_review_decision_pack.py": True,
    "tests/test_product_rule_fixture_evidence.py": True,
    "tests/test_phase_d6_acceptance_policy.py": True,
    "tests/test_phase_d6_backlearning_label_export_pack.py": True,
    "tests/test_controlled_learning_governance.py": True,
    "tests/test_roadmap_readiness_decision_map.py": True,
    "tests/test_phase_d6_shadow_learning_report.py": True,
    "tests/test_operator_24h_prerun_build_checklist.py": True,
    "tests/test_unresolved_blocker_ledger.py": True,
    "tests/test_btc_usdc_24h_live_start_decision_pack.py": True,
    "tests/test_all_ticker_24h_workflow_readiness_pack.py": True,
    "tests/test_all_ticker_operator_preflight_command_pack.py": True,
    "tests/test_all_ticker_24h_monitor.py": True,
    "tests/test_all_ticker_24h_post_run_evidence_pack.py": True,
    "tests/test_all_ticker_live_scope_guard.py": True,
    "tests/test_all_ticker_live_readonly_preflight.py": True,
    "tests/test_shadow_parameter_approximation_pack.py": True,
    "tests/test_c4_d1_handoff_branch_map.py": False,
    "tests/test_btc_usdc_24h_post_run_evidence_pack.py": False,
    "tests/test_btc_usdc_24h_monitor.py": False,
}
SelectedTestRunner = Callable[[List[str], Path], Dict[str, Any]]


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


def _validate_selected_test_path(path: str) -> str:
    rel = str(path or "").strip()
    if rel not in SELECTED_TEST_ALLOWLIST:
        raise ValueError(f"selected_test_not_allowlisted:{rel}")
    if any(token in rel for token in (";", "&", "|", "`", "$", "\n", "\r", "..")):
        raise ValueError(f"selected_test_forbidden_path:{rel}")
    return rel


def _default_selected_test_runner(command: List[str], cwd: Path) -> Dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    summary = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    return {
        "returncode": completed.returncode,
        "summary": summary[-2000:],
    }


def _run_selected_tests(
    root: Path,
    *,
    selected_test_runner: Optional[SelectedTestRunner] = None,
    selected_test_specs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    runner = selected_test_runner or _default_selected_test_runner
    specs = list(selected_test_specs or [])
    if not specs:
        specs = [
            {"path": path, "required": required}
            for path, required in SELECTED_TEST_ALLOWLIST.items()
        ]

    results: List[Dict[str, Any]] = []
    for spec in specs:
        rel = _validate_selected_test_path(str(spec.get("path") or ""))
        required = bool(spec.get("required", SELECTED_TEST_ALLOWLIST[rel]))
        path = root / rel
        command = [sys.executable, "-m", "pytest", "-q", rel]
        if not path.exists():
            results.append(
                {
                    "command": " ".join(command),
                    "required": required,
                    "status": "failed" if required else "missing_optional",
                    "duration_seconds": 0.0,
                    "summary": "required test missing" if required else "optional test file missing",
                    "path": rel,
                }
            )
            continue
        start = time.monotonic()
        outcome = runner(command, root)
        duration = round(time.monotonic() - start, 3)
        returncode = int(outcome.get("returncode", 1))
        results.append(
            {
                "command": " ".join(command),
                "required": required,
                "status": "passed" if returncode == 0 else "failed",
                "duration_seconds": duration,
                "summary": str(outcome.get("summary") or ""),
                "path": rel,
            }
        )

    failed_required = [row for row in results if row["required"] and row["status"] != "passed"]
    missing_optional = [row for row in results if row["status"] == "missing_optional"]
    failed_optional = [row for row in results if not row["required"] and row["status"] == "failed"]
    if failed_required:
        classification = "STOP_NOW"
    elif missing_optional or failed_optional:
        classification = "WATCH"
    else:
        classification = "OK"
    return {
        "selected_tests_enabled": True,
        "selected_tests_run_count": sum(1 for row in results if row["status"] in {"passed", "failed"}),
        "selected_tests_passed_count": sum(1 for row in results if row["status"] == "passed"),
        "selected_tests_failed_count": sum(1 for row in results if row["status"] == "failed"),
        "selected_tests_missing_optional_count": len(missing_optional),
        "selected_tests_classification": classification,
        "selected_test_results": results,
    }


def _sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _is_open_order(order: Dict[str, Any]) -> bool:
    return str(order.get("status") or "").strip().lower() in OPEN_STATUSES


def _is_d3_exit_order(order: Dict[str, Any]) -> bool:
    if str(order.get("side") or "").strip().upper() != "SELL":
        return False
    phase = str(order.get("phase") or "").strip()
    cid = str(order.get("client_order_id") or "").strip().lower()
    mode = str(order.get("mode") or order.get("source_mode") or "").strip().lower()
    return (
        phase == D3_EXIT_PHASE
        or cid.startswith("phased3-")
        or cid.startswith("phased4-")
        or "d3" in mode
    )


def _open_d3_exit_count(orders: Iterable[Dict[str, Any]]) -> int:
    return sum(1 for order in orders if _is_open_order(order) and _is_d3_exit_order(order))


def _latest_existing(root: Path, candidates: Sequence[str]) -> Optional[Path]:
    for rel in candidates:
        path = root / rel
        if path.exists() and path.is_file():
            return path
    return None


def _report_status(payload: Dict[str, Any]) -> Any:
    for key in (
        "status",
        "overall_status",
        "phase_status",
        "conclusion",
        "report_status",
        "readiness_status",
    ):
        if key in payload:
            return payload.get(key)
    return None


def _report_ref(
    root: Path,
    *,
    key: str,
    candidates: Sequence[str],
    optional: bool = True,
) -> Dict[str, Any]:
    path = _latest_existing(root, candidates)
    if not path:
        return {
            "key": key,
            "available": False,
            "optional": optional,
            "path": None,
            "status": None,
            "watch_reason": f"optional_report_missing:{key}" if optional else f"required_report_missing:{key}",
        }
    payload = _load_json(path)
    return {
        "key": key,
        "available": True,
        "optional": optional,
        "path": str(path),
        "sha256": _sha256_file(path),
        "status": _report_status(payload),
        "summary": _summarize_report(key, payload),
    }


def _summarize_report(key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if key == "state_hygiene_cleanup_preview":
        return {
            "status": payload.get("status"),
            "cleanup_preview_count": payload.get("cleanup_preview_count"),
            "safe_cleanup_preview_count": payload.get("safe_cleanup_preview_count"),
            "apply_now": payload.get("apply_now"),
            "state_write_performed": payload.get("state_write_performed"),
        }
    if key == "exit_workflow_readiness":
        current = payload.get("current_order_state") or {}
        return {
            "exit_workflow_readiness_report_ready": payload.get("exit_workflow_readiness_report_ready"),
            "master_live_exit_ready": payload.get("master_live_exit_ready"),
            "follower_sell_ready": payload.get("follower_sell_ready"),
            "open_orders": current.get("open_orders"),
            "open_d3_exit": current.get("open_d3_exit"),
        }
    if key == "replication_lifecycle_publisher_scaffold":
        return {
            "publisher_scaffold_ready": payload.get("lifecycle_publisher_scaffold_ready")
            if "lifecycle_publisher_scaffold_ready" in payload
            else payload.get("publisher_scaffold_ready"),
            "http_call_attempted": payload.get("http_replication_call_attempted", payload.get("http_call_attempted")),
            "lifecycle_runtime_integrated": payload.get("lifecycle_runtime_integrated"),
        }
    if key == "replication_lifecycle_golden_payloads":
        return {
            "lifecycle_payloads_valid": payload.get("lifecycle_payloads_valid"),
            "simulator_validation_passed": payload.get("simulator_validation_passed"),
            "follower_ready_for_live": payload.get("follower_ready_for_live"),
        }
    if key == "replication_paper_lifecycle_simulator":
        return {
            "simulator_validation_passed": payload.get(
                "simulator_validation_passed",
                payload.get("paper_lifecycle_simulator_ready"),
            ),
            "live_order_attempted": payload.get("live_order_attempted"),
            "coinbase_call_attempted": payload.get("coinbase_call_attempted"),
            "state_write_performed": payload.get("state_write_performed"),
        }
    if key == "operator_runbook_pack":
        return {
            "phase": payload.get("phase"),
            "status": payload.get("status"),
            "no_coinbase_call": payload.get("no_coinbase_call"),
            "state_write_performed": payload.get("state_write_performed"),
        }
    if key == "d5_d6_evidence_expansion":
        flags = payload.get("readiness_and_governance_flags") or {}
        fee = payload.get("fee_evidence") or {}
        return {
            "classification": payload.get("classification"),
            "d5_d6_evidence_expansion_ready": flags.get("d5_d6_evidence_expansion_ready"),
            "human_review_ready": flags.get("human_review_ready"),
            "fee_gap_present": fee.get("fee_gap_present"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
            "parameter_change_allowed": flags.get("parameter_change_allowed"),
        }
    if key == "all_ticker_readiness_gate":
        flags = payload.get("readiness_flags") or {}
        gate = payload.get("gate_decision") or {}
        return {
            "classification": payload.get("classification"),
            "btc_usdc_tiny_scope_ready_for_operator_preflight": flags.get(
                "btc_usdc_tiny_scope_ready_for_operator_preflight"
            ),
            "all_ticker_ready": flags.get("all_ticker_ready"),
            "all_ticker_live_allowed_now": flags.get("all_ticker_live_allowed_now"),
            "tickers_blocked_count": gate.get("tickers_blocked_count"),
            "tickers_missing_evidence_count": gate.get("tickers_missing_evidence_count"),
        }
    if key == "follower_receiver_api_audit":
        flags = payload.get("readiness_flags") or {}
        discovery = payload.get("follower_code_discovery") or {}
        endpoints = payload.get("endpoint_audit") or {}
        return {
            "classification": payload.get("classification"),
            "follower_receiver_code_accessible": flags.get("follower_receiver_code_accessible"),
            "follower_receiver_api_audit_complete": flags.get("follower_receiver_api_audit_complete"),
            "follower_ready_for_live": flags.get("follower_ready_for_live"),
            "follower_buy_ready": flags.get("follower_buy_ready"),
            "follower_sell_ready": flags.get("follower_sell_ready"),
            "receiver_code_found": discovery.get("receiver_code_found"),
            "decision_endpoint_status": endpoints.get("decision_endpoint_status"),
            "lifecycle_endpoint_status": endpoints.get("lifecycle_endpoint_status"),
        }
    if key == "main_workflow_parity_report":
        gate = payload.get("gate_decision") or {}
        return {
            "main_workflow_parity_report_ready": gate.get("main_workflow_parity_report_ready"),
            "old_multi_ticker_decision_workflow_seen": gate.get("old_multi_ticker_decision_workflow_seen"),
            "all_ticker_lifecycle_parity_ready": gate.get("all_ticker_lifecycle_parity_ready"),
            "all_ticker_live_allowed_now": gate.get("all_ticker_live_allowed_now"),
            "btc_usdc_tiny_scope_ready_for_operator_preflight": gate.get(
                "btc_usdc_tiny_scope_ready_for_operator_preflight"
            ),
        }
    if key == "multi_ticker_paper_lifecycle_replay":
        gate = payload.get("gate_decision") or {}
        return {
            "classification": payload.get("classification"),
            "multi_ticker_paper_lifecycle_replay_ready": gate.get("multi_ticker_paper_lifecycle_replay_ready"),
            "all_ticker_lifecycle_parity_ready": gate.get("all_ticker_lifecycle_parity_ready"),
            "all_ticker_live_allowed_now": gate.get("all_ticker_live_allowed_now"),
            "tickers_replay_ready_count": gate.get("tickers_replay_ready_count"),
            "tickers_replay_partial_count": gate.get("tickers_replay_partial_count"),
            "tickers_blocked_count": gate.get("tickers_blocked_count"),
        }
    if key == "per_ticker_product_rule_evidence_cache":
        gate = payload.get("gate_decision") or {}
        return {
            "classification": payload.get("classification"),
            "per_ticker_product_rule_evidence_cache_ready": gate.get("per_ticker_product_rule_evidence_cache_ready"),
            "all_ticker_product_rule_evidence_ready": gate.get("all_ticker_product_rule_evidence_ready"),
            "all_ticker_lifecycle_parity_ready": gate.get("all_ticker_lifecycle_parity_ready"),
            "all_ticker_live_allowed_now": gate.get("all_ticker_live_allowed_now"),
            "tickers_ready_count": gate.get("tickers_ready_count"),
            "tickers_partial_count": gate.get("tickers_partial_count"),
            "tickers_missing_count": gate.get("tickers_missing_count"),
        }
    if key == "d6_backlearning_parameter_evidence_plan":
        flags = payload.get("governance_flags") or {}
        evidence = payload.get("evidence_summary") or {}
        return {
            "classification": payload.get("classification"),
            "d6_backlearning_parameter_evidence_plan_ready": flags.get(
                "d6_backlearning_parameter_evidence_plan_ready"
            ),
            "human_review_ready": flags.get("human_review_ready"),
            "parameter_review_candidate": flags.get("parameter_review_candidate"),
            "parameter_change_allowed": flags.get("parameter_change_allowed"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
            "live_learning_allowed": flags.get("live_learning_allowed"),
            "evidence_quality_classification": evidence.get("evidence_quality_classification"),
        }
    if key == "d6_human_review_decision_pack":
        flags = payload.get("governance_flags") or {}
        source = payload.get("evidence_source_summary") or {}
        return {
            "classification": payload.get("classification"),
            "d6_human_review_decision_pack_ready": flags.get("d6_human_review_decision_pack_ready"),
            "human_review_ready": flags.get("human_review_ready"),
            "parameter_review_candidate": flags.get("parameter_review_candidate"),
            "parameter_values_proposed": flags.get("parameter_values_proposed"),
            "parameter_change_allowed": flags.get("parameter_change_allowed"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
            "live_learning_allowed": flags.get("live_learning_allowed"),
            "evidence_quality_overview": source.get("evidence_quality_overview"),
        }
    if key == "product_rule_fixture_evidence":
        summary = payload.get("universe_summary") or {}
        return {
            "classification": payload.get("classification"),
            "product_rule_fixture_evidence_ready": summary.get("fixture_completion_ready"),
            "fixture_evidence_ticker_count": summary.get("fixture_evidence_ticker_count"),
            "live_readonly_cached_ticker_count": summary.get("live_readonly_cached_ticker_count"),
            "missing_evidence_ticker_count": summary.get("missing_evidence_ticker_count"),
            "paper_replay_usable_ticker_count": summary.get("paper_replay_usable_ticker_count"),
            "all_ticker_live_allowed_now": summary.get("all_ticker_live_allowed_now"),
        }
    if key == "d6_acceptance_policy":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "d6_acceptance_policy_ready": flags.get("d6_acceptance_policy_ready"),
            "parameter_review_candidate": flags.get("parameter_review_candidate"),
            "parameter_values_proposed": flags.get("parameter_values_proposed"),
            "parameter_change_allowed": flags.get("parameter_change_allowed"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
            "live_learning_allowed": flags.get("live_learning_allowed"),
        }
    if key == "d6_backlearning_label_export_pack":
        flags = payload.get("governance_flags") or {}
        counts = payload.get("label_counts") or {}
        return {
            "classification": payload.get("classification"),
            "d6_backlearning_label_export_pack_ready": flags.get("d6_backlearning_label_export_pack_ready"),
            "export_record_count": counts.get("export_record_count"),
            "ticker_label_count": counts.get("ticker_label_count"),
            "lifecycle_label_count": counts.get("lifecycle_label_count"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
        }
    if key == "roadmap_readiness_decision_map":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "roadmap_readiness_decision_map_ready": flags.get("roadmap_readiness_decision_map_ready"),
            "route_count": payload.get("route_count"),
            "blocked_route_count": payload.get("blocked_route_count"),
            "ready_route_count": payload.get("ready_route_count"),
            "parameter_review_candidate": flags.get("parameter_review_candidate"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
        }
    if key == "controlled_learning_governance":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "controlled_learning_governance_ready": flags.get("controlled_learning_governance_ready"),
            "current_max_allowed_learning_stage": flags.get("current_max_allowed_learning_stage"),
            "parameter_proposal_candidate": flags.get("parameter_proposal_candidate"),
            "parameter_values_proposed": flags.get("parameter_values_proposed"),
            "parameter_change_allowed": flags.get("parameter_change_allowed"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
            "live_learning_allowed": flags.get("live_learning_allowed"),
        }
    if key == "d6_shadow_learning_report":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "d6_shadow_learning_report_ready": flags.get("d6_shadow_learning_report_ready"),
            "report_only_shadow_learning_ready": flags.get("report_only_shadow_learning_ready"),
            "execution_bridge_created": flags.get("execution_bridge_created"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
            "live_learning_allowed": flags.get("live_learning_allowed"),
        }
    if key == "operator_24h_prerun_build_checklist":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "status": payload.get("status"),
            "operator_24h_prerun_build_checklist_ready": flags.get("operator_24h_prerun_build_checklist_ready"),
            "build_complete_for_operator_live_start_review": flags.get("build_complete_for_operator_live_start_review"),
            "live_start_authorized": flags.get("live_start_authorized"),
            "operator_manual_start_required": flags.get("operator_manual_start_required"),
        }
    if key == "unresolved_blocker_ledger":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "unresolved_blocker_ledger_ready": flags.get("unresolved_blocker_ledger_ready"),
            "remaining_locally_buildable_item_count": flags.get("remaining_locally_buildable_item_count"),
            "all_remaining_items_are_ack_live_or_external_dependent": flags.get(
                "all_remaining_items_are_ack_live_or_external_dependent"
            ),
        }
    if key == "btc_usdc_24h_live_start_decision_pack":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "decision_status": payload.get("decision_status"),
            "btc_usdc_24h_live_start_decision_pack_ready": flags.get(
                "btc_usdc_24h_live_start_decision_pack_ready"
            ),
            "ready_for_operator_fresh_preflight": flags.get("ready_for_operator_fresh_preflight"),
            "live_start_authorized": flags.get("live_start_authorized"),
            "operator_manual_start_required": flags.get("operator_manual_start_required"),
            "codex_must_not_start_live_test": flags.get("codex_must_not_start_live_test"),
        }
    if key == "all_ticker_24h_workflow_readiness_pack":
        gate = payload.get("gate_decision") or {}
        return {
            "classification": payload.get("classification"),
            "all_ticker_24h_workflow_readiness_pack_ready": gate.get(
                "all_ticker_24h_workflow_readiness_pack_ready"
            ),
            "all_ticker_workflow_built_locally": gate.get("all_ticker_workflow_built_locally"),
            "all_ticker_ready_for_operator_fresh_preflight": gate.get(
                "all_ticker_ready_for_operator_fresh_preflight"
            ),
            "all_ticker_live_authorized": gate.get("all_ticker_live_authorized"),
            "btc_usdc_ready_for_operator_fresh_preflight": gate.get(
                "btc_usdc_ready_for_operator_fresh_preflight"
            ),
            "non_btc_tickers_ready_for_operator_fresh_preflight": gate.get(
                "non_btc_tickers_ready_for_operator_fresh_preflight"
            ),
        }
    if key == "all_ticker_operator_preflight_command_pack":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "all_ticker_operator_preflight_command_pack_ready": flags.get(
                "all_ticker_operator_preflight_command_pack_ready"
            ),
            "all_commands_operator_only": flags.get("all_commands_operator_only"),
            "all_ticker_live_authorized": flags.get("all_ticker_live_authorized"),
            "live_start_authorized": flags.get("live_start_authorized"),
        }
    if key == "all_ticker_live_scope_guard":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "all_ticker_live_scope_guard_ready": flags.get("all_ticker_live_scope_guard_ready"),
            "all_ticker_live_authorized": flags.get("all_ticker_live_authorized"),
            "live_start_authorized": flags.get("live_start_authorized"),
            "stop_reasons": payload.get("stop_reasons") or [],
        }
    if key == "all_ticker_live_readonly_preflight":
        gate = payload.get("gate_decision") or {}
        return {
            "classification": payload.get("classification"),
            "status": payload.get("status"),
            "all_ticker_live_readonly_preflight_tool_ready": gate.get(
                "all_ticker_live_readonly_preflight_tool_ready"
            ),
            "all_ticker_live_readonly_preflight_attempted": gate.get(
                "all_ticker_live_readonly_preflight_attempted"
            ),
            "all_ticker_live_readonly_preflight_passed": gate.get(
                "all_ticker_live_readonly_preflight_passed"
            ),
            "all_ticker_ready_for_operator_fresh_preflight": gate.get(
                "all_ticker_ready_for_operator_fresh_preflight"
            ),
            "all_ticker_live_authorized": gate.get("all_ticker_live_authorized"),
        }
    if key == "shadow_parameter_approximation_pack":
        flags = payload.get("governance_flags") or {}
        return {
            "classification": payload.get("classification"),
            "shadow_parameter_approximation_pack_ready": flags.get(
                "shadow_parameter_approximation_pack_ready"
            ),
            "parameter_values_approved": flags.get("parameter_values_approved"),
            "parameter_change_allowed": flags.get("parameter_change_allowed"),
            "safe_to_mutate_parameters_now": flags.get("safe_to_mutate_parameters_now"),
            "learning_to_execution_ready": flags.get("learning_to_execution_ready"),
            "live_learning_allowed": flags.get("live_learning_allowed"),
        }
    return {"status": _report_status(payload)}


def _tool_availability(root: Path) -> Dict[str, Dict[str, Any]]:
    tools = {
        "btc_usdc_24h_live_monitor": "tools/show_btc_usdc_24h_live_monitor.py",
        "btc_usdc_24h_post_run_evidence_pack": "tools/build_btc_usdc_24h_post_run_evidence_pack.py",
        "all_ticker_24h_live_monitor": "tools/show_all_ticker_24h_live_monitor.py",
        "all_ticker_24h_post_run_evidence_pack": "tools/build_all_ticker_24h_post_run_evidence_pack.py",
        "all_ticker_live_scope_guard": "tools/build_all_ticker_live_scope_guard.py",
        "all_ticker_live_readonly_preflight": "tools/show_all_ticker_live_readonly_preflight.py",
        "shadow_parameter_approximation_pack": "tools/build_shadow_parameter_approximation_pack.py",
        "operator_runbook_pack_builder": "tools/build_live_operator_runbook_pack.py",
    }
    return {
        key: {"available": (root / rel).exists(), "path": str(root / rel)}
        for key, rel in tools.items()
    }


def _readiness_flags(report_refs: Dict[str, Dict[str, Any]], classification: str) -> Dict[str, bool]:
    state_hygiene = report_refs.get("state_hygiene_cleanup_preview", {})
    exit_workflow = report_refs.get("exit_workflow_readiness", {})
    golden = report_refs.get("replication_lifecycle_golden_payloads", {})
    simulator = report_refs.get("replication_paper_lifecycle_simulator", {})
    follower_audit = report_refs.get("follower_receiver_api_audit", {})
    all_ticker_gate = report_refs.get("all_ticker_readiness_gate", {})
    d6_plan = report_refs.get("d6_backlearning_parameter_evidence_plan", {})
    d6_decision_pack = report_refs.get("d6_human_review_decision_pack", {})
    product_fixture = report_refs.get("product_rule_fixture_evidence", {})
    d6_acceptance = report_refs.get("d6_acceptance_policy", {})
    d6_label_export = report_refs.get("d6_backlearning_label_export_pack", {})
    readiness_map = report_refs.get("roadmap_readiness_decision_map", {})
    controlled_learning = report_refs.get("controlled_learning_governance", {})
    shadow_learning = report_refs.get("d6_shadow_learning_report", {})
    prerun_checklist = report_refs.get("operator_24h_prerun_build_checklist", {})
    blocker_ledger = report_refs.get("unresolved_blocker_ledger", {})
    decision_pack = report_refs.get("btc_usdc_24h_live_start_decision_pack", {})
    all_ticker_24h_pack = report_refs.get("all_ticker_24h_workflow_readiness_pack", {})
    all_ticker_command_pack = report_refs.get("all_ticker_operator_preflight_command_pack", {})
    all_ticker_scope_guard = report_refs.get("all_ticker_live_scope_guard", {})
    all_ticker_live_preflight = report_refs.get("all_ticker_live_readonly_preflight", {})
    shadow_parameter_pack = report_refs.get("shadow_parameter_approximation_pack", {})

    state_payload = _load_json(Path(state_hygiene["path"])) if state_hygiene.get("available") else {}
    exit_payload = _load_json(Path(exit_workflow["path"])) if exit_workflow.get("available") else {}
    golden_payload = _load_json(Path(golden["path"])) if golden.get("available") else {}
    simulator_payload = _load_json(Path(simulator["path"])) if simulator.get("available") else {}
    follower_payload = _load_json(Path(follower_audit["path"])) if follower_audit.get("available") else {}
    all_ticker_payload = _load_json(Path(all_ticker_gate["path"])) if all_ticker_gate.get("available") else {}
    d6_plan_payload = _load_json(Path(d6_plan["path"])) if d6_plan.get("available") else {}
    d6_decision_payload = _load_json(Path(d6_decision_pack["path"])) if d6_decision_pack.get("available") else {}
    product_fixture_payload = _load_json(Path(product_fixture["path"])) if product_fixture.get("available") else {}
    d6_acceptance_payload = _load_json(Path(d6_acceptance["path"])) if d6_acceptance.get("available") else {}
    d6_label_payload = _load_json(Path(d6_label_export["path"])) if d6_label_export.get("available") else {}
    readiness_map_payload = _load_json(Path(readiness_map["path"])) if readiness_map.get("available") else {}
    controlled_payload = _load_json(Path(controlled_learning["path"])) if controlled_learning.get("available") else {}
    shadow_payload = _load_json(Path(shadow_learning["path"])) if shadow_learning.get("available") else {}
    prerun_payload = _load_json(Path(prerun_checklist["path"])) if prerun_checklist.get("available") else {}
    ledger_payload = _load_json(Path(blocker_ledger["path"])) if blocker_ledger.get("available") else {}
    decision_pack_payload = _load_json(Path(decision_pack["path"])) if decision_pack.get("available") else {}
    all_ticker_24h_payload = (
        _load_json(Path(all_ticker_24h_pack["path"])) if all_ticker_24h_pack.get("available") else {}
    )
    all_ticker_command_payload = (
        _load_json(Path(all_ticker_command_pack["path"])) if all_ticker_command_pack.get("available") else {}
    )
    all_ticker_scope_payload = (
        _load_json(Path(all_ticker_scope_guard["path"])) if all_ticker_scope_guard.get("available") else {}
    )
    all_ticker_live_preflight_payload = (
        _load_json(Path(all_ticker_live_preflight["path"])) if all_ticker_live_preflight.get("available") else {}
    )
    shadow_parameter_payload = (
        _load_json(Path(shadow_parameter_pack["path"])) if shadow_parameter_pack.get("available") else {}
    )
    follower_flags = follower_payload.get("readiness_flags") if isinstance(follower_payload.get("readiness_flags"), dict) else {}
    all_ticker_flags = (
        all_ticker_payload.get("readiness_flags") if isinstance(all_ticker_payload.get("readiness_flags"), dict) else {}
    )
    d6_plan_flags = (
        d6_plan_payload.get("governance_flags") if isinstance(d6_plan_payload.get("governance_flags"), dict) else {}
    )
    d6_decision_flags = (
        d6_decision_payload.get("governance_flags")
        if isinstance(d6_decision_payload.get("governance_flags"), dict)
        else {}
    )
    product_fixture_summary = (
        product_fixture_payload.get("universe_summary")
        if isinstance(product_fixture_payload.get("universe_summary"), dict)
        else {}
    )
    d6_acceptance_flags = (
        d6_acceptance_payload.get("governance_flags")
        if isinstance(d6_acceptance_payload.get("governance_flags"), dict)
        else {}
    )
    d6_label_flags = (
        d6_label_payload.get("governance_flags") if isinstance(d6_label_payload.get("governance_flags"), dict) else {}
    )
    readiness_map_flags = (
        readiness_map_payload.get("governance_flags")
        if isinstance(readiness_map_payload.get("governance_flags"), dict)
        else {}
    )
    controlled_flags = (
        controlled_payload.get("governance_flags")
        if isinstance(controlled_payload.get("governance_flags"), dict)
        else {}
    )
    shadow_flags = (
        shadow_payload.get("governance_flags") if isinstance(shadow_payload.get("governance_flags"), dict) else {}
    )
    prerun_flags = (
        prerun_payload.get("governance_flags") if isinstance(prerun_payload.get("governance_flags"), dict) else {}
    )
    ledger_flags = (
        ledger_payload.get("governance_flags") if isinstance(ledger_payload.get("governance_flags"), dict) else {}
    )
    decision_pack_flags = (
        decision_pack_payload.get("governance_flags")
        if isinstance(decision_pack_payload.get("governance_flags"), dict)
        else {}
    )
    all_ticker_24h_gate = (
        all_ticker_24h_payload.get("gate_decision")
        if isinstance(all_ticker_24h_payload.get("gate_decision"), dict)
        else {}
    )
    all_ticker_command_flags = (
        all_ticker_command_payload.get("governance_flags")
        if isinstance(all_ticker_command_payload.get("governance_flags"), dict)
        else {}
    )
    all_ticker_scope_flags = (
        all_ticker_scope_payload.get("governance_flags")
        if isinstance(all_ticker_scope_payload.get("governance_flags"), dict)
        else {}
    )
    all_ticker_live_preflight_gate = (
        all_ticker_live_preflight_payload.get("gate_decision")
        if isinstance(all_ticker_live_preflight_payload.get("gate_decision"), dict)
        else {}
    )
    shadow_parameter_flags = (
        shadow_parameter_payload.get("governance_flags")
        if isinstance(shadow_parameter_payload.get("governance_flags"), dict)
        else {}
    )

    hygiene_flags = state_payload.get("readiness_flags") if isinstance(state_payload.get("readiness_flags"), dict) else {}
    return {
        "local_safe_regression_passed": classification == "OK",
        "master_ready_for_operator_preflight": bool(
            hygiene_flags.get("master_ready_for_operator_preflight", True)
            and exit_payload.get("master_ready_for_operator_preflight", True)
            and classification != "STOP_NOW"
        ),
        "master_ready_for_operator_live_start": False,
        "master_live_exit_ready": bool(exit_payload.get("master_live_exit_ready", False)),
        "follower_receiver_code_accessible": bool(follower_flags.get("follower_receiver_code_accessible", False)),
        "follower_receiver_api_audit_complete": bool(
            follower_flags.get("follower_receiver_api_audit_complete", False)
        ),
        "follower_ready_for_paper_lifecycle_test": bool(
            golden_payload.get("follower_ready_for_paper_lifecycle_test")
            or simulator_payload.get("follower_ready_for_paper_lifecycle_test")
            or hygiene_flags.get("follower_ready_for_paper_lifecycle_test", False)
        ),
        "follower_buy_ready": bool(follower_flags.get("follower_buy_ready", False)),
        "follower_ready_for_live": False,
        "follower_sell_ready": bool(
            exit_payload.get("follower_sell_ready", False) or follower_flags.get("follower_sell_ready", False)
        ),
        "lifecycle_parity_ready": bool(
            exit_payload.get("lifecycle_parity_ready", False) or follower_flags.get("lifecycle_parity_ready", False)
        ),
        "all_ticker_ready": bool(all_ticker_flags.get("all_ticker_ready", exit_payload.get("all_ticker_ready", False))),
        "learning_to_execution_ready": False,
        "d6_acceptance_policy_ready": bool(d6_acceptance_flags.get("d6_acceptance_policy_ready", False)),
        "d6_backlearning_label_export_pack_ready": bool(
            d6_label_flags.get("d6_backlearning_label_export_pack_ready", False)
        ),
        "roadmap_readiness_decision_map_ready": bool(
            readiness_map_flags.get("roadmap_readiness_decision_map_ready", False)
        ),
        "controlled_learning_governance_ready": bool(
            controlled_flags.get("controlled_learning_governance_ready", False)
        ),
        "current_max_allowed_learning_stage": str(
            controlled_flags.get("current_max_allowed_learning_stage", "")
        ),
        "parameter_proposal_candidate": bool(controlled_flags.get("parameter_proposal_candidate", False)),
        "d6_shadow_learning_report_ready": bool(shadow_flags.get("d6_shadow_learning_report_ready", False)),
        "report_only_shadow_learning_ready": bool(shadow_flags.get("report_only_shadow_learning_ready", False)),
        "execution_bridge_created": bool(shadow_flags.get("execution_bridge_created", False)),
        "operator_24h_prerun_build_checklist_ready": bool(
            prerun_flags.get("operator_24h_prerun_build_checklist_ready", False)
        ),
        "build_complete_for_operator_live_start_review": bool(
            prerun_flags.get("build_complete_for_operator_live_start_review", False)
        ),
        "live_start_authorized": False,
        "operator_manual_start_required": bool(prerun_flags.get("operator_manual_start_required", False)),
        "unresolved_blocker_ledger_ready": bool(ledger_flags.get("unresolved_blocker_ledger_ready", False)),
        "remaining_locally_buildable_item_count": int(ledger_flags.get("remaining_locally_buildable_item_count") or 0),
        "btc_usdc_24h_live_start_decision_pack_ready": bool(
            decision_pack_flags.get("btc_usdc_24h_live_start_decision_pack_ready", False)
        ),
        "ready_for_operator_fresh_preflight": bool(decision_pack_flags.get("ready_for_operator_fresh_preflight", False)),
        "all_ticker_24h_workflow_readiness_pack_ready": bool(
            all_ticker_24h_gate.get("all_ticker_24h_workflow_readiness_pack_ready", False)
        ),
        "all_ticker_operator_preflight_command_pack_ready": bool(
            all_ticker_command_flags.get("all_ticker_operator_preflight_command_pack_ready", False)
        ),
        "all_ticker_monitor_scaffold_ready": bool(
            all_ticker_command_flags.get("all_ticker_operator_preflight_command_pack_ready", False)
        ),
        "all_ticker_post_run_evidence_scaffold_ready": bool(
            all_ticker_command_flags.get("all_ticker_operator_preflight_command_pack_ready", False)
        ),
        "all_ticker_live_scope_guard_ready": bool(
            all_ticker_scope_flags.get("all_ticker_live_scope_guard_ready", False)
        ),
        "all_ticker_workflow_built_locally": bool(
            all_ticker_24h_gate.get("all_ticker_workflow_built_locally", False)
        ),
        "all_ticker_ready_for_operator_fresh_preflight": bool(
            all_ticker_live_preflight_gate.get(
                "all_ticker_ready_for_operator_fresh_preflight",
                all_ticker_24h_gate.get("all_ticker_ready_for_operator_fresh_preflight", False),
            )
        ),
        "all_ticker_live_readonly_preflight_tool_ready": bool(
            all_ticker_live_preflight_gate.get("all_ticker_live_readonly_preflight_tool_ready", False)
        ),
        "all_ticker_live_readonly_preflight_attempted": bool(
            all_ticker_live_preflight_gate.get("all_ticker_live_readonly_preflight_attempted", False)
        ),
        "all_ticker_live_readonly_preflight_passed": bool(
            all_ticker_live_preflight_gate.get("all_ticker_live_readonly_preflight_passed", False)
        ),
        "all_ticker_live_authorized": False,
        "btc_usdc_ready_for_operator_fresh_preflight": bool(
            all_ticker_24h_gate.get("btc_usdc_ready_for_operator_fresh_preflight", False)
        ),
        "non_btc_tickers_ready_for_operator_fresh_preflight": bool(
            all_ticker_24h_gate.get("non_btc_tickers_ready_for_operator_fresh_preflight", False)
        ),
        "d6_backlearning_parameter_evidence_plan_ready": bool(
            d6_plan_flags.get("d6_backlearning_parameter_evidence_plan_ready", False)
        ),
        "d6_human_review_decision_pack_ready": bool(
            d6_decision_flags.get("d6_human_review_decision_pack_ready", False)
        ),
        "human_review_ready": bool(
            d6_decision_flags.get("human_review_ready", d6_plan_flags.get("human_review_ready", False))
        ),
        "parameter_review_candidate": bool(
            d6_decision_flags.get("parameter_review_candidate", d6_plan_flags.get("parameter_review_candidate", False))
        ),
        "parameter_values_proposed": False,
        "shadow_parameter_approximation_pack_ready": bool(
            shadow_parameter_flags.get("shadow_parameter_approximation_pack_ready", False)
        ),
        "product_rule_fixture_evidence_ready": bool(product_fixture_summary.get("fixture_completion_ready", False)),
        "fixture_evidence_ticker_count": int(product_fixture_summary.get("fixture_evidence_ticker_count") or 0),
        "paper_replay_usable_ticker_count": int(product_fixture_summary.get("paper_replay_usable_ticker_count") or 0),
        "parameter_review_approved": False,
        "parameter_change_allowed": False,
        "safe_to_mutate_parameters_now": False,
        "live_learning_allowed": False,
        "state_hygiene_cleanup_preview_ready": bool(
            hygiene_flags.get("state_hygiene_cleanup_preview_ready")
            or state_payload.get("phase") == "state_hygiene_cleanup_preview_v1"
        ),
        "state_hygiene_apply_ready": False,
    }


def build_safe_regression_harness(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    expected_open_orders_hash: str = DEFAULT_OPEN_ORDERS_HASH,
    expected_positions_hash: str = DEFAULT_POSITIONS_HASH,
    open_orders_report: Optional[Dict[str, Any]] = None,
    function_audit_report: Optional[Dict[str, Any]] = None,
    include_selected_tests: bool = False,
    selected_test_runner: Optional[SelectedTestRunner] = None,
    selected_test_specs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    orders_path = project_root / "state" / "open_orders.json"
    positions_path = project_root / "state" / "positions.json"

    orders = load_orders(orders_path)
    open_summary = dict((open_orders_report or {}).get("summary") or build_open_order_summary(orders))
    open_d3_exit = _open_d3_exit_count(orders)
    open_summary["open_d3_exit"] = open_d3_exit
    audit = function_audit_report or build_audit_report(project_root)

    initial_hashes = {
        "state/open_orders.json": _sha256_file(orders_path),
        "state/positions.json": _sha256_file(positions_path),
    }
    selected_tests = (
        _run_selected_tests(
            project_root,
            selected_test_runner=selected_test_runner,
            selected_test_specs=selected_test_specs,
        )
        if include_selected_tests
        else {
            "selected_tests_enabled": False,
            "selected_tests_run_count": 0,
            "selected_tests_passed_count": 0,
            "selected_tests_failed_count": 0,
            "selected_tests_missing_optional_count": 0,
            "selected_tests_classification": "OK",
            "selected_test_results": [],
        }
    )
    current_hashes = {
        "state/open_orders.json": _sha256_file(orders_path),
        "state/positions.json": _sha256_file(positions_path),
    }
    expected_hashes = {
        "state/open_orders.json": expected_open_orders_hash,
        "state/positions.json": expected_positions_hash,
    }
    hash_drift = {
        key: {"expected": expected_hashes[key], "actual": current_hashes.get(key)}
        for key in expected_hashes
        if current_hashes.get(key) != expected_hashes[key]
    }

    refs = {
        "state_hygiene_cleanup_preview": _report_ref(
            project_root,
            key="state_hygiene_cleanup_preview",
            candidates=["reports/d6/state-hygiene-cleanup-preview-20260609.json"],
        ),
        "exit_workflow_readiness": _report_ref(
            project_root,
            key="exit_workflow_readiness",
            candidates=["reports/d6/exit-workflow-readiness-report-20260609.json"],
        ),
        "replication_lifecycle_publisher_scaffold": _report_ref(
            project_root,
            key="replication_lifecycle_publisher_scaffold",
            candidates=["reports/d6/replication-lifecycle-publisher-scaffold-20260609.json"],
        ),
        "replication_lifecycle_golden_payloads": _report_ref(
            project_root,
            key="replication_lifecycle_golden_payloads",
            candidates=["reports/d6/replication-lifecycle-golden-payloads-20260609.json"],
        ),
        "replication_paper_lifecycle_simulator": _report_ref(
            project_root,
            key="replication_paper_lifecycle_simulator",
            candidates=["reports/d6/replication-paper-lifecycle-simulator-20260609.json"],
        ),
        "operator_runbook_pack": _report_ref(
            project_root,
            key="operator_runbook_pack",
            candidates=["reports/d6/operator-24h-live-test-pack-20260609.json"],
        ),
        "d5_d6_evidence_expansion": _report_ref(
            project_root,
            key="d5_d6_evidence_expansion",
            candidates=["reports/d6/d5-d6-evidence-expansion-20260609.json"],
        ),
        "all_ticker_readiness_gate": _report_ref(
            project_root,
            key="all_ticker_readiness_gate",
            candidates=["reports/d6/all-ticker-readiness-gate-20260609.json"],
        ),
        "follower_receiver_api_audit": _report_ref(
            project_root,
            key="follower_receiver_api_audit",
            candidates=["reports/d6/follower-receiver-api-audit-20260609.json"],
        ),
        "main_workflow_parity_report": _report_ref(
            project_root,
            key="main_workflow_parity_report",
            candidates=["reports/d6/main-workflow-parity-report-20260609.json"],
        ),
        "multi_ticker_paper_lifecycle_replay": _report_ref(
            project_root,
            key="multi_ticker_paper_lifecycle_replay",
            candidates=["reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json"],
        ),
        "per_ticker_product_rule_evidence_cache": _report_ref(
            project_root,
            key="per_ticker_product_rule_evidence_cache",
            candidates=["reports/d6/per-ticker-product-rule-evidence-cache-20260609.json"],
        ),
        "d6_backlearning_parameter_evidence_plan": _report_ref(
            project_root,
            key="d6_backlearning_parameter_evidence_plan",
            candidates=["reports/d6/d6-backlearning-parameter-evidence-plan-20260609.json"],
        ),
        "d6_human_review_decision_pack": _report_ref(
            project_root,
            key="d6_human_review_decision_pack",
            candidates=["reports/d6/d6-human-review-decision-pack-20260609.json"],
        ),
        "product_rule_fixture_evidence": _report_ref(
            project_root,
            key="product_rule_fixture_evidence",
            candidates=["reports/d6/product-rule-fixture-evidence-20260609.json"],
        ),
        "d6_acceptance_policy": _report_ref(
            project_root,
            key="d6_acceptance_policy",
            candidates=["reports/d6/d6-acceptance-policy-20260609.json"],
        ),
        "d6_backlearning_label_export_pack": _report_ref(
            project_root,
            key="d6_backlearning_label_export_pack",
            candidates=["reports/d6/d6-backlearning-label-export-pack-20260609.json"],
        ),
        "roadmap_readiness_decision_map": _report_ref(
            project_root,
            key="roadmap_readiness_decision_map",
            candidates=["reports/d6/roadmap-readiness-decision-map-20260609.json"],
        ),
        "controlled_learning_governance": _report_ref(
            project_root,
            key="controlled_learning_governance",
            candidates=["reports/d6/controlled-learning-governance-20260609.json"],
        ),
        "d6_shadow_learning_report": _report_ref(
            project_root,
            key="d6_shadow_learning_report",
            candidates=["reports/d6/d6-shadow-learning-report-20260609.json"],
        ),
        "operator_24h_prerun_build_checklist": _report_ref(
            project_root,
            key="operator_24h_prerun_build_checklist",
            candidates=["reports/d6/operator-24h-prerun-build-checklist-20260609.json"],
        ),
        "unresolved_blocker_ledger": _report_ref(
            project_root,
            key="unresolved_blocker_ledger",
            candidates=["reports/d6/unresolved-blocker-ledger-20260609.json"],
        ),
        "btc_usdc_24h_live_start_decision_pack": _report_ref(
            project_root,
            key="btc_usdc_24h_live_start_decision_pack",
            candidates=["reports/d6/btc-usdc-24h-live-start-decision-pack-20260609.json"],
        ),
        "all_ticker_24h_workflow_readiness_pack": _report_ref(
            project_root,
            key="all_ticker_24h_workflow_readiness_pack",
            candidates=["reports/d6/all-ticker-24h-workflow-readiness-pack-20260609.json"],
        ),
        "all_ticker_operator_preflight_command_pack": _report_ref(
            project_root,
            key="all_ticker_operator_preflight_command_pack",
            candidates=["reports/d6/all-ticker-operator-preflight-command-pack-20260609.json"],
        ),
        "all_ticker_live_scope_guard": _report_ref(
            project_root,
            key="all_ticker_live_scope_guard",
            candidates=["reports/d6/all-ticker-live-scope-guard-20260609.json"],
        ),
        "all_ticker_live_readonly_preflight": _report_ref(
            project_root,
            key="all_ticker_live_readonly_preflight",
            candidates=["reports/d6/all-ticker-live-readonly-preflight-20260609.json"],
        ),
        "shadow_parameter_approximation_pack": _report_ref(
            project_root,
            key="shadow_parameter_approximation_pack",
            candidates=["reports/d6/shadow-parameter-approximation-pack-20260609.json"],
        ),
    }

    stop_reasons: List[str] = []
    watch_reasons: List[str] = []
    if int(open_summary.get("open_orders") or 0) > 0:
        stop_reasons.append("open_orders_present")
    if open_d3_exit > 0:
        stop_reasons.append("open_d3_exit_present")
    if audit.get("overall_status") != "ok_observe_only":
        stop_reasons.append("function_audit_not_ok_observe_only")
    if hash_drift:
        watch_reasons.append("state_hash_drift_detected")
    if include_selected_tests:
        if selected_tests["selected_tests_classification"] == "STOP_NOW":
            stop_reasons.append("selected_tests_required_failure")
        elif selected_tests["selected_tests_classification"] == "WATCH":
            watch_reasons.append("selected_tests_watch")

    for key, ref in refs.items():
        if not ref.get("available"):
            watch_reasons.append(str(ref.get("watch_reason") or f"optional_report_missing:{key}"))
    hygiene = refs["state_hygiene_cleanup_preview"]
    if hygiene.get("available"):
        hygiene_payload = _load_json(Path(str(hygiene["path"])))
        if hygiene_payload.get("status") == "STOP_NOW":
            stop_reasons.append("state_hygiene_stop_now")
        elif hygiene_payload.get("status") == "WATCH":
            watch_reasons.append("state_hygiene_watch")
    evidence = refs["d5_d6_evidence_expansion"]
    if evidence.get("available"):
        evidence_payload = _load_json(Path(str(evidence["path"])))
        if evidence_payload.get("classification") == "STOP_NOW":
            stop_reasons.append("d5_d6_evidence_stop_now")
        elif evidence_payload.get("classification") == "WATCH":
            watch_reasons.append("d5_d6_evidence_watch")
    all_ticker_gate = refs["all_ticker_readiness_gate"]
    if all_ticker_gate.get("available"):
        all_ticker_payload = _load_json(Path(str(all_ticker_gate["path"])))
        if all_ticker_payload.get("classification") == "STOP_NOW":
            stop_reasons.append("all_ticker_readiness_stop_now")
        elif all_ticker_payload.get("classification") == "WATCH":
            watch_reasons.append("all_ticker_readiness_watch")
    follower_audit = refs["follower_receiver_api_audit"]
    if follower_audit.get("available"):
        follower_payload = _load_json(Path(str(follower_audit["path"])))
        if follower_payload.get("classification") == "STOP_NOW":
            stop_reasons.append("follower_receiver_api_audit_stop_now")
        elif follower_payload.get("classification") == "WATCH":
            watch_reasons.append("follower_receiver_api_audit_watch")
    replay_ref = refs["multi_ticker_paper_lifecycle_replay"]
    if replay_ref.get("available"):
        replay_payload = _load_json(Path(str(replay_ref["path"])))
        if replay_payload.get("classification") == "STOP_NOW":
            stop_reasons.append("multi_ticker_paper_lifecycle_replay_stop_now")
        elif replay_payload.get("classification") == "WATCH":
            watch_reasons.append("multi_ticker_paper_lifecycle_replay_watch")
    product_cache_ref = refs["per_ticker_product_rule_evidence_cache"]
    if product_cache_ref.get("available"):
        product_cache_payload = _load_json(Path(str(product_cache_ref["path"])))
        if product_cache_payload.get("classification") == "STOP_NOW":
            stop_reasons.append("per_ticker_product_rule_evidence_cache_stop_now")
        elif product_cache_payload.get("classification") == "WATCH":
            watch_reasons.append("per_ticker_product_rule_evidence_cache_watch")
    d6_plan_ref = refs["d6_backlearning_parameter_evidence_plan"]
    if d6_plan_ref.get("available"):
        d6_plan_payload = _load_json(Path(str(d6_plan_ref["path"])))
        if d6_plan_payload.get("classification") == "STOP_NOW":
            stop_reasons.append("d6_backlearning_parameter_evidence_plan_stop_now")
        elif d6_plan_payload.get("classification") == "WATCH":
            watch_reasons.append("d6_backlearning_parameter_evidence_plan_watch")
    d6_decision_ref = refs["d6_human_review_decision_pack"]
    if d6_decision_ref.get("available"):
        d6_decision_payload = _load_json(Path(str(d6_decision_ref["path"])))
        if d6_decision_payload.get("classification") == "STOP_NOW":
            stop_reasons.append("d6_human_review_decision_pack_stop_now")
        elif d6_decision_payload.get("classification") == "WATCH":
            watch_reasons.append("d6_human_review_decision_pack_watch")
    product_fixture_ref = refs["product_rule_fixture_evidence"]
    if product_fixture_ref.get("available"):
        product_fixture_payload = _load_json(Path(str(product_fixture_ref["path"])))
        if product_fixture_payload.get("classification") == "STOP_NOW":
            stop_reasons.append("product_rule_fixture_evidence_stop_now")
        elif product_fixture_payload.get("classification") == "WATCH":
            watch_reasons.append("product_rule_fixture_evidence_watch")
    for key in (
        "d6_acceptance_policy",
        "d6_backlearning_label_export_pack",
        "roadmap_readiness_decision_map",
        "controlled_learning_governance",
        "d6_shadow_learning_report",
        "operator_24h_prerun_build_checklist",
        "unresolved_blocker_ledger",
        "btc_usdc_24h_live_start_decision_pack",
        "all_ticker_24h_workflow_readiness_pack",
        "all_ticker_operator_preflight_command_pack",
        "all_ticker_live_scope_guard",
    ):
        ref = refs[key]
        if ref.get("available"):
            payload = _load_json(Path(str(ref["path"])))
            if payload.get("classification") == "STOP_NOW":
                stop_reasons.append(f"{key}_stop_now")
            elif payload.get("classification") == "WATCH":
                watch_reasons.append(f"{key}_watch")
    for key in ("all_ticker_live_readonly_preflight", "shadow_parameter_approximation_pack"):
        ref = refs[key]
        if ref.get("available"):
            payload = _load_json(Path(str(ref["path"])))
            if payload.get("classification") == "STOP_NOW":
                stop_reasons.append(f"{key}_stop_now")

    if stop_reasons:
        classification = "STOP_NOW"
    elif watch_reasons:
        classification = "WATCH"
    else:
        classification = "OK"

    flags = _readiness_flags(refs, classification)
    flags["local_safe_regression_passed"] = classification in {"OK", "WATCH"} and not stop_reasons
    no_state_write_confirmed = initial_hashes == current_hashes

    conclusion = {
        "local_safe_regression_checks_passed": flags["local_safe_regression_passed"],
        "classification": classification,
        "live_start_status": "not_authorized_not_a_live_preflight",
        "what_still_blocks_live_start": [
            "fresh operator preflight not run by this harness",
            "exact live-start ACK missing",
            "master_ready_for_operator_live_start=false",
        ],
        "what_still_blocks_full_workflow": [
            "follower_ready_for_live=false",
            "follower_buy_ready=false",
            "follower_sell_ready=false",
            "lifecycle_parity_ready=false",
            "all_ticker_ready=false",
            "learning_to_execution_ready=false",
        ],
        "requires_explicit_ack": [
            "Coinbase poll or live order inspection",
            "live submit/cancel/replace/reprice",
            "lifecycle apply or terminal closeout apply",
            "state hygiene cleanup apply",
            "replication/follower live enablement",
            "parameter mutation or learning-to-execution",
        ],
    }

    return _json_safe(
        {
            "phase": PHASE_SAFE_REGRESSION_HARNESS,
            "generated_at": generated_at or _now_iso(),
            "report_mode": "local_report_only_safe_regression_harness",
            "classification": classification,
            "local_safe_regression_passed": flags["local_safe_regression_passed"],
            "stop_reasons": sorted(set(stop_reasons)),
            "watch_reasons": sorted(set(watch_reasons)),
            "no_coinbase_call": True,
            "no_http_replication_call": True,
            "no_http_call_confirmed": True,
            "no_live_action": True,
            "no_coinbase_call_confirmed": True,
            "state_write_performed": False,
            "no_state_write_confirmed": no_state_write_confirmed,
            "not_a_live_preflight": True,
            "does_not_authorize_live_trading": True,
            "open_order_summary": open_summary,
            "function_preservation_audit": {
                "overall_status": audit.get("overall_status"),
                "warnings": list(audit.get("warnings") or []),
                "order_store": audit.get("order_store") or {},
            },
            "state_hashes": {
                "initial": initial_hashes,
                "current": current_hashes,
                "expected": expected_hashes,
                "drift": hash_drift,
            },
            "selected_tests": selected_tests,
            "report_references": refs,
            "tool_availability": _tool_availability(project_root),
            "readiness_flags": flags,
            "human_readable_conclusion": conclusion,
        }
    )


def render_safe_regression_harness_markdown(report: Dict[str, Any]) -> str:
    flags = report.get("readiness_flags") or {}
    open_summary = report.get("open_order_summary") or {}
    audit = report.get("function_preservation_audit") or {}
    selected = report.get("selected_tests") or {}
    lines = [
        "# Safe Regression Harness",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- local_safe_regression_passed: `{report.get('local_safe_regression_passed')}`",
        f"- no_coinbase_call: `{report.get('no_coinbase_call')}`",
        f"- no_http_replication_call: `{report.get('no_http_replication_call')}`",
        f"- no_http_call_confirmed: `{report.get('no_http_call_confirmed')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- no_state_write_confirmed: `{report.get('no_state_write_confirmed')}`",
        f"- not_a_live_preflight: `{report.get('not_a_live_preflight')}`",
        "",
        "## Local Checks",
        "",
        f"- open_orders: `{open_summary.get('open_orders')}`",
        f"- open_d3_exit: `{open_summary.get('open_d3_exit')}`",
        f"- total_orders: `{open_summary.get('total_orders')}`",
        f"- function_audit: `{audit.get('overall_status')}`",
        f"- function_audit_warnings: `{'; '.join(audit.get('warnings') or [])}`",
        "",
        "## State Hashes",
        "",
    ]
    hashes = report.get("state_hashes") or {}
    for key, value in (hashes.get("current") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Classification Reasons", ""])
    lines.append(f"- stop_reasons: `{'; '.join(report.get('stop_reasons') or [])}`")
    lines.append(f"- watch_reasons: `{'; '.join(report.get('watch_reasons') or [])}`")
    lines.extend(["", "## Selected Tests", ""])
    lines.append(f"- selected_tests_enabled: `{selected.get('selected_tests_enabled')}`")
    lines.append(f"- selected_tests_classification: `{selected.get('selected_tests_classification')}`")
    lines.append(f"- selected_tests_run_count: `{selected.get('selected_tests_run_count')}`")
    lines.append(f"- selected_tests_passed_count: `{selected.get('selected_tests_passed_count')}`")
    lines.append(f"- selected_tests_failed_count: `{selected.get('selected_tests_failed_count')}`")
    lines.append(f"- selected_tests_missing_optional_count: `{selected.get('selected_tests_missing_optional_count')}`")
    for result in selected.get("selected_test_results") or []:
        lines.append(
            f"- {result.get('path')}: status=`{result.get('status')}`, required=`{result.get('required')}`, "
            f"duration_seconds=`{result.get('duration_seconds')}`"
        )
    lines.extend(["", "## Report References", ""])
    for key, ref in (report.get("report_references") or {}).items():
        lines.append(
            f"- {key}: available=`{ref.get('available')}`, status=`{ref.get('status')}`, path=`{ref.get('path')}`"
        )
    lines.extend(["", "## Readiness Flags", ""])
    for key in (
        "local_safe_regression_passed",
        "master_ready_for_operator_preflight",
        "master_ready_for_operator_live_start",
        "master_live_exit_ready",
        "follower_receiver_code_accessible",
        "follower_receiver_api_audit_complete",
        "follower_ready_for_paper_lifecycle_test",
        "follower_buy_ready",
        "follower_ready_for_live",
        "follower_sell_ready",
        "lifecycle_parity_ready",
        "all_ticker_ready",
        "learning_to_execution_ready",
        "d6_acceptance_policy_ready",
        "d6_backlearning_label_export_pack_ready",
        "controlled_learning_governance_ready",
        "current_max_allowed_learning_stage",
        "parameter_proposal_candidate",
        "d6_shadow_learning_report_ready",
        "report_only_shadow_learning_ready",
        "execution_bridge_created",
        "operator_24h_prerun_build_checklist_ready",
        "build_complete_for_operator_live_start_review",
        "live_start_authorized",
        "operator_manual_start_required",
        "unresolved_blocker_ledger_ready",
        "remaining_locally_buildable_item_count",
        "btc_usdc_24h_live_start_decision_pack_ready",
        "ready_for_operator_fresh_preflight",
        "all_ticker_24h_workflow_readiness_pack_ready",
        "all_ticker_operator_preflight_command_pack_ready",
        "all_ticker_monitor_scaffold_ready",
        "all_ticker_post_run_evidence_scaffold_ready",
        "all_ticker_live_scope_guard_ready",
        "all_ticker_workflow_built_locally",
        "all_ticker_ready_for_operator_fresh_preflight",
        "all_ticker_live_readonly_preflight_tool_ready",
        "all_ticker_live_readonly_preflight_attempted",
        "all_ticker_live_readonly_preflight_passed",
        "all_ticker_live_authorized",
        "btc_usdc_ready_for_operator_fresh_preflight",
        "non_btc_tickers_ready_for_operator_fresh_preflight",
        "roadmap_readiness_decision_map_ready",
        "d6_backlearning_parameter_evidence_plan_ready",
        "d6_human_review_decision_pack_ready",
        "human_review_ready",
        "parameter_review_candidate",
        "parameter_values_proposed",
        "shadow_parameter_approximation_pack_ready",
        "product_rule_fixture_evidence_ready",
        "fixture_evidence_ticker_count",
        "paper_replay_usable_ticker_count",
        "parameter_review_approved",
        "parameter_change_allowed",
        "safe_to_mutate_parameters_now",
        "live_learning_allowed",
        "state_hygiene_cleanup_preview_ready",
        "state_hygiene_apply_ready",
    ):
        lines.append(f"- {key}: `{flags.get(key, report.get(key))}`")
    conclusion = report.get("human_readable_conclusion") or {}
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            f"- local_safe_regression_checks_passed: `{conclusion.get('local_safe_regression_checks_passed')}`",
            f"- live_start_status: `{conclusion.get('live_start_status')}`",
            f"- what_still_blocks_live_start: `{'; '.join(conclusion.get('what_still_blocks_live_start') or [])}`",
            f"- what_still_blocks_full_workflow: `{'; '.join(conclusion.get('what_still_blocks_full_workflow') or [])}`",
            f"- requires_explicit_ack: `{'; '.join(conclusion.get('requires_explicit_ack') or [])}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_SAFE_REGRESSION_HARNESS",
    "SELECTED_TEST_ALLOWLIST",
    "build_safe_regression_harness",
    "render_safe_regression_harness_markdown",
]
