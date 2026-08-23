#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.autonomous_live_run_common import now_iso, open_orders_summary
from tools.show_autonomous_live_run_status import build_autonomous_live_run_status
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report

ALLOWED_HOURS = (6, 12, 24, 48, 72)

STOP_CONDITIONS = [
    "duplicate open D3 exit",
    "missing exchange_order_id on open live order",
    "lifecycle hook exception",
    "repeated atomic write error",
    "process lock conflict",
    "Coinbase lookup failure repeated",
    "unexpected live cancel/replace/apply",
    "more than configured max open orders",
    "oversell/duplicate SELL signal",
    "run_health critical",
]

WHAT_NOT_TO_TOUCH = [
    "do not manually submit/cancel/replace/apply Coinbase orders during Mode A",
    "do not enable Mode B flags without the separate exact ACK",
    "do not mutate .env during the run",
    "do not repair production state during the run",
    "do not activate a balanced profile without hash ACK",
    "do not create a second SELL against reserved base",
]


def build_prepare_autonomous_endurance_run(*, root: str | Path = ".", hours: int = 24) -> Dict[str, Any]:
    if hours not in ALLOWED_HOURS:
        raise ValueError(f"hours must be one of {ALLOWED_HOURS}")
    project_root = Path(root)
    readiness = build_full_autonomous_run_readiness_report(root=project_root)
    status = build_autonomous_live_run_status(root=project_root)
    orders = open_orders_summary(project_root)
    blockers = list(readiness.get("blockers") or [])
    warnings = list(readiness.get("warnings") or [])
    if orders.get("duplicate_open_d3_exit_positions"):
        blockers.append("duplicate_open_d3_exit")
    if orders.get("missing_exchange_order_id_client_order_ids"):
        blockers.append("missing_exchange_order_id_on_open_d3_exit")
    if status.get("run_health") == "critical":
        blockers.append("run_health_critical")
    if status.get("stale_lock_detected"):
        warnings.append("stale_process_lock_detected")
    mode_a = readiness.get("mode_a_readiness") or {}
    mode_b = readiness.get("mode_b_readiness") or {}
    readiness_recommendation = str(readiness.get("recommendation") or "")
    mode_a_allowed = (
        not blockers
        and readiness_recommendation == "ready_for_mode_a_bounded_autonomous_live_run"
        and bool(mode_a.get("ready", True))
    )
    report_path = f"reports/live_runs/live-run-{hours}h.json"
    return {
        "phase": "prepare_autonomous_endurance_run_v1",
        "generated_at": now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "service_restart_attempted": False,
        "endurance_run_allowed": mode_a_allowed,
        "mode_a_can_run": mode_a_allowed,
        "mode": status.get("mode") or "unknown",
        "duration_hours": hours,
        "readiness": readiness_recommendation,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "current_mode_status": {
            "run_health": status.get("run_health"),
            "service_detectable": status.get("service_detectable"),
            "systemd_service_status": status.get("systemd_service_status"),
            "systemd_pid": status.get("systemd_pid"),
            "lock_pid": status.get("lock_pid"),
            "pid_consistent": status.get("pid_consistent"),
        },
        "mode_a_readiness": mode_a,
        "mode_b_disabled_reason": (mode_b.get("reason") if isinstance(mode_b, dict) else "") or "controlled stop-exit apply disabled and requires ACK",
        "operator_commands": {
            "restart": "sudo systemctl restart coinbase-bot.service",
            "monitor": "python3 tools/show_autonomous_live_run_status.py --json",
            "follow_logs": "journalctl -u coinbase-bot -f --no-pager -l",
            "write_report": f"python3 tools/write_autonomous_live_run_report.py --since-hours {hours} --json-out {report_path}",
            "next_steps": f"python3 tools/summarize_autonomous_run_next_steps.py --run-report {report_path} --balanced-profile reports/live_learning/balanced-start-profile-candidate.json --json",
        },
        "stop_conditions": STOP_CONDITIONS,
        "what_not_to_touch_during_run": WHAT_NOT_TO_TOUCH,
        "open_orders_summary": orders,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare one safe operator command set for a Mode A endurance run.")
    parser.add_argument("--hours", type=int, default=24, choices=ALLOWED_HOURS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_prepare_autonomous_endurance_run(root=args.root, hours=args.hours)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"allowed={report['endurance_run_allowed']} "
            f"mode={report['mode']} readiness={report['readiness']} "
            f"restart={report['operator_commands']['restart']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ALLOWED_HOURS", "STOP_CONDITIONS", "build_prepare_autonomous_endurance_run", "main", "parse_args"]
