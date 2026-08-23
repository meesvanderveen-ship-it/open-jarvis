from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from tools.show_function_preservation_audit import build_audit_report
except Exception:  # pragma: no cover - import guard for isolated fixtures
    build_audit_report = None  # type: ignore[assignment]


PHASE_BTC_USDC_24H_LIVE_START_DECISION_PACK = "btc_usdc_24h_live_start_decision_pack_v1"
LATEST_OPEN_ORDERS_HASH = "919115b9fbcc20e137a1cfb18e87a4858482ab5c06c3fdb3e5c0e61079066b60"
LATEST_POSITIONS_HASH = "d288bc7ca3a9b11fc78e29aa4407036c1e9f66b6b4597b4e0293d4bf615965c2"
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
ACTUAL_SUBMIT_ACK = "I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC"


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


def _sha256(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _orders_from_state(path: Path) -> List[Dict[str, Any]]:
    payload = _load_json(path)
    orders = payload.get("orders")
    if isinstance(orders, dict):
        return [dict(row) for row in orders.values() if isinstance(row, dict)]
    if isinstance(orders, list):
        return [dict(row) for row in orders if isinstance(row, dict)]
    return []


def _is_open(order: Dict[str, Any]) -> bool:
    return str(order.get("status") or "").strip().lower() in OPEN_STATUSES


def _is_d3_exit(order: Dict[str, Any]) -> bool:
    side = str(order.get("side") or "").strip().upper()
    cid = str(order.get("client_order_id") or "").strip().lower()
    phase = str(order.get("phase") or "").strip()
    mode = str(order.get("mode") or order.get("source_mode") or "").strip().lower()
    return side == "SELL" and (
        phase == "D3_controlled_live_reduce_only_exits"
        or cid.startswith("phased3-")
        or cid.startswith("phased4-")
        or "d3" in mode
    )


def _command(command: str, purpose: str, *, operator_only: bool = True) -> Dict[str, Any]:
    return {
        "purpose": purpose,
        "command": command,
        "operator_only": operator_only,
        "codex_must_not_run": operator_only,
    }


def _command_templates(root: Path) -> Dict[str, Any]:
    tool_paths = {
        "selected_harness": root / "tools/run_safe_regression_harness.py",
        "show_open_orders": root / "tools/show_open_orders.py",
        "function_audit": root / "tools/show_function_preservation_audit.py",
        "tiny_env": root / "tools/operator_btc_usdc_tiny_env.sh",
        "tiny_preflight": root / "tools/show_btc_usdc_tiny_live_preflight.py",
        "monitor": root / "tools/show_btc_usdc_24h_live_monitor.py",
        "post_run": root / "tools/build_btc_usdc_24h_post_run_evidence_pack.py",
        "loop": root / "run_trader_loop.py",
    }
    missing = [key for key, path in tool_paths.items() if not path.exists()]
    commands = [
        _command(
            "python3 tools/run_safe_regression_harness.py --include-selected-tests "
            "--json-out reports/d6/safe-regression-harness-$(date -u +%Y%m%d).json "
            "--markdown-out reports/d6/safe-regression-harness-$(date -u +%Y%m%d).md",
            "OPERATOR ONLY - CODEX MUST NOT RUN: refresh local selected-test harness before manual start review.",
        ),
        _command(
            "python3 tools/show_open_orders.py --open-only --json --limit 20",
            "OPERATOR ONLY - CODEX MUST NOT RUN: confirm local open_orders=0.",
        ),
        _command(
            "python3 tools/show_function_preservation_audit.py --fail-on-review",
            "OPERATOR ONLY - CODEX MUST NOT RUN: confirm function preservation audit remains ok_observe_only.",
        ),
        _command(
            "tools/operator_btc_usdc_tiny_env.sh .venv/bin/python tools/show_btc_usdc_tiny_live_preflight.py "
            f"--actual-submit-ack {ACTUAL_SUBMIT_ACK} --require-actual-submit-enabled",
            "OPERATOR ONLY - CODEX MUST NOT RUN: local BTC-USDC tiny preflight template; no Coinbase call in this tool.",
        ),
        _command(
            "tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py --startup-diagnostic",
            "OPERATOR ONLY - CODEX MUST NOT RUN: startup diagnostic before any manual live run.",
        ),
        _command(
            f"BTC_USDC_TINY_ACTUAL_SUBMIT_ACK={ACTUAL_SUBMIT_ACK} "
            "tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py",
            "OPERATOR ONLY - CODEX MUST NOT RUN: manual BTC-USDC 24h run start command template.",
        ),
        _command(
            "python3 tools/show_btc_usdc_24h_live_monitor.py --json --since-utc <OPERATOR_START_UTC>",
            "OPERATOR ONLY - CODEX MUST NOT RUN: local read-only monitor during operator-started run.",
        ),
        _command(
            "pgrep -af 'run_trader_loop.py'  # operator reviews PID, then stops only the intended manual process",
            "OPERATOR ONLY - CODEX MUST NOT RUN: stop/disable review template; prefer Ctrl-C in the manual run terminal.",
        ),
        _command(
            "python3 tools/build_btc_usdc_24h_post_run_evidence_pack.py "
            "--start-utc <OPERATOR_START_UTC> --stop-utc <OPERATOR_STOP_UTC> "
            "--json-out reports/live/btc-usdc-24h-post-run-evidence-<DATE>.json "
            "--markdown-out reports/live/btc-usdc-24h-post-run-evidence-<DATE>.md",
            "OPERATOR ONLY - CODEX MUST NOT RUN: build local post-run evidence after the manual test ends.",
        ),
    ]
    return {"commands": commands, "missing_command_templates": missing, "tool_paths": {k: str(v) for k, v in tool_paths.items()}}


def build_btc_usdc_24h_live_start_decision_pack(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    function_audit_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    harness = _load_json(project_root / "reports/d6/safe-regression-harness-20260609.json")
    checklist = _load_json(project_root / "reports/d6/operator-24h-prerun-build-checklist-20260609.json")
    ledger = _load_json(project_root / "reports/d6/unresolved-blocker-ledger-20260609.json")
    decision_map = _load_json(project_root / "reports/d6/roadmap-readiness-decision-map-20260609.json")
    shadow = _load_json(project_root / "reports/d6/d6-shadow-learning-report-20260609.json")
    controlled = _load_json(project_root / "reports/d6/controlled-learning-governance-20260609.json")

    harness_flags = harness.get("readiness_flags") if isinstance(harness.get("readiness_flags"), dict) else {}
    selected = harness.get("selected_tests") if isinstance(harness.get("selected_tests"), dict) else {}
    checklist_flags = checklist.get("governance_flags") if isinstance(checklist.get("governance_flags"), dict) else {}
    ledger_flags = ledger.get("governance_flags") if isinstance(ledger.get("governance_flags"), dict) else {}

    orders = _orders_from_state(project_root / "state/open_orders.json")
    open_orders_actual = sum(1 for order in orders if _is_open(order))
    open_d3_exit_actual = sum(1 for order in orders if _is_open(order) and _is_d3_exit(order))
    audit = function_audit_report
    if audit is None and build_audit_report is not None:
        audit = build_audit_report(project_root)
    audit = audit or {"overall_status": "unknown"}
    audit_status = str(audit.get("overall_status") or "unknown")
    hashes = {
        "state/open_orders.json": _sha256(project_root / "state/open_orders.json"),
        "state/positions.json": _sha256(project_root / "state/positions.json"),
    }
    hash_match = (
        hashes["state/open_orders.json"] == LATEST_OPEN_ORDERS_HASH
        and hashes["state/positions.json"] == LATEST_POSITIONS_HASH
    )
    commands = _command_templates(project_root)

    local_build_closure_complete = bool(
        checklist_flags.get("build_complete_for_operator_live_start_review")
        and ledger_flags.get("remaining_locally_buildable_item_count", 999) == 0
    )
    selected_ok = selected.get("selected_tests_classification") == "OK"
    command_templates_ok = not commands["missing_command_templates"]
    blockers: List[str] = []
    warnings: List[str] = [
        "Coinbase product/balance/fresh live preflight was not run by Codex.",
        "This pack is not live authorization and does not start the 24h test.",
    ]
    if open_orders_actual != 0:
        blockers.append("open_orders_nonzero")
    if open_d3_exit_actual != 0:
        blockers.append("open_d3_exit_nonzero")
    if audit_status != "ok_observe_only":
        blockers.append("function_preservation_audit_not_ok")
    if not selected_ok:
        blockers.append("selected_tests_not_ok")
    if not local_build_closure_complete:
        blockers.append("local_build_closure_incomplete")
    if not command_templates_ok:
        blockers.append("missing_command_template")
    if not hash_match:
        warnings.append("state_hashes_do_not_match_latest_checkpoint")

    if any(reason in blockers for reason in ("open_orders_nonzero", "open_d3_exit_nonzero", "function_preservation_audit_not_ok")):
        decision_status = "blocked_by_STOP"
    elif any(reason in blockers for reason in ("selected_tests_not_ok", "local_build_closure_incomplete", "missing_command_template")):
        decision_status = "not_ready_local_blockers"
    else:
        decision_status = "ready_for_operator_fresh_preflight"

    ready_for_operator_fresh_preflight = decision_status == "ready_for_operator_fresh_preflight"
    report = {
        "phase": PHASE_BTC_USDC_24H_LIVE_START_DECISION_PACK,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "decision_pack_only": True,
            "codex_must_not_start_live_test": True,
            "operator_manual_start_required": True,
            "live_start_authorized": False,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "order_action_attempted": False,
            "lifecycle_apply_attempted": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
            "learning_to_execution_performed": False,
        },
        "classification": "OK" if ready_for_operator_fresh_preflight else "STOP_NOW" if decision_status == "blocked_by_STOP" else "WATCH",
        "decision_status": decision_status,
        "ready_for_operator_fresh_preflight": ready_for_operator_fresh_preflight,
        "build_readiness_summary": {
            "local_build_closure_complete": local_build_closure_complete,
            "remaining_locally_buildable_item_count": int(ledger_flags.get("remaining_locally_buildable_item_count") or 0),
            "selected_tests_classification": selected.get("selected_tests_classification"),
            "selected_tests_passed_count": int(selected.get("selected_tests_passed_count") or 0),
            "selected_tests_failed_count": int(selected.get("selected_tests_failed_count") or 0),
            "operator_24h_prerun_build_checklist_ready": bool(checklist_flags.get("operator_24h_prerun_build_checklist_ready")),
            "unresolved_blocker_ledger_ready": bool(ledger_flags.get("unresolved_blocker_ledger_ready")),
            "roadmap_readiness_decision_map_ready": bool((decision_map.get("governance_flags") or {}).get("roadmap_readiness_decision_map_ready")),
            "monitor_test_present": (project_root / "tests/test_btc_usdc_24h_monitor.py").exists(),
            "post_run_evidence_pack_present": (project_root / "tools/build_btc_usdc_24h_post_run_evidence_pack.py").exists(),
            "d6_governance_ready": bool(shadow and controlled),
            "learning_to_execution_ready": False,
            "parameter_change_allowed": False,
            "all_ticker_live_allowed_now": False,
            "follower_ready_for_live": False,
        },
        "current_safety_state": {
            "open_orders_expected": 0,
            "open_orders_actual": open_orders_actual,
            "open_d3_exit_expected": 0,
            "open_d3_exit_actual": open_d3_exit_actual,
            "function_preservation_audit_status": audit_status,
            "state_hashes_current": hashes,
            "state_hashes_match_latest_checkpoint": hash_match,
            "blockers": blockers,
            "warnings": warnings,
        },
        "btc_usdc_operator_route": {
            "target_ticker": "BTC-USDC",
            "scope": "BTC-USDC only",
            "max_quote_usdc": "10",
            "max_open_positions": 1,
            "max_new_orders_per_cycle": 1,
            "live_exits_disabled": True,
            "all_ticker_live_disabled": True,
            "follower_live_disabled": True,
            "learning_to_execution_disabled": True,
            "parameter_mutation_disabled": True,
            "operator_manual_start_required": True,
            "codex_must_not_start_this_route": True,
        },
        "required_operator_pre_start_checklist": [
            "confirm normal systemd loop is stopped or not running in parallel",
            "run fresh local safe regression harness",
            "run fresh BTC-USDC preflight",
            "confirm open_orders=0",
            "confirm open_d3_exit=0",
            "confirm function audit ok",
            "confirm no STOP_NOW",
            f"confirm exact ACK token: {ACTUAL_SUBMIT_ACK}",
            "confirm live exits remain disabled",
            "confirm all-ticker live remains disabled",
            "confirm follower live remains disabled",
            "confirm learning-to-execution remains disabled",
            "confirm operator understands Codex does not start the loop",
        ],
        "operator_only_commands_do_not_run_by_codex": commands["commands"],
        "missing_command_templates": commands["missing_command_templates"],
        "hard_blockers_that_remain": [
            "live_start requires exact operator ACK",
            "Coinbase product/balance/fresh preflight not run by Codex",
            "state hygiene apply remains ACK-gated",
            "live SELL/exits remain disabled",
            "all-ticker live remains disabled",
            "follower live remains disabled",
            "parameter mutation remains disabled",
            "learning-to-execution remains disabled",
            "Codex must not start 24h test",
        ],
        "governance_flags": {
            "btc_usdc_24h_live_start_decision_pack_ready": True,
            "ready_for_operator_fresh_preflight": ready_for_operator_fresh_preflight,
            "live_start_authorized": False,
            "operator_manual_start_required": True,
            "codex_must_not_start_live_test": True,
            "local_safe_regression_passed": bool(harness_flags.get("local_safe_regression_passed")),
            "selected_tests_classification": selected.get("selected_tests_classification"),
            "selected_tests_passed_count": int(selected.get("selected_tests_passed_count") or 0),
            "selected_tests_failed_count": int(selected.get("selected_tests_failed_count") or 0),
            "remaining_locally_buildable_item_count": int(ledger_flags.get("remaining_locally_buildable_item_count") or 0),
            "open_orders": open_orders_actual,
            "open_d3_exit": open_d3_exit_actual,
            "function_preservation_audit_status": audit_status,
            "learning_to_execution_ready": False,
            "parameter_change_allowed": False,
            "all_ticker_live_allowed_now": False,
            "follower_ready_for_live": False,
            "state_hygiene_apply_ready": False,
        },
    }
    return _json_safe(report)


def render_btc_usdc_24h_live_start_decision_pack_markdown(report: Dict[str, Any]) -> str:
    flags = report.get("governance_flags") or {}
    safety = report.get("current_safety_state") or {}
    lines = [
        "# BTC-USDC 24h Live-Start Decision Pack",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- decision_status: `{report.get('decision_status')}`",
        f"- ready_for_operator_fresh_preflight: `{report.get('ready_for_operator_fresh_preflight')}`",
        f"- live_start_authorized: `{flags.get('live_start_authorized')}`",
        f"- operator_manual_start_required: `{flags.get('operator_manual_start_required')}`",
        f"- codex_must_not_start_live_test: `{flags.get('codex_must_not_start_live_test')}`",
        "",
        "## Current Safety State",
        "",
        f"- open_orders: `{safety.get('open_orders_actual')}`",
        f"- open_d3_exit: `{safety.get('open_d3_exit_actual')}`",
        f"- function_preservation_audit_status: `{safety.get('function_preservation_audit_status')}`",
        f"- blockers: `{'; '.join(safety.get('blockers') or [])}`",
        f"- warnings: `{'; '.join(safety.get('warnings') or [])}`",
        "",
        "## Governance Flags",
        "",
    ]
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## OPERATOR ONLY - CODEX MUST NOT RUN", ""])
    for row in report.get("operator_only_commands_do_not_run_by_codex") or []:
        lines.append(f"- {row.get('purpose')}")
        lines.append(f"  - `{row.get('command')}`")
    lines.extend(["", "## Hard Blockers That Remain", ""])
    for blocker in report.get("hard_blockers_that_remain") or []:
        lines.append(f"- {blocker}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_BTC_USDC_24H_LIVE_START_DECISION_PACK",
    "build_btc_usdc_24h_live_start_decision_pack",
    "render_btc_usdc_24h_live_start_decision_pack_markdown",
]
