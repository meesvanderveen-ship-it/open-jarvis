#!/usr/bin/env python3
"""Run the report-only GrowBot/River parameter-learning sidecar."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.adaptive_policy_lab import build_adaptive_policy_candidate, write_adaptive_policy_outputs
from bot.atomic_io import atomic_write_json
from bot.growbot_learning_adapter import build_growbot_episode_report, write_growbot_episode_report
from bot.growbot_river_readiness import build_growbot_river_readiness, write_growbot_river_readiness
from bot.learnable_parameter_registry import build_learnable_parameter_registry
from bot.parameter_candidate_analysis import build_parameter_candidate_analysis, write_parameter_candidate_analysis
from bot.parameter_step_scheduler import schedule_parameter_steps
from bot.river_online_parameter_learner import run_river_online_parameter_learning


REPORT_PATH = Path("reports/growbot_river/growbot-river-learning-latest.json")
HISTORY_PATH = Path("reports/growbot_river/history/proposal-history.jsonl")


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_history(path: Path) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-10_000:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_history(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "generated_at": report["generated_at"],
        "phase": report.get("phase"),
        "proposals": report.get("proposals") or [],
        "river_newly_processed": ((report.get("river") or {}).get("processing") or {}).get("newly_processed", 0),
        "new_memory_episodes": ((report.get("episode_report") or {}).get("memory") or {}).get("added", 0),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run report-only GrowBot/River online parameter learning.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--max-per-source", type=int, default=1500)
    parser.add_argument("--growbot-source", default=None, help="Optional local GrowBot source tree; inspected for provenance only and never imported.")
    parser.add_argument("--skip-adaptive-chain", action="store_true", help="Do not refresh existing adaptive-policy and analysis reports.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    episode_report = build_growbot_episode_report(
        root,
        max_per_source=max(1, args.max_per_source),
        append_memory=True,
        growbot_source_path=args.growbot_source,
    )
    episode_output = write_growbot_episode_report(episode_report, root=root)
    river_report = run_river_online_parameter_learning(episode_report["episodes"], root=root)
    history_path = root / HISTORY_PATH
    history = _load_history(history_path)
    summary = episode_report["summary"]
    schedule = schedule_parameter_steps(
        river_report.get("parameter_signals") or [],
        root=root,
        episode_count=int((episode_report.get("memory") or {}).get("total_after") or summary.get("episode_count") or 0),
        regimes=summary.get("regimes") or [],
        history=history,
    )
    report: Dict[str, Any] = {
        "schema_version": "growbot_river_learning_cycle_v1",
        "phase": "growbot_river_parameter_learning_report_only",
        "generated_at": now_iso(),
        "workflow_position": "logs/outcomes/reflections/backtests -> GrowBot/River -> adaptive_policy_lab -> parameter_candidate_analysis -> autonomous_parameter_governor -> approved_parameter_profile -> BotConfig",
        "episode_report": {
            "path": episode_output,
            "summary": summary,
            "sources": episode_report["sources"],
            "episode_identity": episode_report.get("episode_identity") or {},
            "learning_data_contract": episode_report.get("learning_data_contract") or {},
            "memory": episode_report["memory"],
        },
        "growbot_open_source": episode_report.get("growbot_open_source") or {},
        "river": river_report,
        "registry": build_learnable_parameter_registry(root),
        "phase_decision": schedule["phase_decision"],
        "phase_limits": schedule["phase_limits"],
        "proposals": schedule["proposals"],
        "blocked_proposals": schedule["blocked_proposals"],
        "safety_policy": {
            "report_only": True,
            "parameter_mutation_allowed": False,
            "execution_authority": False,
            "coinbase_calls_attempted": False,
            "order_submit_cancel_replace_attempted": False,
            "approved_profile_hash_ack_required": True,
            "C43_D3_bypass_allowed": False,
        },
        "downstream": {
            "adaptive_policy_lab": "pending_refresh" if not args.skip_adaptive_chain else "not_refreshed",
            "parameter_candidate_analysis": "pending_refresh" if not args.skip_adaptive_chain else "not_refreshed",
            "autonomous_parameter_governor": "not_invoked_by_this_tool",
            "approved_parameter_profile": "not_mutated_by_this_tool",
            "BotConfig": "not_instantiated_or_mutated_by_this_tool",
        },
    }
    atomic_write_json(root / REPORT_PATH, report)
    # Replays caused by a report-only model migration are not new evidence and
    # must not manufacture extra direction-stability history.
    if int((episode_report.get("memory") or {}).get("added") or 0) > 0:
        _append_history(history_path, report)

    if not args.skip_adaptive_chain:
        candidate = build_adaptive_policy_candidate(root=root)
        candidate_outputs = write_adaptive_policy_outputs(candidate, root=root)
        analysis = build_parameter_candidate_analysis(root=root, candidate=candidate)
        analysis_outputs = write_parameter_candidate_analysis(analysis, root=root)
        report["downstream"].update({
            "adaptive_policy_lab": candidate_outputs.get("lab"),
            "parameter_candidate_analysis": analysis_outputs.get("json"),
            "autonomous_parameter_governor": "not_invoked_by_this_tool; existing governor retains ACK and safety gates",
        })
        report["downstream_candidate"] = {
            "candidate_available": candidate.get("candidate_available"),
            "candidate_hash": candidate.get("hash"),
            "analysis_available": analysis.get("parameter_analysis_available"),
            "analysis_hash": analysis.get("analysis_hash"),
        }
    readiness = build_growbot_river_readiness(root=root, episode_report=episode_report, river_report=river_report)
    readiness_output = write_growbot_river_readiness(readiness, root=root)
    report["readiness"] = {
        "path": readiness_output,
        "report_only_ready": readiness["readiness"]["report_only_ready"],
        "stabilization_ready": readiness["readiness"]["stabilization_ready"],
        "blockers": readiness["blockers"],
    }
    atomic_write_json(root / REPORT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "growbot_river "
            f"episodes={summary.get('episode_count')} "
            f"new={((river_report.get('processing') or {}).get('newly_processed', 0))} "
            f"phase={report.get('phase_decision', {}).get('phase')} "
            f"proposals={len(report.get('proposals') or [])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
