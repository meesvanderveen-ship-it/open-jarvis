#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json
from tools.autonomous_live_run_common import (
    detect_service_status,
    now_iso,
    open_orders_summary,
    process_lock_status,
    summarize_logs,
)
from tools.build_live_learning_sidecar import build_live_learning_sidecar_report
from tools.propose_balanced_start_parameter_profile import build_balanced_start_parameter_profile_candidate
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report

DEFAULT_OUTPUT = Path("reports/live_runs/live-run-latest.json")


def build_autonomous_live_run_report(*, root: str | Path = ".", since_hours: int = 24) -> Dict[str, Any]:
    project_root = Path(root)
    logs = summarize_logs(project_root, since_hours=since_hours)
    readiness = build_full_autonomous_run_readiness_report(root=project_root)
    sidecar = build_live_learning_sidecar_report(root=project_root)
    candidate = build_balanced_start_parameter_profile_candidate(root=project_root)
    orders = open_orders_summary(project_root)
    service = detect_service_status()
    lock = process_lock_status(project_root)
    critical_runtime = bool(
        readiness.get("blockers")
        or logs.get("duplicate_cycle_evidence")
        or logs.get("atomic_write_errors")
        or logs.get("state_write_errors")
        or logs.get("lifecycle_exceptions")
        or orders.get("duplicate_open_d3_exit_positions")
        or orders.get("missing_exchange_order_id_client_order_ids")
    )
    warning_runtime = bool(
        logs.get("errors")
        or logs.get("llm_provider_errors")
        or logs.get("llm_corrupt_outputs")
        or logs.get("blocked_actions")
        or logs.get("blocked_duplicate_or_oversell_signals")
    )
    run_quality = "bad" if critical_runtime else "warning" if warning_runtime else "good"
    recommendation = "stop_and_fix" if run_quality == "bad" else "review_before_continue" if run_quality == "warning" else "continue_mode_a"
    if run_quality == "good" and since_hours < 24:
        recommendation = "extend_to_24h"
    missed_fill = int(logs.get("missed_fill_evidence") or (candidate.get("basis") or {}).get("missed_fill_opportunity") or 0)
    false_positive = int(logs.get("false_positive_or_quick_stop_signals") or (candidate.get("basis") or {}).get("false_positive_plans") or 0)
    if run_quality != "bad" and missed_fill and not false_positive:
        profile_action = "review_conservative"
    elif false_positive:
        profile_action = "do_not_change"
    else:
        profile_action = "keep_baseline"
    mode_b_reasons = []
    if run_quality == "good":
        mode_b_reasons.append("runtime_clean")
    if not logs.get("blocked_duplicate_or_oversell_signals") and not orders.get("duplicate_open_d3_exit_positions"):
        mode_b_reasons.append("no_duplicate_or_oversell_evidence")
    if not logs.get("lifecycle_exceptions"):
        mode_b_reasons.append("d3_lifecycle_clean")
    mode_b_candidate = {
        "candidate": run_quality == "good"
        and "no_duplicate_or_oversell_evidence" in mode_b_reasons
        and "d3_lifecycle_clean" in mode_b_reasons,
        "reasons": mode_b_reasons,
        "still_requires_ack": True,
    }
    return {
        "phase": "autonomous_live_run_report_v1",
        "generated_at": now_iso(),
        "since_hours": since_hours,
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "service_uptime_evidence": {
            "service_detectable": service.get("detectable"),
            "systemd_service_status": service.get("status"),
            "systemd_pid": service.get("active_pid"),
            "uptime_seconds": service.get("uptime_seconds"),
        },
        "process_lock_evidence": lock,
        "summary": logs,
        "open_orders_summary": orders,
        "cycles_expected_vs_observed": logs.get("cycles_expected_vs_observed"),
        "heartbeat_expected_vs_observed": logs.get("heartbeat_expected_vs_observed"),
        "duplicate_cycle_evidence": logs.get("duplicate_cycle_evidence"),
        "atomic_write_errors": logs.get("atomic_write_errors"),
        "state_write_errors": logs.get("state_write_errors"),
        "lifecycle_exceptions": logs.get("lifecycle_exceptions"),
        "llm_http_200_count": logs.get("llm_http_200_count"),
        "llm_provider_errors": logs.get("llm_provider_errors"),
        "per_ticker_decision_counts": logs.get("per_ticker_decision_counts"),
        "buy_intents": logs.get("buy_intents"),
        "buy_submits": logs.get("buy_submits"),
        "open_orders_created": logs.get("open_orders_created"),
        "fills": logs.get("fills"),
        "d3_lifecycle_polls": logs.get("d3_lifecycle_polls"),
        "d3_keep_open_counts": logs.get("d3_keep_open_counts"),
        "d3_terminal_proposals": logs.get("d3_terminal_proposals"),
        "stop_breach_signals": logs.get("stop_breach_signals"),
        "stale_tp_detections": logs.get("stale_tp_signals"),
        "controlled_stop_exit_previews": logs.get("controlled_stop_exit_preview_signals"),
        "blocked_duplicate_or_oversell_signals": logs.get("blocked_duplicate_or_oversell_signals"),
        "d3_status": {
            "lifecycle_last_status": logs.get("d3_lifecycle_last_status"),
            "lifecycle_summary": logs.get("d3_lifecycle_summary"),
        },
        "stop_exit_preview_status": readiness.get("controlled_stop_exit_readiness"),
        "learning_evidence_summary": {
            "classification": sidecar.get("classification"),
            "decision_outcomes": sidecar.get("decision_outcomes"),
            "execution_outcomes": sidecar.get("execution_outcomes"),
            "parameter_recommendations": sidecar.get("parameter_recommendations") or [],
        },
        "parameter_candidate_implications": {
            "classification": candidate.get("classification"),
            "safe_to_activate_now": candidate.get("safe_to_activate_now"),
            "profiles": list((candidate.get("profiles") or {}).keys()),
            "recommended_operator_action": candidate.get("recommended_operator_action"),
        },
        "run_quality": run_quality,
        "recommendation": recommendation,
        "recommendation_for_next_run": recommendation,
        "mode_b_candidate": mode_b_candidate,
        "profile_candidate_action": profile_action,
    }


def _write(path: Path, payload: Dict[str, Any]) -> None:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/live_runs").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/live_runs")
    atomic_write_json(target, payload)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write read-only autonomous live run report.")
    parser.add_argument("--json-out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--since-hours", type=int, default=24, choices=[6, 12, 24, 48, 72])
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_autonomous_live_run_report(root=args.root, since_hours=args.since_hours)
    _write(Path(args.json_out), report)
    print(json.dumps({"status": "autonomous_live_run_report_written", "json_out": args.json_out, "recommendation": report["recommendation"], "run_quality": report["run_quality"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DEFAULT_OUTPUT", "build_autonomous_live_run_report", "main", "parse_args"]
