#!/usr/bin/env python3
"""Refresh the GrowBot/River learning chain and prepare it for the existing
autonomous-parameter-governor route in one call.

This tool introduces no new activation path. It chains three already
existing, independently runnable steps:

1. ``tools/run_growbot_river_learning_cycle.py`` -- refreshes episodes,
   River online learning, the bounded step-scheduler proposals, the
   adaptive-policy candidate/analysis bridge, and growbot-river readiness.
2. ``tools/build_live_cycle_readiness_report.py`` -- refreshes the
   live-cycle snapshot used for the episodes/cycles-still-needed numbers.
3. ``bot.growbot_river_governor_bridge`` -- aggregates the result into one
   bridge-status object (report-only).

With ``--apply``, it additionally invokes the existing
``bot.autonomous_parameter_governor.run_governor`` exactly as
``tools/run_autonomous_parameter_governor.py --apply`` would: still gated by
the unchanged governor ACK/mode/cooldown/regime/evidence/open-order safety
rails. No gate is loosened, skipped, or duplicated here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.atomic_io import atomic_write_json
from bot.autonomous_parameter_governor import acquire_governor_lock, release_governor_lock, run_governor
from bot.growbot_river_governor_bridge import (
    build_growbot_river_governor_bridge_status,
    write_growbot_river_governor_bridge_status,
)


PREPARATION_PATH = Path("reports/growbot_river/growbot-river-governor-candidate-preparation-latest.json")


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_tool(root: Path, args: Sequence[str]) -> Dict[str, Any]:
    import subprocess

    cmd = [sys.executable, *args, "--root", str(root), "--json"]
    result = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    try:
        payload = json.loads(result.stdout)
    except Exception:
        payload = {}
    return {
        "args": list(args),
        "returncode": result.returncode,
        "ok": result.returncode == 0,
        "stderr_tail": result.stderr[-1000:],
        "summary": payload if isinstance(payload, dict) else {},
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh GrowBot/River learning and prepare it for the existing governor route.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--apply", action="store_true", help="Also invoke the existing governor apply path (still gated by ACK/mode/cooldown/safety rails).")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip refreshing the river/candidate chain; only recompute bridge status from existing reports.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root)
    refresh_steps: List[Dict[str, Any]] = []
    if not args.skip_refresh:
        refresh_steps.append(_run_tool(root, ["tools/run_growbot_river_learning_cycle.py"]))
        refresh_steps.append(_run_tool(root, ["tools/build_live_cycle_readiness_report.py"]))

    bridge_status = build_growbot_river_governor_bridge_status(root=root)
    bridge_outputs = write_growbot_river_governor_bridge_status(bridge_status, root=root)

    governor_run: Dict[str, Any] = {"invoked": False, "reason": "apply_not_requested"}
    if args.apply:
        # Use the same lock run_governor_cycle() uses, so a scheduled run of
        # this tool can never race a concurrent run of the existing governor
        # cycle (tools/run_autonomous_parameter_governor.py) over the same
        # approved_parameter_profile.json / activation log.
        lock = acquire_governor_lock(root)
        if lock.get("acquired"):
            try:
                governor_run = run_governor(root=root, apply=True)
            finally:
                release_governor_lock(root)
        else:
            governor_run = {"applied": False, "reason": lock.get("reason"), "state_write_performed": False}
        governor_run["invoked"] = True
        governor_run["lock"] = lock

    report = {
        "schema_version": "growbot_river_governor_candidate_preparation_v1",
        "generated_at": now_iso(),
        "refresh_skipped": bool(args.skip_refresh),
        "refresh_steps": refresh_steps,
        "refresh_ok": all(step["ok"] for step in refresh_steps) if refresh_steps else None,
        "bridge_status": bridge_status,
        "bridge_status_outputs": bridge_outputs,
        "governor_run": governor_run,
        "safety_policy": {
            "report_only_unless_apply_requested": True,
            "apply_still_requires_existing_ack_mode_and_safety_gates": True,
            "introduces_new_activation_route": False,
        },
    }
    atomic_write_json(root / PREPARATION_PATH, report)
    report["output"] = str(root / PREPARATION_PATH)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "growbot_river_governor_candidate_preparation "
            f"refresh_ok={report['refresh_ok']} "
            f"bridge_ready={bridge_status['bridge_ready']} "
            f"candidate_ready={bridge_status['candidate_ready']} "
            f"auto_apply_eligible={bridge_status['auto_apply_eligible']} "
            f"governor_invoked={governor_run['invoked']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
