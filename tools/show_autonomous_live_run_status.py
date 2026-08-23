#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.autonomous_live_run_common import (
    detect_service_status,
    latest_cycle_times,
    latest_lifecycle_status,
    now_iso,
    open_orders_summary,
    process_lock_status,
    summarize_logs,
)
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report


def build_autonomous_live_run_status(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    readiness = build_full_autonomous_run_readiness_report(root=project_root)
    replication_status = readiness.get("replication_status") if isinstance(readiness.get("replication_status"), dict) else {}
    flags = ((readiness.get("service_config_readiness") or {}).get("flags") or {})
    service = detect_service_status()
    lock = process_lock_status(project_root)
    cycles = latest_cycle_times(project_root)
    lifecycle = latest_lifecycle_status(project_root)
    orders = open_orders_summary(project_root)
    logs = summarize_logs(project_root, since_hours=24)
    systemd_pid = str(service.get("active_pid") or "")
    lock_pid = str(lock.get("pid") or "")
    pid_consistent = True
    if systemd_pid and systemd_pid != "0" and lock_pid:
        pid_consistent = systemd_pid == lock_pid
    mode = "unknown"
    if service.get("detectable") and service.get("status", "").startswith("inactive"):
        mode = "not_running"
    elif readiness.get("recommendation") == "ready_for_full_poc_live_run_no_replication":
        mode = "full_poc_live_no_replication"
    elif flags.get("enable_autonomous_stop_exit_apply") or ((readiness.get("mode_b_ack_readiness") or {}).get("autonomous_apply_enabled")):
        mode = "mode_b_apply_enabled"
    elif lock.get("pid_alive") and readiness.get("recommendation") == "ready_for_mode_a_bounded_autonomous_live_run":
        mode = "mode_a_preview_stop_exit"
    elif service.get("detectable") and readiness.get("recommendation") == "ready_for_mode_a_bounded_autonomous_live_run":
        mode = "mode_a_preview_stop_exit"
    health = "healthy"
    if readiness.get("blockers"):
        health = "blocked"
    if logs.get("errors") or logs.get("llm_provider_errors") or cycles.get("duplicate_cycle_detection"):
        health = "warning" if health == "healthy" else health
    if logs.get("atomic_write_errors") or logs.get("state_write_errors") or logs.get("lifecycle_exceptions"):
        health = "warning" if health == "healthy" else health
    if logs.get("last_cycle_summary") is None:
        health = "warning" if health == "healthy" else health
    elif int((logs.get("last_cycle_summary") or {}).get("errors") or 0) == 0 and not (
        logs.get("atomic_write_errors")
        or logs.get("state_write_errors")
        or logs.get("lifecycle_exceptions")
        or cycles.get("duplicate_cycle_detection")
    ):
        health = "healthy" if health == "healthy" else health
    if not pid_consistent or lock.get("stale"):
        health = "warning" if health == "healthy" else health
    if orders.get("duplicate_open_d3_exit_positions") or orders.get("missing_exchange_order_id_client_order_ids"):
        health = "critical"
    return {
        "phase": "autonomous_live_run_status_v1",
        "generated_at": now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "service_restart_attempted": False,
        "service_status": service,
        "service_detectable": bool(service.get("detectable")),
        "systemd_service_status": service.get("status"),
        "systemd_pid": systemd_pid,
        "lock_pid": lock_pid,
        "pid_consistent": pid_consistent,
        "stale_lock_detected": bool(lock.get("stale")),
        "active_pid": service.get("active_pid") or lock.get("pid") or "",
        "process_lock_status": lock,
        **cycles,
        **lifecycle,
        "open_orders_summary": orders,
        "open_d3_exit_summary": {"count": orders.get("open_d3_exit"), "samples": orders.get("open_d3_exit_samples")},
        "d3_lifecycle_last_status": lifecycle.get("last_d3_lifecycle_status") or logs.get("d3_lifecycle_last_status"),
        "last_d3_lifecycle_status": lifecycle.get("last_d3_lifecycle_status"),
        "last_d3_coinbase_call_attempted": lifecycle.get("last_d3_coinbase_call_attempted"),
        "last_d3_proposed_action": lifecycle.get("last_d3_proposed_action"),
        "entry_attempts": logs.get("entry_attempts"),
        "last_cycle_summary": logs.get("last_cycle_summary"),
        "last_gate_summary": logs.get("last_gate_summary"),
        "orders_submitted": logs.get("orders_submitted"),
        "fills": logs.get("fills"),
        "waits": logs.get("waits"),
        "close_position_signals": logs.get("close_position_signals"),
        "stop_breach_signals": logs.get("stop_breach_signals"),
        "stale_tp_signals": logs.get("stale_tp_signals"),
        "controlled_stop_exit_preview_signals": logs.get("controlled_stop_exit_preview_signals"),
        "errors_by_type": logs.get("errors_by_type"),
        "recent_runtime_errors": logs.get("runtime_error_lines") or [],
        "recent_state_write_errors": {
            "atomic_write_errors": logs.get("atomic_write_errors"),
            "state_write_errors": logs.get("state_write_errors"),
        },
        "recent_duplicate_cycle_evidence": logs.get("duplicate_cycle_evidence"),
        "recent_stop_breach_evidence": logs.get("stop_breach_signals"),
        "recent_stale_tp_evidence": logs.get("stale_tp_signals"),
        "latest_readiness_recommendation": readiness.get("recommendation"),
        "learning_status": readiness.get("learning_status"),
        "neural_learning_status": readiness.get("neural_learning_status"),
        "live_order_size_policy": readiness.get("live_order_size_policy"),
        "bounded_exploration": readiness.get("bounded_exploration"),
        "planner_judge_handoff": readiness.get("planner_judge_handoff"),
        "neural_shadow_passivity": readiness.get("neural_shadow_passivity"),
        "research_prior_parameters": readiness.get("research_prior_parameters"),
        "backtesting_parameter_bridge": readiness.get("backtesting_parameter_bridge"),
        "approved_profile_status": readiness.get("approved_profile_status"),
        "replication_status": replication_status,
        "market_order_status": readiness.get("market_order_status"),
        "mode_c_market_order_readiness": readiness.get("mode_c_market_order_readiness"),
        "mode_b_ack_readiness": readiness.get("mode_b_ack_readiness"),
        "mode": mode,
        "run_health": health,
        "readiness": {
            "blockers": readiness.get("blockers"),
            "mode_a_readiness": readiness.get("mode_a_readiness"),
            "mode_b_readiness": readiness.get("mode_b_readiness"),
            "poc_full_workflow_readiness": readiness.get("poc_full_workflow_readiness"),
        },
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only autonomous live run status.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_autonomous_live_run_status(root=args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"mode={report['mode']} health={report['run_health']} readiness={report['latest_readiness_recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_autonomous_live_run_status", "main", "parse_args"]
