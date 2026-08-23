#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.approved_parameter_profile import load_approved_parameter_profile
from bot.live_order_size_policy import bounded_exploration_report, live_order_size_policy_report
from bot.live_learning_orchestrator import build_live_learning_context
from bot.neural_shadow_policy import neural_learning_status_from_config
from bot.research_parameter_priors import research_prior_status
from bot.config import BotConfig
from bot.config import (
    MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV,
    MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE,
    MODE_C_MARKET_ORDER_ACK_ENV,
    MODE_C_MARKET_ORDER_ACK_VALUE,
)
from tools.build_live_learning_sidecar import build_live_learning_sidecar_report
from tools.propose_balanced_start_parameter_profile import build_balanced_start_parameter_profile_candidate


D3_PHASE = "D3_controlled_live_reduce_only_exits"
OPEN_EQUIVALENT_STATUSES = {
    "planned",
    "pending",
    "submitted",
    "open",
    "partially_filled",
    "cancel_pending",
    "replace_pending",
}
FORBIDDEN_LEARNING_FLAGS = [
    "LEARNING_TO_EXECUTION_READY",
    "LEARNING_TO_EXECUTION_ALLOWED",
    "LIVE_LEARNING_ALLOWED",
    "PARAMETER_CHANGE_ALLOWED",
    "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _iter_jsonl_tail(path: Path, limit: int = 200) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _last_publish_status(path: Path) -> str:
    for row in reversed(_iter_jsonl_tail(path)):
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        status = str(row.get("status") or "").strip()
        reason = str(result.get("reason") or "").strip()
        if status or reason:
            return reason or status
    return "unknown"


def _replication_status(root: Path) -> Dict[str, Any]:
    return {
        "replication_enabled": os.getenv("REPLICATION_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        "replica_url_present": bool(os.getenv("REPLICA_URL", "").strip()),
        "replica_shared_secret_present": bool(os.getenv("REPLICA_SHARED_HMAC_SECRET", "").strip()),
        "replication_lifecycle_enabled": os.getenv("REPLICATION_LIFECYCLE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        "replication_lifecycle_http_enabled": os.getenv("REPLICATION_LIFECYCLE_HTTP_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        "last_replication_publish_status": _last_publish_status(root / "logs/replication_outbox.jsonl"),
        "last_lifecycle_publish_status": _last_publish_status(root / "logs/replication_lifecycle_outbox.jsonl"),
        "follower_health_checked": False,
        "follower_health_ok": None,
        "follower_mode": "unknown",
    }


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _mode_b_ack_status_from_env() -> Dict[str, Any]:
    ack = os.getenv(MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV, "").strip()
    cancel_enabled = _bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL")
    submit_enabled = _bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT")
    apply_enabled = _bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY")
    route_enabled = _bool_env("ENABLE_CONTROLLED_STOP_MARKET_EXITS")
    valid = ack == MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE
    any_action_enabled = cancel_enabled or submit_enabled or apply_enabled
    return {
        "route_enabled": route_enabled,
        "autonomous_cancel_enabled": cancel_enabled,
        "autonomous_submit_enabled": submit_enabled,
        "autonomous_apply_enabled": apply_enabled,
        "ack_env": MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV,
        "ack_present": bool(ack),
        "ack_valid": valid,
        "mode_a_compatible": not any_action_enabled,
        "mode_b_apply_allowed": bool(route_enabled and cancel_enabled and submit_enabled and apply_enabled and valid),
        "blocker": "mode_b_stop_exit_apply_ack_missing" if any_action_enabled and not valid else "",
    }


def _direct_parameter_mutation_disabled() -> bool:
    return not any(_bool_env(name) for name in ("LEARNING_TO_EXECUTION_ALLOWED", "LIVE_LEARNING_ALLOWED", "PARAMETER_CHANGE_ALLOWED"))


def _mode_c_market_order_readiness_from_env(replication_status: Dict[str, Any], flags: Dict[str, Any]) -> Dict[str, Any]:
    market_flags = {
        "MARKET_ORDER_ENABLED": _bool_env("MARKET_ORDER_ENABLED"),
        "ENABLE_MARKET_ORDERS": _bool_env("ENABLE_MARKET_ORDERS"),
        "ALLOW_MARKET_ORDERS": _bool_env("ALLOW_MARKET_ORDERS"),
    }
    any_enabled = any(market_flags.values())
    all_enabled = all(market_flags.values())
    ack = os.getenv(MODE_C_MARKET_ORDER_ACK_ENV, "").strip()
    ack_valid = ack == MODE_C_MARKET_ORDER_ACK_VALUE
    replication_enabled = bool(
        replication_status.get("replication_enabled")
        or replication_status.get("replication_lifecycle_enabled")
        or replication_status.get("replication_lifecycle_http_enabled")
    )
    blockers: List[str] = []
    if any_enabled and not all_enabled:
        blockers.append("mode_c_market_order_ack_missing")
    if any_enabled and not ack_valid:
        blockers.append("market_orders_enabled_without_ack")
        blockers.append("mode_c_market_order_ack_missing")
    if any_enabled and replication_enabled:
        blockers.append("market_orders_enabled_with_replication")
    min_quote = _to_decimal(flags.get("min_live_order_quote_usdc"), "0")
    max_quote = _to_decimal(flags.get("max_live_order_quote_usdc"), "0")
    default_quote = _to_decimal(flags.get("default_quote_size_usdc"), "0")
    max_notional = _to_decimal(flags.get("max_notional_usd"), "0")
    if any_enabled and min_quote != Decimal("50.00"):
        blockers.append("market_order_quote_below_min")
    if any_enabled and max_quote != Decimal("100.00"):
        blockers.append("market_order_quote_above_max")
    if any_enabled and (default_quote < Decimal("50.00") or max_notional < Decimal("50.00")):
        blockers.append("market_order_quote_below_min")
    if any_enabled and (default_quote > Decimal("100.00") or max_notional > Decimal("100.00")):
        blockers.append("market_order_quote_above_max")
    if any_enabled and int(flags.get("max_open_positions") or 0) != 3:
        blockers.append("market_order_max_open_positions_not_3")
    if any_enabled and int(flags.get("autonomous_max_open_orders") or 0) != 3:
        blockers.append("market_order_max_open_orders_not_3")
    if any_enabled and int(flags.get("max_new_orders_per_cycle") or 0) != 1:
        blockers.append("market_order_max_new_orders_per_cycle_not_1")
    if any_enabled and int(flags.get("phase_c_max_new_orders_per_cycle") or 0) != 1:
        blockers.append("market_order_max_new_orders_per_cycle_not_1")
    return {
        "status": "disabled" if not any_enabled else ("ready" if not blockers else "blocked"),
        "ready": bool(any_enabled and not blockers),
        "enabled": bool(any_enabled),
        "flags": market_flags,
        "ack_env": MODE_C_MARKET_ORDER_ACK_ENV,
        "required_ack": MODE_C_MARKET_ORDER_ACK_VALUE,
        "ack_present": bool(ack),
        "ack_valid": ack_valid,
        "replication_must_remain_disabled": True,
        "replication_disabled": not replication_enabled,
        "blockers": sorted(set(blockers)),
        "rails": {
            "min_quote_usdc": "50.00",
            "max_quote_usdc": "100.00",
            "max_new_orders_per_cycle": 1,
            "max_open_orders": 3,
            "max_open_positions": 3,
        },
        "market_buy_rules": [
            "approve_trade",
            "side BUY",
            "concrete trade_plan",
            "deterministic risk green",
            "allowed ticker",
            "quote 50-100",
            "no duplicate open order",
            "no max-position/max-order breach",
        ],
        "market_sell_rules": [
            "existing bot-managed base only",
            "never naked sell",
            "never oversell",
            "never duplicate D3/exit",
            "terminal Coinbase fill evidence before local apply",
        ],
    }


def _orders_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("orders"), dict):
        return [dict(v) for v in payload["orders"].values() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [dict(v) for v in payload if isinstance(v, dict)]
    return []


def _is_open(order: Dict[str, Any]) -> bool:
    return str(order.get("status") or "").strip().lower() in OPEN_EQUIVALENT_STATUSES


def _is_d3_exit(order: Dict[str, Any]) -> bool:
    return (
        str(order.get("phase") or "").strip() == D3_PHASE
        and str(order.get("side") or "").strip().upper() == "SELL"
    )


def _open_orders_summary(root: Path) -> Dict[str, Any]:
    path = root / "state/open_orders.json"
    orders = _orders_from_payload(_load_json(path))
    open_orders = [o for o in orders if _is_open(o)]
    open_d3 = [o for o in open_orders if _is_d3_exit(o)]
    duplicate_positions: Dict[str, int] = {}
    missing_exchange_ids: List[str] = []
    for order in open_d3:
        linked = str(order.get("linked_position_id") or "")
        duplicate_positions[linked] = duplicate_positions.get(linked, 0) + 1
        if not str(order.get("exchange_order_id") or order.get("order_id") or "").strip():
            missing_exchange_ids.append(str(order.get("client_order_id") or ""))
    return {
        "path": str(path),
        "total_orders": len(orders),
        "open_orders": len(open_orders),
        "open_d3_exit": len(open_d3),
        "open_d3_exit_samples": [
            {
                "client_order_id": str(o.get("client_order_id") or ""),
                "exchange_order_id": str(o.get("exchange_order_id") or o.get("order_id") or ""),
                "linked_position_id": str(o.get("linked_position_id") or ""),
                "status": str(o.get("status") or ""),
                "remaining_size": str(o.get("remaining_size") or o.get("size_base") or ""),
                "limit_price": str(o.get("limit_price") or ""),
            }
            for o in open_d3[:10]
        ],
        "duplicate_open_d3_exit_positions": sorted(k for k, v in duplicate_positions.items() if v > 1),
        "missing_exchange_order_id_client_order_ids": missing_exchange_ids,
    }


def _positions_summary(root: Path) -> Dict[str, Any]:
    path = root / "state/positions.json"
    payload = _load_json(path)
    positions = payload if isinstance(payload, dict) else {}
    open_positions = {
        str(ticker): pos
        for ticker, pos in positions.items()
        if isinstance(pos, dict) and str(pos.get("status") or "").strip().lower() == "open"
    }
    btc = open_positions.get("BTC-USDC") if isinstance(open_positions.get("BTC-USDC"), dict) else {}
    return {
        "path": str(path),
        "open_positions": len(open_positions),
        "btc_usdc_status": str(btc.get("status") or ""),
        "btc_usdc_position_size_base": str(btc.get("position_size_base") or ""),
        "btc_usdc_bot_managed_base": str(btc.get("bot_managed_base") or ""),
        "btc_usdc_entry_price": str(btc.get("entry_price") or ""),
        "btc_usdc_stop_price": str(btc.get("stop_price") or btc.get("invalidation_price") or ""),
        "btc_usdc_last_heartbeat_reason": str(btc.get("last_heartbeat_reason") or ""),
    }


def _approved_profile_readiness(root: Path) -> Dict[str, Any]:
    try:
        result = load_approved_parameter_profile(path=root / "state/approved_parameter_profile.json")
        return {
            "status": result.status,
            "reason": result.reason,
            "path": result.path,
            "loaded_keys": sorted(result.values),
            "hash_validated": bool(result.status == "loaded"),
            "hash": result.actual_hash or result.expected_hash,
            "parameters": result.values,
            "runtime_mutation_allowed": False,
        }
    except Exception as exc:
        return {
            "status": "rejected",
            "reason": str(exc),
            "path": str(root / "state/approved_parameter_profile.json"),
            "loaded_keys": [],
            "hash_validated": False,
            "hash": "",
            "parameters": {},
            "runtime_mutation_allowed": False,
        }


def _config_readiness(root: Path) -> Dict[str, Any]:
    cfg = None
    try:
        cfg = BotConfig()
    except Exception as exc:
        return {
            "status": "invalid",
            "error": str(exc),
            "flags": {
            "enable_controlled_stop_market_exits": _bool_env("ENABLE_CONTROLLED_STOP_MARKET_EXITS"),
            "enable_autonomous_stop_exit_cancel": _bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL"),
            "enable_autonomous_stop_exit_submit": _bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT"),
            "enable_autonomous_stop_exit_apply": _bool_env("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY"),
                "market_order_enabled": _bool_env("MARKET_ORDER_ENABLED"),
                "enable_market_orders": _bool_env("ENABLE_MARKET_ORDERS"),
                "allow_market_orders": _bool_env("ALLOW_MARKET_ORDERS"),
            },
        }
    try:
        cfg.validate()
        cfg_error = ""
    except Exception as exc:
        cfg_error = str(exc)

    return {
        "status": "valid" if not cfg_error else "invalid",
        "error": cfg_error,
        "flags": {
            "execution_mode": cfg.execution_mode,
            "enable_full_workflow_live_mode": cfg.enable_full_workflow_live_mode,
            "enable_live_entry_orders": cfg.enable_live_entry_orders,
            "enable_live_limit_orders": cfg.enable_live_limit_orders,
            "enable_phase_c_actual_coinbase_submit": cfg.enable_phase_c_actual_coinbase_submit,
            "enable_live_exit_orders": cfg.enable_live_exit_orders,
            "autonomous_allow_exits": cfg.autonomous_allow_exits,
            "enable_phase_d3_actual_exit_submit": cfg.enable_phase_d3_actual_exit_submit,
            "enable_phase_d2_position_executor": cfg.enable_phase_d2_position_executor,
            "phase_c43_lifecycle_allow_coinbase_poll": cfg.phase_c43_lifecycle_allow_coinbase_poll,
            "phase_c43_lifecycle_apply_local": cfg.phase_c43_lifecycle_apply_local,
            "phase_c43_lifecycle_build_d2_plan": cfg.phase_c43_lifecycle_build_d2_plan,
            "phase_c43_lifecycle_persist_d2_plan": cfg.phase_c43_lifecycle_persist_d2_plan,
            "phase_c43_lifecycle_build_d3_preview": cfg.phase_c43_lifecycle_build_d3_preview,
            "enable_controlled_stop_market_exits": cfg.enable_controlled_stop_market_exits,
            "enable_autonomous_stop_exit_cancel": cfg.enable_autonomous_stop_exit_cancel,
            "enable_autonomous_stop_exit_submit": cfg.enable_autonomous_stop_exit_submit,
            "enable_autonomous_stop_exit_apply": cfg.enable_autonomous_stop_exit_apply,
            "mode_b_controlled_stop_exit_ack_valid": cfg.mode_b_controlled_stop_exit_ack == MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE,
            "market_order_enabled": _bool_env("MARKET_ORDER_ENABLED"),
            "enable_market_orders": _bool_env("ENABLE_MARKET_ORDERS"),
            "allow_market_orders": _bool_env("ALLOW_MARKET_ORDERS"),
            "mode_c_market_order_ack_valid": _bool_env("MARKET_ORDER_ENABLED") and os.getenv(MODE_C_MARKET_ORDER_ACK_ENV, "").strip() == MODE_C_MARKET_ORDER_ACK_VALUE,
            "controlled_stop_exit_max_quote_usd": str(cfg.controlled_stop_exit_max_quote_usd),
            "controlled_stop_exit_require_open_tp_cancel_first": cfg.controlled_stop_exit_require_open_tp_cancel_first,
            "controlled_stop_exit_order_type": cfg.controlled_stop_exit_order_type,
            "controlled_stop_exit_max_slippage_pct": str(cfg.controlled_stop_exit_max_slippage_pct),
            "min_live_order_quote_usdc": str(cfg.min_live_order_quote_usdc),
            "max_live_order_quote_usdc": str(cfg.max_live_order_quote_usdc),
            "default_quote_size_usdc": str(cfg.default_quote_size_usdc),
            "max_notional_usd": str(cfg.max_notional_usd),
            "max_open_positions": cfg.max_open_positions,
            "max_new_orders_per_cycle": cfg.max_new_orders_per_cycle,
            "autonomous_max_order_quote": str(cfg.autonomous_max_order_quote),
            "autonomous_max_open_orders": cfg.autonomous_max_open_orders,
            "autonomous_max_new_orders_per_cycle": cfg.autonomous_max_new_orders_per_cycle,
            "phase_c_max_order_quote": str(cfg.phase_c_max_order_quote),
            "phase_c_max_open_entry_orders": cfg.phase_c_max_open_entry_orders,
            "phase_c_max_new_orders_per_cycle": cfg.phase_c_max_new_orders_per_cycle,
            "phase_d3_max_exit_order_quote": str(cfg.phase_d3_max_exit_order_quote),
            "enable_bounded_exploration_mode": cfg.enable_bounded_exploration_mode,
            "exploration_min_order_quote_usdc": str(cfg.exploration_min_order_quote_usdc),
            "exploration_max_order_quote_usdc": str(cfg.exploration_max_order_quote_usdc),
            "exploration_allowed_tickers": list(cfg.exploration_allowed_tickers or []),
            "exploration_allow_market_orders": cfg.exploration_allow_market_orders,
            "exploration_require_hard_risk_green": cfg.exploration_require_hard_risk_green,
            "exploration_require_fresh_trigger": cfg.exploration_require_fresh_trigger,
            "exploration_require_no_chase": cfg.exploration_require_no_chase,
            "exploration_max_spread_pct": str(cfg.exploration_max_spread_pct),
            "exploration_require_orderbook_snapshot": cfg.exploration_require_orderbook_snapshot,
            "exit_target_max_distance_from_mid_pct": str(cfg.exit_target_max_distance_from_mid_pct),
            "exit_target_allow_far_tp_with_resistance_confirmation": cfg.exit_target_allow_far_tp_with_resistance_confirmation,
            "exit_target_require_fresh_context_when_stop_breached": cfg.exit_target_require_fresh_context_when_stop_breached,
            "exit_target_stale_if_stop_breached": cfg.exit_target_stale_if_stop_breached,
            "neural_shadow_policy_enabled": cfg.neural_shadow_policy_enabled,
            "neural_shadow_policy_training_enabled": cfg.neural_shadow_policy_training_enabled,
            "neural_shadow_policy_execution_allowed": cfg.neural_shadow_policy_execution_allowed,
            "neural_shadow_policy_agreement_required": cfg.neural_shadow_policy_agreement_required,
            "neural_shadow_policy_model_path": cfg.neural_shadow_policy_model_path,
            "neural_shadow_policy_report_path": cfg.neural_shadow_policy_report_path,
        },
    }


def _balanced_profile_status(root: Path, generated_at: Optional[str]) -> Dict[str, Any]:
    candidate_path = root / "reports/live_learning/balanced-start-profile-candidate.json"
    candidate = _load_json(candidate_path) if candidate_path.exists() else {}
    if not candidate:
        try:
            candidate = build_balanced_start_parameter_profile_candidate(root=root, generated_at=generated_at)
        except Exception as exc:
            return {"candidate_exists": False, "error": str(exc), "safe_to_activate_now": False}
    return {
        "candidate_exists": candidate_path.exists(),
        "candidate_path": str(candidate_path),
        "classification": candidate.get("classification"),
        "safe_to_activate_now": bool(candidate.get("safe_to_activate_now")),
        "recommended_operator_action": candidate.get("recommended_operator_action"),
        "hash_to_approve": candidate.get("hash_to_approve"),
    }


def _research_prior_parameter_status(root: Path) -> Dict[str, Any]:
    payload = _load_json(root / "reports/research/research-prior-parameter-profile-latest.json")
    if isinstance(payload, dict) and payload:
        status = research_prior_status(payload)
        status["path"] = "reports/research/research-prior-parameter-profile-latest.json"
        return status
    status = research_prior_status()
    status["path"] = "reports/research/research-prior-parameter-profile-latest.json"
    status["report_exists"] = False
    return status


def _backtesting_parameter_bridge_status(root: Path) -> Dict[str, Any]:
    path = root / "reports/backtests/approved-profile-candidate-from-backtest.json"
    payload = _load_json(path)
    if not isinstance(payload, dict) or not payload:
        return {
            "available": False,
            "path": "reports/backtests/approved-profile-candidate-from-backtest.json",
            "safe_to_live_activate_now": False,
            "requires_operator_review": True,
            "sample_size": 0,
        }
    return {
        "available": True,
        "path": "reports/backtests/approved-profile-candidate-from-backtest.json",
        "safe_to_live_activate_now": bool(payload.get("safe_to_live_activate_now")),
        "requires_operator_review": bool(payload.get("requires_operator_review")),
        "confidence": payload.get("confidence"),
        "overfit_risk": payload.get("overfit_risk"),
        "sample_size": int(payload.get("sample_size") or 0),
        "hash_to_approve": payload.get("hash_to_approve"),
    }


def _learning_status(root: Path, generated_at: Optional[str], approved_profile: Dict[str, Any]) -> Dict[str, Any]:
    try:
        context = build_live_learning_context(root=root, generated_at=generated_at, write_report=False)
        runtime = context.get("runtime_context") if isinstance(context.get("runtime_context"), dict) else {}
    except Exception as exc:
        return {
            "learning_context_available": False,
            "learning_context_classification": "WATCH",
            "backlearning_available": False,
            "backlearning_latest_report": "",
            "approved_profile_enabled": approved_profile.get("status") == "loaded",
            "approved_profile_hash_valid": bool(approved_profile.get("hash_validated")),
            "approved_profile_loaded": approved_profile.get("status") == "loaded",
            "approved_profile_parameters": approved_profile.get("parameters") or {},
            "learning_mode": "unsafe_disabled" if approved_profile.get("status") == "rejected" else "report_only",
            "error": str(exc),
        }
    sources = context.get("sources") if isinstance(context.get("sources"), dict) else {}
    backlearning = sources.get("cost_aware_backlearning") if isinstance(sources.get("cost_aware_backlearning"), dict) else {}
    approved_loaded = approved_profile.get("status") == "loaded"
    return {
        "learning_context_available": True,
        "learning_context_classification": runtime.get("classification") or context.get("classification") or "WATCH",
        "backlearning_available": bool(backlearning.get("available")),
        "backlearning_latest_report": backlearning.get("path") or "",
        "approved_profile_enabled": approved_loaded,
        "approved_profile_hash_valid": bool(approved_profile.get("hash_validated")),
        "approved_profile_loaded": approved_loaded,
        "approved_profile_parameters": approved_profile.get("parameters") or {},
        "learning_mode": "approved_profile_active" if approved_loaded else ("unsafe_disabled" if approved_profile.get("status") == "rejected" else "report_only"),
    }


def _neural_learning_status(root: Path) -> Dict[str, Any]:
    try:
        cfg = BotConfig()
        cfg.validate()
        return neural_learning_status_from_config(cfg, root=root)
    except Exception as exc:
        class _Fallback:
            neural_shadow_policy_enabled = True
            neural_shadow_policy_training_enabled = True
            neural_shadow_policy_execution_allowed = False
            neural_shadow_policy_agreement_required = False
            neural_shadow_policy_model_path = "state/neural_shadow_policy.json"
            neural_shadow_policy_report_path = "reports/live_learning/neural-shadow-policy-latest.json"

        status = neural_learning_status_from_config(_Fallback(), root=root)
        status["status"] = "config_invalid"
        status["error"] = str(exc)
        return status


def build_full_autonomous_run_readiness_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    project_root = Path(root)
    config = _config_readiness(project_root)
    orders = _open_orders_summary(project_root)
    positions = _positions_summary(project_root)
    approved_profile = _approved_profile_readiness(project_root)
    sidecar = build_live_learning_sidecar_report(root=project_root, generated_at=generated_at)
    balanced_profile = _balanced_profile_status(project_root, generated_at)
    research_prior_parameters = _research_prior_parameter_status(project_root)
    backtesting_parameter_bridge = _backtesting_parameter_bridge_status(project_root)
    learning_status = _learning_status(project_root, generated_at, approved_profile)
    neural_learning_status = _neural_learning_status(project_root)
    replication_status = _replication_status(project_root)
    mode_b_ack_status = _mode_b_ack_status_from_env()
    flags = config.get("flags") if isinstance(config.get("flags"), dict) else {}
    mode_c_market_readiness = _mode_c_market_order_readiness_from_env(replication_status, flags)
    try:
        cfg_for_policy = BotConfig()
        cfg_for_policy.validate()
        live_order_size_policy = live_order_size_policy_report(cfg_for_policy)
        bounded_exploration = bounded_exploration_report(cfg_for_policy)
    except Exception:
        cfg_for_policy = None
        live_order_size_policy = {
            "min_quote_usdc": str(flags.get("min_live_order_quote_usdc") or "0"),
            "max_quote_usdc": str(flags.get("max_live_order_quote_usdc") or "0"),
            "entry_under_min_blocked": True,
            "entry_above_max_blocked": True,
            "partial_exit_under_min_blocked": True,
            "full_close_exception_allowed": True,
            "market_orders_allowed": False,
        }
        bounded_exploration = {
            "enabled": bool(flags.get("enable_bounded_exploration_mode")),
            "ready": False,
            "blockers": ["config_invalid"],
        }

    blockers: List[str] = []
    if config.get("status") != "valid":
        blockers.append("config_invalid")
    if mode_b_ack_status["blocker"]:
        blockers.append(mode_b_ack_status["blocker"])
    if not flags.get("enable_full_workflow_live_mode"):
        blockers.append("full_workflow_live_mode_disabled")
    if not flags.get("enable_phase_c_actual_coinbase_submit"):
        blockers.append("entry_submit_flag_disabled")
    if not flags.get("enable_phase_d3_actual_exit_submit"):
        blockers.append("d3_actual_exit_submit_disabled")
    if not flags.get("phase_c43_lifecycle_allow_coinbase_poll"):
        blockers.append("d3_lifecycle_coinbase_poll_disabled")
    if orders["duplicate_open_d3_exit_positions"]:
        blockers.append("duplicate_open_d3_exit")
    if orders["missing_exchange_order_id_client_order_ids"]:
        blockers.append("open_d3_exit_missing_exchange_order_id")
    enabled_forbidden = [name for name in FORBIDDEN_LEARNING_FLAGS if os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}]
    if enabled_forbidden:
        blockers.append("direct_learning_to_execution_flags_enabled")
    if bool(neural_learning_status.get("execution_allowed")):
        blockers.append("neural_shadow_policy_execution_allowed")
    if approved_profile["status"] == "rejected":
        blockers.append("approved_parameter_profile_rejected")

    warnings: List[str] = []
    min_quote = _to_decimal(flags.get("min_live_order_quote_usdc"), "0")
    max_quote = _to_decimal(flags.get("max_live_order_quote_usdc"), "0")
    if min_quote and min_quote < Decimal("50.00"):
        blockers.append("min_live_order_quote_below_50")
    if max_quote > Decimal("100.00"):
        blockers.append("max_live_order_quote_above_100")
    blockers.extend(mode_c_market_readiness["blockers"])
    if bool(flags.get("enable_bounded_exploration_mode")):
        if bool(flags.get("exploration_allow_market_orders")):
            blockers.append("bounded_exploration_market_orders_enabled")
        if _to_decimal(flags.get("exploration_min_order_quote_usdc"), "0") < Decimal("20.00"):
            blockers.append("bounded_exploration_min_quote_below_20")
        if _to_decimal(flags.get("exploration_max_order_quote_usdc"), "0") > Decimal("35.00"):
            blockers.append("bounded_exploration_max_quote_above_35")
    if bool(neural_learning_status.get("one_class_dataset_warning")):
        warnings.append("neural_shadow_one_class_passivity_bias")
    if bool(backtesting_parameter_bridge.get("safe_to_live_activate_now")) and not bool(backtesting_parameter_bridge.get("requires_operator_review")):
        blockers.append("backtest_candidate_safe_without_operator_review")
    elif bool(backtesting_parameter_bridge.get("safe_to_live_activate_now")):
        warnings.append("backtest_candidate_claims_safe_to_live_activate_now")

    stop_apply_enabled = bool(flags.get("enable_autonomous_stop_exit_apply")) or bool(mode_b_ack_status["autonomous_apply_enabled"])
    stop_cancel_enabled = bool(flags.get("enable_autonomous_stop_exit_cancel")) or bool(mode_b_ack_status["autonomous_cancel_enabled"])
    stop_submit_enabled = bool(flags.get("enable_autonomous_stop_exit_submit")) or bool(mode_b_ack_status["autonomous_submit_enabled"])
    stop_route_enabled = bool(flags.get("enable_controlled_stop_market_exits")) or bool(mode_b_ack_status["route_enabled"])
    stop_breach_detected = "stop_breached_or_below_invalidation" in str(positions.get("btc_usdc_last_heartbeat_reason") or "")
    open_tp_above_market_detected = bool(stop_breach_detected and orders["open_d3_exit"])
    stale_tp_blocks_stop_exit = bool(stop_breach_detected and open_tp_above_market_detected)
    stop_readiness = {
        "status": "preview_only_ready" if not stop_apply_enabled else "apply_mode_requires_all_runtime_guards_green",
        "preview_only_is_acceptable_for_bounded_run": not stop_apply_enabled,
        "route_enabled": stop_route_enabled,
        "autonomous_cancel_enabled": stop_cancel_enabled,
        "autonomous_submit_enabled": stop_submit_enabled,
        "autonomous_apply_enabled": stop_apply_enabled,
        "mode_b_ack": mode_b_ack_status,
        "stop_breach_detected": stop_breach_detected,
        "open_tp_above_market_detected": open_tp_above_market_detected,
        "stale_tp_blocks_stop_exit": stale_tp_blocks_stop_exit,
        "controlled_stop_exit_next_step": "cancel_existing_tp_first" if stale_tp_blocks_stop_exit else "preview_only",
        "safe_to_apply_stop_exit_now": False,
        "why_not_safe_to_apply": "explicit_ack_and_runtime_evidence_required",
        "guards_required_when_apply_enabled": [
            "cancel_existing_tp_first",
            "verify_coinbase_cancelled",
            "coinbase_lookup_succeeds",
            "quote_cap_not_exceeded",
            "no_duplicate_open_d3_exit",
            "no_oversell",
            "terminal_fill_evidence_before_local_apply",
        ],
    }
    if (stop_cancel_enabled or stop_submit_enabled or stop_apply_enabled) and not stop_route_enabled:
        blockers.append("autonomous_stop_exit_apply_without_route_enabled")
    if (stop_cancel_enabled or stop_submit_enabled or stop_apply_enabled) and not mode_b_ack_status["ack_valid"]:
        if "mode_b_stop_exit_apply_ack_missing" not in blockers:
            blockers.append("mode_b_stop_exit_apply_ack_missing")

    entry_ready = bool(
        flags.get("enable_full_workflow_live_mode")
        and flags.get("enable_live_entry_orders")
        and flags.get("enable_live_limit_orders")
        and flags.get("enable_phase_c_actual_coinbase_submit")
    )
    d3_ready = bool(
        flags.get("enable_live_exit_orders")
        and flags.get("autonomous_allow_exits")
        and flags.get("enable_phase_d3_actual_exit_submit")
        and flags.get("phase_c43_lifecycle_allow_coinbase_poll")
        and not orders["duplicate_open_d3_exit_positions"]
        and not orders["missing_exchange_order_id_client_order_ids"]
    )
    learning_ready = bool(not enabled_forbidden and approved_profile["status"] in {"skipped", "loaded"})
    source_root = Path(__file__).resolve().parents[1]
    single_process_ready = (source_root / "bot/atomic_io.py").exists() and (source_root / "bot/run_cycle_guard.py").exists()
    atomic_ready = (source_root / "bot/atomic_io.py").exists()
    replication_disabled = not bool(
        replication_status.get("replication_enabled")
        or replication_status.get("replication_lifecycle_enabled")
        or replication_status.get("replication_lifecycle_http_enabled")
    )
    direct_parameter_mutation_disabled = _direct_parameter_mutation_disabled()
    neural_diagnostic_only = not bool(neural_learning_status.get("execution_allowed"))
    d2_d3_ready = bool(
        flags.get("enable_phase_d2_position_executor", True)
        and flags.get("enable_phase_d3_actual_exit_submit")
        and flags.get("enable_live_exit_orders")
        and flags.get("autonomous_allow_exits")
    )
    entry_lifecycle_enabled = bool(
        flags.get("phase_c43_lifecycle_allow_coinbase_poll")
        and flags.get("phase_c43_lifecycle_apply_local")
        and flags.get("phase_c43_lifecycle_build_d2_plan")
        and flags.get("phase_c43_lifecycle_build_d3_preview")
    )
    exit_lifecycle_enabled = bool(flags.get("phase_c43_lifecycle_allow_coinbase_poll"))
    controlled_stop_exit_apply_enabled = bool(
        stop_route_enabled
        and stop_cancel_enabled
        and stop_submit_enabled
        and stop_apply_enabled
        and mode_b_ack_status["ack_valid"]
    )
    poc_blockers: List[str] = []
    if config.get("status") != "valid":
        poc_blockers.append("config_invalid")
    if not entry_ready:
        poc_blockers.append("core_entries_not_enabled")
    if not d3_ready:
        poc_blockers.append("core_exits_or_d3_lifecycle_not_enabled")
    if not d2_d3_ready:
        poc_blockers.append("d2_d3_not_enabled")
    if not entry_lifecycle_enabled:
        poc_blockers.append("entry_lifecycle_apply_not_enabled")
    if not exit_lifecycle_enabled:
        poc_blockers.append("exit_lifecycle_polling_not_enabled")
    if not controlled_stop_exit_apply_enabled:
        poc_blockers.append("mode_b_controlled_stop_exit_not_ready")
    if not mode_b_ack_status["ack_valid"]:
        poc_blockers.append("mode_b_stop_exit_apply_ack_missing")
    # C4.3 uses post-only orderbook limit BUYs.  Mode C market orders are a
    # separate optional route and must be ready only when an operator enables
    # at least one of its three flags.
    if mode_c_market_readiness["enabled"] and not mode_c_market_readiness["ready"]:
        poc_blockers.extend(mode_c_market_readiness["blockers"] or ["mode_c_market_orders_not_ready"])
    if not replication_disabled:
        poc_blockers.append("market_orders_enabled_with_replication")
    if not direct_parameter_mutation_disabled:
        poc_blockers.append("direct_learning_to_execution_flags_enabled")
    if not neural_diagnostic_only:
        poc_blockers.append("neural_shadow_policy_execution_allowed")
    if approved_profile.get("status") != "loaded":
        poc_blockers.append("approved_parameter_profile_not_loaded")
    if orders["duplicate_open_d3_exit_positions"]:
        poc_blockers.append("duplicate_open_d3_exit")
    if orders["missing_exchange_order_id_client_order_ids"]:
        poc_blockers.append("open_d3_exit_missing_exchange_order_id")
    if min_quote != Decimal("50.00") or max_quote != Decimal("100.00"):
        poc_blockers.append("live_quote_rails_not_50_100")
    default_quote = _to_decimal(flags.get("default_quote_size_usdc"), "0")
    if default_quote < min_quote or default_quote > max_quote:
        poc_blockers.append("default_quote_outside_live_quote_rails")
    if int(flags.get("max_new_orders_per_cycle") or 0) != 1:
        poc_blockers.append("max_new_orders_per_cycle_not_1")
    if int(flags.get("autonomous_max_open_orders") or 0) != 3 or int(flags.get("max_open_positions") or 0) != 3:
        poc_blockers.append("max_open_orders_or_positions_not_3")
    if not single_process_ready:
        poc_blockers.append("single_process_guard_missing")
    if not atomic_ready:
        poc_blockers.append("atomic_write_guard_missing")
    poc_blockers = sorted(set(poc_blockers))
    poc_ready = not poc_blockers
    poc_full_workflow_readiness = {
        "ready": poc_ready,
        "core_entries_enabled": entry_ready,
        "core_exits_enabled": d3_ready,
        "d2_d3_enabled": d2_d3_ready,
        "entry_lifecycle_enabled": entry_lifecycle_enabled,
        "exit_lifecycle_enabled": exit_lifecycle_enabled,
        "controlled_stop_exit_apply_enabled": controlled_stop_exit_apply_enabled,
        "mode_b_ack_valid": bool(mode_b_ack_status["ack_valid"]),
        "market_orders_enabled": bool(mode_c_market_readiness["enabled"]),
        "mode_c_ack_valid": bool(mode_c_market_readiness["ack_valid"]),
        "replication_disabled": replication_disabled,
        "direct_parameter_mutation_disabled": direct_parameter_mutation_disabled,
        "neural_diagnostic_only": neural_diagnostic_only,
        "open_orders": int(orders["open_orders"]),
        "open_positions": int(positions["open_positions"]),
        "blockers": poc_blockers,
    }
    mode_a_blockers = list(blockers)
    if not single_process_ready:
        mode_a_blockers.append("single_process_guard_missing")
    if not atomic_ready:
        mode_a_blockers.append("atomic_write_guard_missing")
    if mode_a_blockers:
        if not single_process_ready or not atomic_ready:
            recommendation = "not_ready_concurrency_risk"
        else:
            recommendation = "not_ready_p0_runtime_bug"
    elif stop_apply_enabled:
        recommendation = "ready_for_mode_b_after_exact_ack_not_mode_a"
    else:
        recommendation = "ready_for_mode_a_bounded_autonomous_live_run"
    if poc_ready:
        recommendation = "ready_for_full_poc_live_run_no_replication"
    mode_a_ready = bool(not mode_a_blockers and entry_ready and d3_ready and not stop_apply_enabled)
    mode_b_ready = bool(
        not mode_a_blockers
        and stop_route_enabled
        and stop_apply_enabled
        and not orders["duplicate_open_d3_exit_positions"]
    )

    return {
        "phase": "full_autonomous_run_readiness_v1",
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "coinbase_submit_attempted": False,
        "coinbase_cancel_attempted": False,
        "coinbase_replace_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "service_touched": False,
        "service_config_readiness": config,
        "recommendation": recommendation,
        "blockers": mode_a_blockers,
        "warnings": warnings,
        "mode_a_readiness": {
            "ready": mode_a_ready,
            "reason": (
                "autonomous entries and D3 exits ready; stop-exit preview-only"
                if mode_a_ready
                else "mode_a_blocked_by_runtime_or_d3_readiness"
            ),
            "stop_exit_apply_disabled": not stop_apply_enabled,
            "stop_exit_preview_active": True,
            "if_stop_breach_occurs": "bot_will_not_market_exit_without_mode_b_ack",
            "acceptable_for_mode_a": not stop_apply_enabled,
        },
        "poc_full_workflow_readiness": poc_full_workflow_readiness,
        "entry_readiness": {"ready": entry_ready},
        "live_order_size_policy": live_order_size_policy,
        "bounded_exploration": bounded_exploration,
        "planner_judge_handoff": {
            "prepare_buy_prompt_enforced": True,
            "objective_score_prompt_enforced": True,
            "no_plan_requires_concrete_reason": True,
        },
        "neural_shadow_passivity": {
            "execution_allowed": bool(neural_learning_status.get("execution_allowed")),
            "one_class_dataset_warning": bool(neural_learning_status.get("one_class_dataset_warning")),
            "neural_shadow_one_class_passivity_bias": bool(neural_learning_status.get("neural_shadow_one_class_passivity_bias")),
            "balanced_label_recommendation": neural_learning_status.get("balanced_label_recommendation"),
        },
        "d3_lifecycle_readiness": {
            "ready": d3_ready,
            "open_d3_exit": orders["open_d3_exit"],
            "service_hook_d3_apply_local_forced_false": True,
            "terminal_d3_statuses_propose_apply_only": True,
            "exit_lifecycle_polling_enabled": exit_lifecycle_enabled,
            "terminal_fill_evidence_required_before_local_apply": True,
        },
        "exit_target_policy_readiness": {
            "ready": True,
            "config_flags_present": True,
            "stale_if_stop_breached": flags.get("exit_target_stale_if_stop_breached"),
            "max_distance_from_mid_pct": flags.get("exit_target_max_distance_from_mid_pct"),
        },
        "stop_breach_readiness": stop_readiness,
        "controlled_stop_exit_readiness": stop_readiness,
        "mode_b_ack_readiness": mode_b_ack_status,
        "market_order_status": mode_c_market_readiness,
        "mode_c_market_order_readiness": mode_c_market_readiness,
        "single_process_guard_readiness": {"ready": single_process_ready, "lock_path": "state/run_trader_loop.lock"},
        "atomic_write_readiness": {"ready": atomic_ready, "unique_tmp_names": True},
        "approved_parameter_profile_readiness": approved_profile,
        "learning_status": learning_status,
        "neural_learning_status": neural_learning_status,
        "replication_status": replication_status,
        "approved_profile_status": {
            "enabled": learning_status["approved_profile_enabled"],
            "hash_valid": learning_status["approved_profile_hash_valid"],
            "loaded": learning_status["approved_profile_loaded"],
            "hash": approved_profile.get("hash", ""),
            "parameters": approved_profile.get("parameters") or {},
        },
        "learning_sidecar_status": {
            "classification": sidecar.get("classification"),
            "parameter_recommendations": sidecar.get("parameter_recommendations") or [],
            "no_direct_learning_to_execution_bridge": bool((sidecar.get("governance") or {}).get("no_direct_learning_to_execution_bridge")),
            "recommendation": "keep_current_baseline" if sidecar.get("classification") == "WATCH" else "no_change",
        },
        "balanced_start_profile_status": balanced_profile,
        "research_prior_parameters": research_prior_parameters,
        "backtesting_parameter_bridge": backtesting_parameter_bridge,
        "open_orders_summary": orders,
        "current_position_summary": positions,
        "positions_summary": positions,
        "current_blockers": blockers,
        "mode_b_readiness": {
            "recommendation": "ready_for_mode_b_only_after_explicit_ack" if mode_b_ready else "not_ready_p0_runtime_bug",
            "ready": mode_b_ready,
            "reason": (
                "controlled stop-exit apply disabled and requires ACK"
                if not mode_b_ready
                else "controlled stop-exit apply flags enabled; explicit ACK still required per action"
            ),
            "explicit_operator_ack_required": True,
            "required_conditions": [
                "ENABLE_CONTROLLED_STOP_MARKET_EXITS=true",
                "ENABLE_AUTONOMOUS_STOP_EXIT_APPLY=true",
                f"{MODE_B_CONTROLLED_STOP_EXIT_ACK_ENV}={MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE}",
                "cancel-first route verified",
                "no duplicate/oversell",
                "Coinbase lookup succeeds",
                "terminal fill evidence before local apply",
            ],
        },
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only full autonomous bounded-run readiness.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_full_autonomous_run_readiness_report(root=args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"recommendation={report['recommendation']} blockers={','.join(report['current_blockers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_full_autonomous_run_readiness_report", "main", "parse_args"]
