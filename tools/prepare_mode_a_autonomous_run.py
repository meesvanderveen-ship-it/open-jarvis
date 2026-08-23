#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.autonomous_live_run_common import now_iso
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report


def build_prepare_mode_a_autonomous_run(*, root: str | Path = ".") -> Dict[str, Any]:
    readiness = build_full_autonomous_run_readiness_report(root=root)
    mode_a = readiness.get("mode_a_readiness") or {}
    blockers = list(readiness.get("blockers") or [])
    allowed = bool(mode_a.get("ready") and not blockers)
    return {
        "phase": "prepare_mode_a_autonomous_run_v1",
        "generated_at": now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "service_restart_attempted": False,
        "mode_a_start_allowed": allowed,
        "readiness": readiness.get("recommendation"),
        "blockers": blockers,
        "operator_command_restart": "sudo systemctl restart coinbase-bot.service",
        "operator_command_monitor": "python3 tools/show_autonomous_live_run_status.py --json",
        "operator_command_6h_report": "python3 tools/write_autonomous_live_run_report.py --since-hours 6 --json-out reports/live_runs/live-run-latest.json",
        "operator_command_12h_report": "python3 tools/write_autonomous_live_run_report.py --since-hours 12 --json-out reports/live_runs/live-run-latest.json",
        "operator_command_24h_report": "python3 tools/write_autonomous_live_run_report.py --since-hours 24 --json-out reports/live_runs/live-run-latest.json",
        "stop_conditions": [
            "readiness recommendation changes away from ready_for_mode_a_bounded_autonomous_live_run",
            "duplicate_open_d3_exit appears",
            "open_d3_exit_missing_exchange_order_id appears",
            "run_health becomes critical",
            "process lock conflict or duplicate cycle boundary repeats",
            "stop breach occurs while Mode B remains disabled: review/cancel-first decision required",
            "Coinbase/API/LLM provider errors repeat across cycles",
        ],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare one safe operator start for Mode A autonomous run.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_prepare_mode_a_autonomous_run(root=args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"mode_a_start_allowed={report['mode_a_start_allowed']} restart='{report['operator_command_restart']}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_prepare_mode_a_autonomous_run", "main", "parse_args"]
