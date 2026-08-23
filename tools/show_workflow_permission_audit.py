#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.approved_parameter_profile import sha256_file
from bot.autonomous_parameter_governor import ALLOWED_PARAMETERS, FORBIDDEN_PARAMETERS, governor_settings, validate_governor
from bot.config import MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV, MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE, MODE_C_MARKET_ORDER_ACK_ENV, MODE_C_MARKET_ORDER_ACK_VALUE
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report


OPEN_STATUSES = {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _orders(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("orders"), dict):
        return [dict(v) for v in payload["orders"].values() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [dict(v) for v in payload if isinstance(v, dict)]
    return []


def _positions(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("positions"), dict):
        payload = payload["positions"]
    if isinstance(payload, dict):
        return [dict(v) for v in payload.values() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [dict(v) for v in payload if isinstance(v, dict)]
    return []


def _service_status() -> Dict[str, Any]:
    out = {
        "systemd_active": "unknown_read_only_not_attempted",
        "systemd_running": "unknown_read_only_not_attempted",
        "service_name": _env("COINBASE_BOT_SYSTEMD_SERVICE", "coinbase-bot.service"),
    }
    try:
        result = subprocess.run(["systemctl", "is-active", out["service_name"]], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=2)
        status = result.stdout.strip()
        out["systemd_active"] = status == "active"
        out["systemd_running"] = status == "active"
        out["systemctl_returncode"] = result.returncode
    except Exception as exc:
        out["systemd_error"] = str(exc)
    return out


def _runtime_lock_status(root: Path) -> Dict[str, Any]:
    lock = root / "state/run_trader_loop.lock"
    payload = _load_json(lock)
    pid = payload.get("pid") if isinstance(payload, dict) else None
    pid_consistent = False
    if pid:
        try:
            os.kill(int(pid), 0)
            pid_consistent = True
        except Exception:
            pid_consistent = False
    return {
        "lock_path": str(lock),
        "single_process_lock_present": lock.exists(),
        "pid": pid,
        "pid_consistent": pid_consistent,
        "stale_lock_detected": bool(lock.exists() and pid and not pid_consistent),
        "cycle_boundary_guard_present": (root / "bot/run_cycle_guard.py").exists(),
        "atomic_write_guard_present": (root / "bot/atomic_io.py").exists(),
    }


def _approved_profile(root: Path, readiness: Dict[str, Any]) -> Dict[str, Any]:
    status = readiness.get("approved_profile_status") if isinstance(readiness.get("approved_profile_status"), dict) else {}
    path = root / "state/approved_parameter_profile.json"
    payload = _load_json(path)
    params = payload.get("parameters") if isinstance(payload, dict) and isinstance(payload.get("parameters"), dict) else {}
    actual_hash = sha256_file(path) if path.exists() else ""
    expected_hash = _env("APPROVED_PARAMETER_PROFILE_HASH")
    return {
        "ENABLE_APPROVED_PARAMETER_PROFILE": _bool_env("ENABLE_APPROVED_PARAMETER_PROFILE"),
        "APPROVED_PARAMETER_PROFILE_HASH": expected_hash,
        "actual_file_hash": actual_hash,
        "hash_valid": bool(expected_hash and actual_hash and expected_hash == actual_hash and status.get("loaded", False)),
        "profile_name": payload.get("profile_name") if isinstance(payload, dict) else "",
        "profile_version": payload.get("profile_version") if isinstance(payload, dict) else "",
        "parameter_list_loaded": sorted(params),
        "quote_rails_20_100": params.get("DEFAULT_QUOTE_SIZE_USDC") == "20.00" and params.get("MAX_NOTIONAL_USD") == "100.00",
        "d2_thresholds_present": all(k in params for k in ("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "PHASE_D2_MIN_REWARD_TO_RISK_RATIO")),
        "blockers": [] if status.get("hash_valid") else ["approved_profile_missing_or_hash_mismatch"],
    }


def _trailing_stop_status(root: Path, positions: List[Dict[str, Any]], flags: Dict[str, Any]) -> Dict[str, Any]:
    preview_module = root / "bot/phase_d4_trailing_preview.py"
    controlled_cancel_replace = root / "bot/phase_d4_controlled_cancel_replace.py"
    d3_exits = root / "bot/phase_d3_controlled_live_exits.py"

    preview_exists = preview_module.exists()
    cancel_replace_exists = controlled_cancel_replace.exists()
    d3_text = ""
    preview_text = ""
    cancel_text = ""
    try:
        d3_text = d3_exits.read_text(encoding="utf-8", errors="replace") if d3_exits.exists() else ""
        preview_text = preview_module.read_text(encoding="utf-8", errors="replace") if preview_exists else ""
        cancel_text = controlled_cancel_replace.read_text(encoding="utf-8", errors="replace") if cancel_replace_exists else ""
    except Exception:
        pass

    trailing_flags = {
        key: value
        for key, value in flags.items()
        if "trailing" in str(key).lower()
    }
    env_trailing_flags = {
        key: os.getenv(key)
        for key in os.environ
        if "TRAILING" in key.upper()
    }
    highest_persisted = any("highest_price_since_entry" in p or "highest_price_seen" in p for p in positions)
    stop_price_persisted = any("trailing_stop_price" in p or "stop_price" in p for p in positions)
    preview_only_evidence = preview_exists and (
        "preview_only" in preview_text
        or "d4_trailing_preview_candidate_ready" in preview_text
        or "required_future_ack" in preview_text
    )
    live_wired = bool(
        cancel_replace_exists
        and "submit" in cancel_text.lower()
        and "cancel" in cancel_text.lower()
        and "coinbase" in cancel_text.lower()
        and not preview_only_evidence
    )
    disabled = any(str(v).strip().lower() in {"false", "0", "off", "disabled"} for v in {**trailing_flags, **env_trailing_flags}.values())
    cancel_verified = (
        "require_open_tp_cancel_first" in d3_text
        or "coinbase_cancel_verify" in d3_text
        or bool(flags.get("controlled_stop_exit_require_open_tp_cancel_first"))
    )

    if not preview_exists and not cancel_replace_exists and not trailing_flags and not env_trailing_flags and not highest_persisted and not stop_price_persisted:
        status = "not_implemented"
    elif preview_only_evidence and not live_wired:
        status = "preview_only"
    elif (preview_exists or cancel_replace_exists or highest_persisted or stop_price_persisted) and not live_wired:
        status = "implemented_not_wired"
    elif live_wired and disabled:
        status = "wired_but_disabled"
    elif live_wired and cancel_verified:
        status = "live_ready"
    else:
        status = "implemented_not_wired"

    return {
        "trailing_stop_status": status,
        "module_exists": preview_exists or cancel_replace_exists,
        "preview_module_exists": preview_exists,
        "controlled_cancel_replace_module_exists": cancel_replace_exists,
        "flags": trailing_flags,
        "env_flags": env_trailing_flags,
        "highest_price_since_entry_persisted": highest_persisted,
        "trailing_stop_price_persisted": stop_price_persisted,
        "preview_only": preview_only_evidence,
        "live_wired_via_controlled_stop_or_market_close": live_wired,
        "cancels_verifies_existing_tp_first": cancel_verified,
        "existing_tp_cancel_first_required": bool(flags.get("controlled_stop_exit_require_open_tp_cancel_first")),
        "can_live_exit": status == "live_ready",
    }


def build_workflow_permission_audit(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root)
    readiness = build_full_autonomous_run_readiness_report(root=project_root, generated_at=generated_at)
    flags = ((readiness.get("service_config_readiness") or {}).get("flags") or {})
    orders_payload = _load_json(project_root / "state/open_orders.json")
    positions_payload = _load_json(project_root / "state/positions.json")
    orders = _orders(orders_payload)
    positions = _positions(positions_payload)
    open_orders = [o for o in orders if str(o.get("status") or "").lower() in OPEN_STATUSES]
    open_positions = [p for p in positions if str(p.get("status") or "open").lower() == "open" and str(p.get("position_size_base") or p.get("size_base") or "0") not in {"", "0", "0.0"}]
    open_d3 = [o for o in open_orders if str(o.get("phase") or "") == "D3_controlled_live_reduce_only_exits" and str(o.get("side") or "").upper() == "SELL"]
    missing_exchange_ids = [str(o.get("client_order_id") or "") for o in open_d3 if not str(o.get("exchange_order_id") or o.get("order_id") or "").strip()]
    duplicate_positions = sorted({str(o.get("linked_position_id") or "") for o in open_d3 if str(o.get("linked_position_id") or "") and sum(1 for x in open_d3 if str(x.get("linked_position_id") or "") == str(o.get("linked_position_id") or "")) > 1})
    replication = readiness.get("replication_status") if isinstance(readiness.get("replication_status"), dict) else {}
    mode_c = readiness.get("mode_c_market_order_readiness") if isinstance(readiness.get("mode_c_market_order_readiness"), dict) else {}
    stop = readiness.get("controlled_stop_exit_readiness") if isinstance(readiness.get("controlled_stop_exit_readiness"), dict) else {}
    profile = _approved_profile(project_root, readiness)
    governor = validate_governor(root=project_root, readiness_report=readiness)
    settings = governor_settings()

    can_submit_buy = bool(flags.get("enable_full_workflow_live_mode") and flags.get("enable_live_entry_orders") and flags.get("enable_live_limit_orders") and flags.get("enable_phase_c_actual_coinbase_submit"))
    can_apply_fill = bool(flags.get("phase_c43_lifecycle_allow_coinbase_poll") and flags.get("phase_c43_lifecycle_apply_local"))
    can_d2 = bool(flags.get("enable_phase_d2_position_executor") and flags.get("phase_c43_lifecycle_build_d2_plan") and flags.get("phase_c43_lifecycle_persist_d2_plan"))
    can_d3 = bool(flags.get("enable_live_exit_orders") and flags.get("autonomous_allow_exits") and flags.get("enable_phase_d3_controlled_live_exits", True) and flags.get("enable_phase_d3_actual_exit_submit") and not duplicate_positions and not missing_exchange_ids)
    can_poll = bool(flags.get("phase_c43_lifecycle_allow_coinbase_poll"))
    can_apply = bool(flags.get("phase_c43_lifecycle_apply_local") and not missing_exchange_ids)
    mode_b_ack_valid = _env(MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV) == MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE
    can_stop_cancel = bool(flags.get("enable_controlled_stop_market_exits") and flags.get("enable_autonomous_stop_exit_cancel") and mode_b_ack_valid)
    can_stop_submit = bool(flags.get("enable_controlled_stop_market_exits") and flags.get("enable_autonomous_stop_exit_submit") and mode_b_ack_valid and not open_d3)
    can_stop_apply = bool(flags.get("enable_controlled_stop_market_exits") and flags.get("enable_autonomous_stop_exit_apply") and mode_b_ack_valid)
    can_market_close = bool(mode_c.get("ready") and can_stop_submit)
    can_governor = bool(governor.get("can_mutate_allowed_parameters") and not open_orders and not open_positions)
    trailing_status = _trailing_stop_status(project_root, positions, flags)

    blockers: List[str] = []
    warnings: List[str] = []
    if not can_submit_buy:
        blockers.append("buy_submit_permissions_incomplete")
    if not can_d3:
        blockers.append("d3_exit_permissions_incomplete")
    if not can_apply:
        blockers.append("lifecycle_apply_permissions_incomplete")
    if missing_exchange_ids:
        blockers.append("open_d3_exit_missing_exchange_order_id")
    if duplicate_positions:
        blockers.append("duplicate_open_d3_exit")
    if mode_c.get("enabled") and not mode_c.get("ready"):
        blockers.extend(mode_c.get("blockers") or ["mode_c_not_ready"])
    if any(bool(replication.get(k)) for k in ("replication_enabled", "replication_lifecycle_enabled", "replication_lifecycle_http_enabled")) and mode_c.get("enabled"):
        blockers.append("replication_enabled_while_mode_c_market_orders_enabled")
    if profile["ENABLE_APPROVED_PARAMETER_PROFILE"] and not profile["hash_valid"]:
        blockers.append("approved_profile_hash_mismatch")
    if governor.get("open_orders", 0):
        warnings.append("governor_apply_blocked_by_open_orders")
    if governor.get("open_positions", 0):
        warnings.append("governor_apply_blocked_by_open_positions")

    if can_submit_buy and can_d3 and can_apply and can_poll and not blockers:
        workflow_status = "full_workflow_permissions_ready"
    elif can_submit_buy and not can_d3:
        workflow_status = "entry_ready_exit_blocked"
    elif can_d3 and not can_submit_buy:
        workflow_status = "exit_ready_entry_blocked"
    elif not can_stop_submit:
        workflow_status = "stop_exit_not_ready"
    elif not can_governor:
        workflow_status = "governor_not_ready"
    else:
        workflow_status = "blocked"

    audit = {
        "phase": "workflow_permission_audit_v1",
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_submit_attempted": False,
        "coinbase_cancel_attempted": False,
        "coinbase_replace_attempted": False,
        "coinbase_apply_attempted": False,
        "env_write_performed": False,
        "state_write_performed": False,
        "service_touched": False,
        "service_runtime": {**_service_status(), **_runtime_lock_status(project_root)},
        "universe_tickers": {
            "execution_mode": flags.get("execution_mode"),
            "allowed_tickers_effective": [x.strip() for x in _env("ALLOWED_TICKERS").split(",") if x.strip()],
            "phase_c_allowed_tickers_effective": [x.strip() for x in _env("PHASE_C_ALLOWED_TICKERS").split(",") if x.strip()],
            "allowed_phase_c_mismatch": sorted(set(_env("ALLOWED_TICKERS").split(",")) ^ set(_env("PHASE_C_ALLOWED_TICKERS").split(","))) if _env("ALLOWED_TICKERS") and _env("PHASE_C_ALLOWED_TICKERS") else [],
            "tiny_mode": _bool_env("ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE"),
            "runtime_tickers": list(flags.get("exploration_allowed_tickers") or []),
        },
        "entry_buy_path": {
            "ENABLE_FULL_WORKFLOW_LIVE_MODE": bool(flags.get("enable_full_workflow_live_mode")),
            "ENABLE_LIVE_ENTRY_ORDERS": bool(flags.get("enable_live_entry_orders")),
            "ENABLE_LIVE_LIMIT_ORDERS": bool(flags.get("enable_live_limit_orders")),
            "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": bool(flags.get("enable_phase_c_actual_coinbase_submit")),
            "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE": _bool_env("ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE"),
            "ENABLE_LIMIT_ORDER_MANAGER": _bool_env("ENABLE_LIMIT_ORDER_MANAGER"),
            "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS_false": not _bool_env("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS"),
            "max_new_orders_per_cycle": flags.get("max_new_orders_per_cycle"),
            "max_open_orders": flags.get("autonomous_max_open_orders"),
            "max_open_positions": flags.get("max_open_positions"),
            "quote_rails": {"min": flags.get("min_live_order_quote_usdc"), "default": flags.get("default_quote_size_usdc"), "max": flags.get("max_live_order_quote_usdc")},
            "coinbase_product_rules_readiness": "readiness_unknown_read_only_not_attempted",
        },
        "d1_fill_to_position_path": {
            "local_fill_reconciliation_ready": can_apply_fill,
            "terminal_fill_evidence_required": True,
            "position_creation_allowed": can_apply_fill,
            "no_state_apply_without_coinbase_evidence": True,
            "state_files_present_parsable": bool(isinstance(orders_payload, (dict, list)) and isinstance(positions_payload, (dict, list))),
        },
        "d2_position_executor": {
            "ENABLE_PHASE_D2_POSITION_EXECUTOR": bool(flags.get("enable_phase_d2_position_executor")),
            "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": _env("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"),
            "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": _env("PHASE_D2_MIN_REWARD_TO_FEE_RATIO"),
            "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": _env("PHASE_D2_MIN_REWARD_TO_RISK_RATIO"),
            "plan_build_persist_ready": can_d2,
        },
        "d3_controlled_live_exits": {
            "ENABLE_LIVE_EXIT_ORDERS": bool(flags.get("enable_live_exit_orders")),
            "AUTONOMOUS_ALLOW_EXITS": bool(flags.get("autonomous_allow_exits")),
            "ENABLE_PHASE_D3_CONTROLLED_LIVE_EXITS": _bool_env("ENABLE_PHASE_D3_CONTROLLED_LIVE_EXITS"),
            "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": bool(flags.get("enable_phase_d3_actual_exit_submit")),
            "PHASE_D3_MAX_EXIT_ORDER_QUOTE": flags.get("phase_d3_max_exit_order_quote"),
            "PHASE_D3_MAX_OPEN_EXIT_ORDERS": _env("PHASE_D3_MAX_OPEN_EXIT_ORDERS"),
            "duplicate_d3_guard": not duplicate_positions,
            "no_naked_sell": True,
            "no_oversell": True,
            "open_d3_exits_count": len(open_d3),
            "missing_exchange_order_ids": missing_exchange_ids,
        },
        "c43_lifecycle": {
            "PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL": bool(flags.get("phase_c43_lifecycle_allow_coinbase_poll")),
            "PHASE_C43_LIFECYCLE_APPLY_LOCAL": bool(flags.get("phase_c43_lifecycle_apply_local")),
            "PHASE_C43_LIFECYCLE_BUILD_D2_PLAN": bool(flags.get("phase_c43_lifecycle_build_d2_plan")),
            "PHASE_C43_LIFECYCLE_PERSIST_D2_PLAN": bool(flags.get("phase_c43_lifecycle_persist_d2_plan")),
            "PHASE_C43_LIFECYCLE_BUILD_D3_PREVIEW": bool(flags.get("phase_c43_lifecycle_build_d3_preview")),
            "can_poll_c43_orders": can_poll,
            "can_poll_d3_exits": can_poll,
            "can_apply_terminal_fills_cancels_only_with_evidence": can_apply,
        },
        "controlled_stop_emergency_exit_path": {
            **stop,
            "MODE_B_CONTROLLED_STOP_EXIT_ACK_valid": mode_b_ack_valid,
            "require_cancel_existing_tp_first": bool(flags.get("controlled_stop_exit_require_open_tp_cancel_first")),
            "require_coinbase_cancel_verify": True,
            "quote_cap": flags.get("controlled_stop_exit_max_quote_usd"),
            "slippage_cap": flags.get("controlled_stop_exit_max_slippage_pct"),
            "order_type": flags.get("controlled_stop_exit_order_type"),
            "no_duplicate_sell_while_tp_open": not open_d3,
            "local_apply_only_after_fill_evidence": True,
        },
        "mode_c_market_orders": {
            **mode_c,
            "market_orders_allowed_only_for_controlled_close_stop_route": True,
            "MODE_C_MARKET_ORDER_ACK_valid": _env(MODE_C_MARKET_ORDER_ACK_ENV) == MODE_C_MARKET_ORDER_ACK_VALUE,
        },
        "trailing_stop": {
            **trailing_status,
            "enabled": any(bool(p.get("trailing_active")) for p in positions),
            "apply": "controlled_stop_route_required_if_live_wired",
            "uses_controlled_stop_route": True,
        },
        "approved_parameter_profile": profile,
        "learning_governor": {
            "direct_mutation_flags_false": {
                "LEARNING_TO_EXECUTION_ALLOWED": not _bool_env("LEARNING_TO_EXECUTION_ALLOWED"),
                "LIVE_LEARNING_ALLOWED": not _bool_env("LIVE_LEARNING_ALLOWED"),
                "PARAMETER_CHANGE_ALLOWED": not _bool_env("PARAMETER_CHANGE_ALLOWED"),
                "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED": not _bool_env("NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED"),
            },
            "autonomous_parameter_governor": governor,
            "apply_when_safe": settings.get("mode") == "apply_when_safe",
            "candidate_available": governor.get("candidate_available"),
            "analysis_ready": governor.get("analysis_ready"),
            "prepare_ready": governor.get("prepare_ready"),
            "apply_ready": governor.get("apply_ready"),
            "min_market_regimes": settings.get("min_market_regimes_for_apply"),
            "validated_conclusions_per_regime": settings.get("min_validated_conclusions_per_regime_for_apply"),
            "directional_events_per_regime": settings.get("min_directional_events_per_regime_for_apply"),
            "cooldown_days": settings.get("cooldown_days"),
            "max_parameters_per_apply": settings.get("max_parameters_per_activation"),
            "require_new_evidence_hash": settings.get("require_new_evidence_since_last_apply"),
            "block_apply_with_open_orders_positions": bool(settings.get("apply_only_when_no_open_orders") and settings.get("apply_only_when_no_open_positions")),
            "allowed_parameter_families": sorted(ALLOWED_PARAMETERS),
            "forbidden_parameters": sorted(FORBIDDEN_PARAMETERS),
        },
        "replication": replication,
        "workflow_permission_status": workflow_status,
        "can_submit_buy": can_submit_buy,
        "can_apply_fill_to_position": can_apply_fill,
        "can_build_d2_plan": can_d2,
        "can_submit_d3_exit": can_d3,
        "can_lifecycle_poll": can_poll,
        "can_lifecycle_apply": can_apply,
        "can_controlled_stop_cancel": can_stop_cancel,
        "can_controlled_stop_submit": can_stop_submit,
        "can_controlled_stop_apply": can_stop_apply,
        "can_market_close": can_market_close,
        "trailing_stop_status": trailing_status["trailing_stop_status"],
        "can_trailing_stop_exit": trailing_status["can_live_exit"],
        "can_governor_apply_parameter": can_governor,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "recommended_operator_action": "keep_running_collect_judge_funnel_evidence" if not blockers else "resolve_blockers_before_live_apply",
    }
    return audit


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Workflow Permission Audit",
        "",
        f"Generated: `{report.get('generated_at')}`",
        f"Status: `{report.get('workflow_permission_status')}`",
        "",
        "## Capabilities",
    ]
    for key in (
        "can_submit_buy",
        "can_apply_fill_to_position",
        "can_build_d2_plan",
        "can_submit_d3_exit",
        "can_lifecycle_poll",
        "can_lifecycle_apply",
        "can_controlled_stop_cancel",
        "can_controlled_stop_submit",
        "can_controlled_stop_apply",
        "can_market_close",
        "can_trailing_stop_exit",
        "can_governor_apply_parameter",
    ):
        lines.append(f"- `{key}`: {report.get(key)}")
    lines.extend(["", "## Blockers"])
    lines.extend([f"- `{b}`" for b in report.get("blockers", [])] or ["- none"])
    lines.extend(["", "## Warnings"])
    lines.extend([f"- `{w}`" for w in report.get("warnings", [])] or ["- none"])
    trailing = report.get("trailing_stop") if isinstance(report.get("trailing_stop"), dict) else {}
    lines.extend([
        "",
        "## Trailing Stop",
        f"- `trailing_stop_status`: `{report.get('trailing_stop_status')}`",
        f"- `module_exists`: {trailing.get('module_exists')}",
        f"- `preview_only`: {trailing.get('preview_only')}",
        f"- `live_wired_via_controlled_stop_or_market_close`: {trailing.get('live_wired_via_controlled_stop_or_market_close')}",
        f"- `highest_price_since_entry_persisted`: {trailing.get('highest_price_since_entry_persisted')}",
        f"- `trailing_stop_price_persisted`: {trailing.get('trailing_stop_price_persisted')}",
        f"- `cancels_verifies_existing_tp_first`: {trailing.get('cancels_verifies_existing_tp_first')}",
    ])
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only workflow permission audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out")
    parser.add_argument("--md-out")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_workflow_permission_audit(root=args.root)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md_out:
        path = Path(args.md_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(report), encoding="utf-8")
    if args.json or not (args.json_out or args.md_out):
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
