from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from bot.pre_live_current_state import build_pre_live_current_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE = "pre_live_startup_gate_v1"

STARTUP_BLOCK_EXIT_CODE = 4


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def live_workflow_enabled(cfg: Any) -> bool:
    if str(getattr(cfg, "execution_mode", "")).strip().lower() == "live":
        return True
    return any(
        _cfg_bool(cfg, name)
        for name in (
            "enable_full_workflow_live_mode",
            "enable_limit_order_manager",
            "enable_live_limit_orders",
            "enable_live_entry_orders",
            "enable_phase_c_live_small_limit_orders",
            "enable_phase_c_actual_coinbase_submit",
            "enable_autonomous_small_live_orderbook_mode",
            "enable_resting_limit_entry_live_submit",
            "enable_pending_entry_live_cancel",
            "enable_live_exit_orders",
            "autonomous_allow_exits",
            "enable_phase_d3_actual_exit_submit",
            "phase_c43_lifecycle_allow_coinbase_poll",
            "phase_c43_lifecycle_apply_local",
            "enable_controlled_stop_market_exits",
            "enable_autonomous_stop_exit_submit",
            "enable_autonomous_stop_exit_apply",
        )
    )


def assess_pre_live_startup_gate(cfg: Any, root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    live_enabled = live_workflow_enabled(cfg)
    current = build_pre_live_current_state(root)
    blockers: List[str] = list(current.get("blockers") or [])
    market_flags = {
        "market_order_enabled": _cfg_bool(cfg, "market_order_enabled"),
        "enable_market_orders": _cfg_bool(cfg, "enable_market_orders"),
        "allow_market_orders": _cfg_bool(cfg, "allow_market_orders"),
    }
    if any(market_flags.values()):
        blockers.append("market_order_flags_enabled_forbidden_orderbook_workflow")
    blockers = sorted(set(blockers))
    startup_allowed = bool(not live_enabled or not blockers)
    return {
        "phase": PHASE,
        "startup_allowed": startup_allowed,
        "blockers": blockers,
        "operator_action": "do_not_run_bot_yet" if not startup_allowed else "startup_allowed",
        "live_workflow_enabled": live_enabled,
        "pipeline_health": "green" if not blockers else "red",
        "pre_live_health_missing": False,
        "safe_to_restart": bool(not blockers),
        "terminal_operator_status": "do_not_run_bot_yet" if not startup_allowed else "startup_allowed",
        "current_state": current,
        "historical_reports_are_diagnostic_only": True,
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "service_restart_attempted": False,
        "lock_removed": False,
    }


def enforce_pre_live_startup_gate(cfg: Any, root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    report = assess_pre_live_startup_gate(cfg, root=root)
    if not report["startup_allowed"]:
        raise SystemExit(STARTUP_BLOCK_EXIT_CODE)
    return report


__all__ = [
    "STARTUP_BLOCK_EXIT_CODE",
    "assess_pre_live_startup_gate",
    "enforce_pre_live_startup_gate",
    "live_workflow_enabled",
]
