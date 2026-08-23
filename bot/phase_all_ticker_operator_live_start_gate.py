from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS
from tools.show_function_preservation_audit import build_audit_report
from tools.show_open_orders import build_summary as build_open_order_summary
from tools.show_open_orders import load_orders


PHASE_ALL_TICKER_OPERATOR_LIVE_START_GATE = "all_ticker_operator_live_start_gate_v1"
ALL_TICKER_ACTUAL_SUBMIT_ACK = "I_APPROVE_ALL_TICKER_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC"
TINY_MAX_DEFAULT_QUOTE = Decimal("10")
TINY_MAX_ORDER_QUOTE = Decimal("10")
TINY_MAX_NOTIONAL = Decimal("25")
TINY_MAX_AUTONOMOUS_ORDER_QUOTE = Decimal("25")
TINY_MAX_OPEN_POSITIONS = 4
TINY_MAX_ENTRY_ORDERS = 4
TINY_MAX_OPEN_ORDERS = 4
TINY_MAX_NEW_ORDERS_PER_CYCLE = 1
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        if not text:
            return default
        return int(Decimal(text))
    except Exception:
        return default


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: Any) -> List[str]:
    return [part.strip().upper() for part in str(value or "").split(",") if part.strip()]


def _latest_preflight_path(root: Path) -> Optional[Path]:
    paths = sorted((root / "reports" / "d6").glob("all-ticker-live-readonly-preflight*.json"))
    if not paths:
        return None
    return max(paths, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _is_open_order(order: Dict[str, Any]) -> bool:
    return str(order.get("status") or "").strip().lower() in OPEN_STATUSES


def _is_d3_exit(order: Dict[str, Any]) -> bool:
    side = str(order.get("side") or "").strip().upper()
    client_order_id = str(order.get("client_order_id") or "").strip().lower()
    phase = str(order.get("phase") or "").strip()
    mode = str(order.get("mode") or order.get("source_mode") or "").strip().lower()
    return side == "SELL" and (
        phase == "D3_controlled_live_reduce_only_exits"
        or client_order_id.startswith("phased3-")
        or client_order_id.startswith("phased4-")
        or "d3" in mode
    )


def _env_snapshot(environ: Dict[str, str]) -> Dict[str, Any]:
    keys = [
        "ALL_TICKER_TINY_WRAPPER_MODE",
        "OPERATOR_ALL_TICKER_TINY_ENV_READY",
        "EXECUTION_MODE",
        "ALLOWED_TICKERS",
        "PHASE_C_ALLOWED_TICKERS",
        "DEFAULT_QUOTE_SIZE_USDC",
        "PHASE_C_MAX_ORDER_QUOTE",
        "MAX_NOTIONAL_USD",
        "AUTONOMOUS_MAX_ORDER_QUOTE",
        "MAX_OPEN_POSITIONS",
        "MAX_NEW_ORDERS_PER_CYCLE",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE",
        "AUTONOMOUS_MAX_OPEN_ORDERS",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE",
        "ENABLE_LIVE_ENTRY_ORDERS",
        "ENABLE_LIVE_LIMIT_ORDERS",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT",
        "ENABLE_LIVE_EXIT_ORDERS",
        "AUTONOMOUS_ALLOW_EXITS",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS",
        "REPLICATION_ENABLED",
        "LEARNING_TO_EXECUTION_READY",
        "LEARNING_TO_EXECUTION_ALLOWED",
        "LIVE_LEARNING_ALLOWED",
        "PARAMETER_CHANGE_ALLOWED",
    ]
    return {key: environ.get(key, "") for key in keys}


def _cap_checks(env: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "default_quote_size_usdc": str(_to_decimal(env.get("DEFAULT_QUOTE_SIZE_USDC"))),
        "phase_c_max_order_quote": str(_to_decimal(env.get("PHASE_C_MAX_ORDER_QUOTE"))),
        "max_notional_usd": str(_to_decimal(env.get("MAX_NOTIONAL_USD"))),
        "autonomous_max_order_quote": str(_to_decimal(env.get("AUTONOMOUS_MAX_ORDER_QUOTE"))),
        "max_open_positions": _to_int(env.get("MAX_OPEN_POSITIONS")),
        "phase_c_max_open_entry_orders": _to_int(env.get("PHASE_C_MAX_OPEN_ENTRY_ORDERS")),
        "autonomous_max_open_orders": _to_int(env.get("AUTONOMOUS_MAX_OPEN_ORDERS")),
        "max_new_orders_per_cycle": _to_int(env.get("MAX_NEW_ORDERS_PER_CYCLE")),
        "phase_c_max_new_orders_per_cycle": _to_int(env.get("PHASE_C_MAX_NEW_ORDERS_PER_CYCLE")),
        "autonomous_max_new_orders_per_cycle": _to_int(env.get("AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE")),
    }


def _caps_are_tiny(caps: Dict[str, Any]) -> bool:
    return (
        _to_decimal(caps.get("default_quote_size_usdc")) <= TINY_MAX_DEFAULT_QUOTE
        and _to_decimal(caps.get("phase_c_max_order_quote")) <= TINY_MAX_ORDER_QUOTE
        and _to_decimal(caps.get("max_notional_usd")) <= TINY_MAX_NOTIONAL
        and _to_decimal(caps.get("autonomous_max_order_quote")) <= TINY_MAX_AUTONOMOUS_ORDER_QUOTE
        and int(caps.get("max_open_positions") or 0) <= TINY_MAX_OPEN_POSITIONS
        and int(caps.get("phase_c_max_open_entry_orders") or 0) <= TINY_MAX_ENTRY_ORDERS
        and int(caps.get("autonomous_max_open_orders") or 0) <= TINY_MAX_OPEN_ORDERS
        and int(caps.get("max_new_orders_per_cycle") or 0) <= TINY_MAX_NEW_ORDERS_PER_CYCLE
        and int(caps.get("phase_c_max_new_orders_per_cycle") or 0) <= TINY_MAX_NEW_ORDERS_PER_CYCLE
        and int(caps.get("autonomous_max_new_orders_per_cycle") or 0) <= TINY_MAX_NEW_ORDERS_PER_CYCLE
    )


def _command(command: str, purpose: str) -> Dict[str, Any]:
    return {
        "purpose": purpose,
        "command": command,
        "operator_only": True,
        "codex_must_not_run": True,
    }


def _operator_commands() -> Dict[str, Any]:
    gate = (
        f"ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK={ALL_TICKER_ACTUAL_SUBMIT_ACK} "
        "tools/operator_all_ticker_tiny_env.sh .venv/bin/python tools/show_all_ticker_operator_live_start_gate.py "
        "--json-out reports/d6/all-ticker-operator-live-start-gate-$(date -u +%Y%m%d).json "
        "--markdown-out reports/d6/all-ticker-operator-live-start-gate-$(date -u +%Y%m%d).md"
    )
    run = (
        f"ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK={ALL_TICKER_ACTUAL_SUBMIT_ACK} "
        "tools/operator_all_ticker_tiny_env.sh .venv/bin/python run_trader_loop.py"
    )
    return {
        "acked_gate_check": _command(
            gate,
            "OPERATOR ONLY - CODEX MUST NOT RUN: later ACKed all-ticker gate check.",
        ),
        "acked_run_do_not_run_yet": _command(
            run,
            "OPERATOR ONLY - DO NOT RUN YET: later manual all-ticker 24h run start command.",
        ),
    }


def _all_tickers_present(tickers: Iterable[str]) -> bool:
    return list(tickers) == list(DEFAULT_TICKERS)


def build_all_ticker_operator_live_start_gate(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    environ: Optional[Dict[str, str]] = None,
    function_audit_report: Optional[Dict[str, Any]] = None,
    preflight_path: str | Path | None = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    env = _env_snapshot(dict(environ or os.environ))
    ack_present = dict(environ or os.environ).get("ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK") == ALL_TICKER_ACTUAL_SUBMIT_ACK
    orders = load_orders(project_root / "state/open_orders.json")
    order_summary = dict(build_open_order_summary(orders))
    open_orders = int(order_summary.get("open_orders") or 0)
    open_d3_exit = sum(1 for order in orders if _is_open_order(order) and _is_d3_exit(order))
    harness = _load_json(project_root / "reports/d6/safe-regression-harness-20260609.json")
    selected = harness.get("selected_tests") if isinstance(harness.get("selected_tests"), dict) else {}
    selected_tests_classification = str(selected.get("selected_tests_classification") or "UNKNOWN")

    audit = function_audit_report
    if audit is None:
        try:
            audit = build_audit_report(project_root)
        except Exception as exc:
            audit = {"overall_status": "review_required", "warnings": [f"audit_load_failed:{type(exc).__name__}"]}
    function_audit_status = str((audit or {}).get("overall_status") or "unknown")

    selected_preflight_path = Path(preflight_path) if preflight_path else _latest_preflight_path(project_root)
    if selected_preflight_path and not selected_preflight_path.is_absolute():
        selected_preflight_path = project_root / selected_preflight_path
    preflight = _load_json(selected_preflight_path) if selected_preflight_path else {}
    gate = preflight.get("gate_decision") if isinstance(preflight.get("gate_decision"), dict) else {}
    per_ticker = preflight.get("per_ticker_preflight") if isinstance(preflight.get("per_ticker_preflight"), list) else []
    preflight_attempted = bool(gate.get("all_ticker_live_readonly_preflight_attempted"))
    preflight_passed = bool(gate.get("all_ticker_live_readonly_preflight_passed"))
    blocked_ticker_count = int(gate.get("blocked_ticker_count") or sum(1 for row in per_ticker if isinstance(row, dict) and row.get("blockers")))
    preflight_tickers = [str(row.get("ticker") or "").upper() for row in per_ticker if isinstance(row, dict)]

    allowed_tickers = _split_csv(env.get("ALLOWED_TICKERS"))
    phase_c_allowed_tickers = _split_csv(env.get("PHASE_C_ALLOWED_TICKERS"))
    caps = _cap_checks(env)
    caps_tiny = _caps_are_tiny(caps)
    actual_submit_enabled = _as_bool(env.get("ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT"))
    actual_submit_ack_aligned = bool((not actual_submit_enabled) or ack_present)
    live_exits_enabled = _as_bool(env.get("ENABLE_LIVE_EXIT_ORDERS"))
    autonomous_exits_enabled = _as_bool(env.get("AUTONOMOUS_ALLOW_EXITS"))
    d3_actual_exit_submit_enabled = _as_bool(env.get("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT"))
    replication_enabled = _as_bool(env.get("REPLICATION_ENABLED"))
    learning_to_execution_ready = _as_bool(env.get("LEARNING_TO_EXECUTION_READY")) or _as_bool(
        env.get("LEARNING_TO_EXECUTION_ALLOWED")
    )
    live_learning_allowed = _as_bool(env.get("LIVE_LEARNING_ALLOWED"))
    parameter_change_allowed = _as_bool(env.get("PARAMETER_CHANGE_ALLOWED"))

    checks = {
        "selected_tests_ok": selected_tests_classification == "OK",
        "open_orders_zero": open_orders == 0,
        "open_d3_exit_zero": open_d3_exit == 0,
        "function_audit_ok_observe_only": function_audit_status == "ok_observe_only",
        "preflight_artifact_present": bool(selected_preflight_path and selected_preflight_path.exists()),
        "latest_all_ticker_live_readonly_preflight_attempted": preflight_attempted,
        "latest_all_ticker_live_readonly_preflight_passed": preflight_passed,
        "blocked_ticker_count_zero": blocked_ticker_count == 0,
        "preflight_includes_all_18_tickers": _all_tickers_present(preflight_tickers),
        "wrapper_allowed_tickers_all_18": _all_tickers_present(allowed_tickers),
        "wrapper_phase_c_allowed_tickers_all_18": _all_tickers_present(phase_c_allowed_tickers),
        "wrapper_mode_present": _as_bool(env.get("ALL_TICKER_TINY_WRAPPER_MODE"))
        and _as_bool(env.get("OPERATOR_ALL_TICKER_TINY_ENV_READY")),
        "caps_tiny_conservative": caps_tiny,
        "live_entries_enabled": _as_bool(env.get("ENABLE_LIVE_ENTRY_ORDERS"))
        and _as_bool(env.get("ENABLE_LIVE_LIMIT_ORDERS"))
        and _as_bool(env.get("ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS")),
        "actual_submit_requires_exact_ack": actual_submit_ack_aligned,
        "live_exits_disabled": not live_exits_enabled,
        "autonomous_exits_disabled": not autonomous_exits_enabled,
        "d3_actual_exit_submit_disabled": not d3_actual_exit_submit_enabled,
        "replication_disabled": not replication_enabled,
        "learning_to_execution_disabled": not learning_to_execution_ready,
        "live_learning_disabled": not live_learning_allowed,
        "parameter_change_disallowed": not parameter_change_allowed,
        "exact_all_ticker_ack_present": ack_present,
    }

    blockers: List[str] = []
    blocker_map = {
        "selected_tests_ok": "selected_tests_not_ok",
        "open_orders_zero": "open_orders_nonzero",
        "open_d3_exit_zero": "open_d3_exit_nonzero",
        "function_audit_ok_observe_only": "function_preservation_audit_not_ok",
        "preflight_artifact_present": "all_ticker_live_readonly_preflight_missing",
        "latest_all_ticker_live_readonly_preflight_attempted": "all_ticker_live_readonly_preflight_not_attempted",
        "latest_all_ticker_live_readonly_preflight_passed": "all_ticker_live_readonly_preflight_failed",
        "blocked_ticker_count_zero": "blocked_ticker_count_nonzero",
        "preflight_includes_all_18_tickers": "preflight_ticker_count_incomplete",
        "wrapper_allowed_tickers_all_18": "wrapper_allowed_ticker_scope_incomplete",
        "wrapper_phase_c_allowed_tickers_all_18": "wrapper_phase_c_ticker_scope_incomplete",
        "wrapper_mode_present": "all_ticker_wrapper_not_active",
        "caps_tiny_conservative": "caps_exceed_tiny_conservative_bounds",
        "live_entries_enabled": "live_entry_flags_not_enabled",
        "actual_submit_requires_exact_ack": "actual_submit_true_without_exact_ack",
        "live_exits_disabled": "live_exits_enabled",
        "autonomous_exits_disabled": "autonomous_exits_enabled",
        "d3_actual_exit_submit_disabled": "d3_actual_exit_submit_enabled",
        "replication_disabled": "replication_enabled",
        "learning_to_execution_disabled": "learning_to_execution_ready",
        "live_learning_disabled": "live_learning_allowed",
        "parameter_change_disallowed": "parameter_change_allowed",
        "exact_all_ticker_ack_present": "all_ticker_ack_missing",
    }
    for check, passed in checks.items():
        if not passed:
            blockers.append(blocker_map[check])

    non_ack_blockers = [blocker for blocker in blockers if blocker != "all_ticker_ack_missing"]
    ready_for_operator_ack = not non_ack_blockers and not ack_present
    all_ticker_operator_live_start_gate_ready = not non_ack_blockers
    live_start_authorized = bool(all_ticker_operator_live_start_gate_ready and ack_present and actual_submit_enabled)
    classification = "OK" if live_start_authorized or ready_for_operator_ack else "STOP_NOW"
    commands = _operator_commands()
    state_hashes = {
        "state/open_orders.json": _sha256(project_root / "state/open_orders.json"),
        "state/positions.json": _sha256(project_root / "state/positions.json"),
    }
    report = {
        "phase": PHASE_ALL_TICKER_OPERATOR_LIVE_START_GATE,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "gate_only": True,
            "codex_must_not_start_live_test": True,
            "operator_manual_start_required": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "order_action_attempted": False,
            "submit_attempted": False,
            "cancel_attempted": False,
            "replace_attempted": False,
            "reprice_attempted": False,
            "lifecycle_apply_attempted": False,
            "state_write_performed": False,
            "env_mutation_performed": False,
            "config_mutation_performed": False,
            "parameter_mutation_performed": False,
            "live_start_attempted": False,
        },
        "classification": classification,
        "status": "authorized_for_operator_manual_start_only" if live_start_authorized else (
            "ready_for_operator_ack" if ready_for_operator_ack else "blocked"
        ),
        "all_ticker_ack_required": ALL_TICKER_ACTUAL_SUBMIT_ACK,
        "all_ticker_ack_present": ack_present,
        "all_ticker_operator_live_start_gate_ready": all_ticker_operator_live_start_gate_ready,
        "ready_for_operator_ack": ready_for_operator_ack,
        "live_start_authorized": live_start_authorized,
        "codex_must_not_start_live_test": True,
        "operator_manual_start_required": True,
        "blockers": blockers,
        "non_ack_blockers": non_ack_blockers,
        "checks": checks,
        "selected_tests": {
            "selected_tests_classification": selected_tests_classification,
            "selected_tests_passed_count": int(selected.get("selected_tests_passed_count") or 0),
            "selected_tests_failed_count": int(selected.get("selected_tests_failed_count") or 0),
        },
        "open_order_summary": {**order_summary, "open_d3_exit": open_d3_exit},
        "function_preservation_audit": {
            "overall_status": function_audit_status,
            "warnings": list((audit or {}).get("warnings") or []),
        },
        "preflight_evidence": {
            "path": str(selected_preflight_path) if selected_preflight_path else "",
            "attempted": preflight_attempted,
            "passed": preflight_passed,
            "blocked_ticker_count": blocked_ticker_count,
            "ticker_count": len(preflight_tickers),
            "tickers": preflight_tickers,
        },
        "wrapper_effective_scope": {
            "all_18_tickers": list(DEFAULT_TICKERS),
            "allowed_tickers": allowed_tickers,
            "phase_c_allowed_tickers": phase_c_allowed_tickers,
            "all_tickers_included": _all_tickers_present(allowed_tickers)
            and _all_tickers_present(phase_c_allowed_tickers),
            "caps": caps,
            "caps_tiny_conservative": caps_tiny,
            "environment": env,
        },
        "state_hashes": state_hashes,
        "operator_only_commands_do_not_run_by_codex": commands,
        "governance_flags": {
            "operator_all_ticker_tiny_env_ready": bool(checks["wrapper_allowed_tickers_all_18"] and checks["wrapper_phase_c_allowed_tickers_all_18"] and checks["caps_tiny_conservative"]),
            "all_ticker_preflight_passed_under_wrapper": preflight_passed,
            "all_ticker_operator_live_start_gate_ready": all_ticker_operator_live_start_gate_ready,
            "ready_for_operator_ack": ready_for_operator_ack,
            "live_start_authorized": live_start_authorized,
            "operator_manual_start_required": True,
            "codex_must_not_start_live_test": True,
            "all_ticker_ack_missing": not ack_present,
            "live_exits_enabled": live_exits_enabled,
            "autonomous_exits_enabled": autonomous_exits_enabled,
            "d3_actual_exit_submit_enabled": d3_actual_exit_submit_enabled,
            "replication_enabled": replication_enabled,
            "parameter_change_allowed": parameter_change_allowed,
            "learning_to_execution_ready": learning_to_execution_ready,
            "live_learning_allowed": live_learning_allowed,
            "selected_tests_classification": selected_tests_classification,
            "open_orders": open_orders,
            "open_d3_exit": open_d3_exit,
            "function_preservation_audit_status": function_audit_status,
        },
    }
    return _json_safe(report)


def render_all_ticker_operator_live_start_gate_markdown(report: Dict[str, Any]) -> str:
    flags = report.get("governance_flags") or {}
    preflight = report.get("preflight_evidence") or {}
    wrapper = report.get("wrapper_effective_scope") or {}
    lines = [
        "# All-Ticker Operator Live-Start Gate",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- status: `{report.get('status')}`",
        f"- live_start_authorized: `{report.get('live_start_authorized')}`",
        f"- ready_for_operator_ack: `{report.get('ready_for_operator_ack')}`",
        f"- codex_must_not_start_live_test: `{report.get('codex_must_not_start_live_test')}`",
        f"- operator_manual_start_required: `{report.get('operator_manual_start_required')}`",
        "",
        "## Evidence",
        "",
        f"- selected_tests_classification: `{flags.get('selected_tests_classification')}`",
        f"- open_orders: `{flags.get('open_orders')}`",
        f"- open_d3_exit: `{flags.get('open_d3_exit')}`",
        f"- function_preservation_audit_status: `{flags.get('function_preservation_audit_status')}`",
        f"- preflight_path: `{preflight.get('path')}`",
        f"- all_ticker_live_readonly_preflight_passed: `{preflight.get('passed')}`",
        f"- blocked_ticker_count: `{preflight.get('blocked_ticker_count')}`",
        f"- wrapper_all_tickers_included: `{wrapper.get('all_tickers_included')}`",
        f"- caps_tiny_conservative: `{wrapper.get('caps_tiny_conservative')}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = report.get("blockers") or []
    if blockers:
        for blocker in blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Governance Flags", ""])
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## OPERATOR ONLY - CODEX MUST NOT RUN", ""])
    commands = report.get("operator_only_commands_do_not_run_by_codex") or {}
    for row in commands.values():
        lines.append(f"- {row.get('purpose')}")
        lines.append(f"  - `{row.get('command')}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "ALL_TICKER_ACTUAL_SUBMIT_ACK",
    "PHASE_ALL_TICKER_OPERATOR_LIVE_START_GATE",
    "build_all_ticker_operator_live_start_gate",
    "render_all_ticker_operator_live_start_gate_markdown",
]
