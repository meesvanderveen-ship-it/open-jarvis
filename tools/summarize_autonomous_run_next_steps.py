#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.autonomous_live_run_common import load_json, now_iso


def build_next_steps_summary(*, run_report: str | Path, balanced_profile: str | Path) -> Dict[str, Any]:
    run = load_json(Path(run_report))
    profile = load_json(Path(balanced_profile))
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    basis = profile.get("basis") if isinstance(profile.get("basis"), dict) else {}
    blockers = []
    runtime_issues = []
    risk_issues = []
    missed_fill = int(basis.get("missed_fill_opportunity") or 0)
    missed_opp = int(basis.get("missed_opportunities") or 0)
    missed_fill = max(missed_fill, int(summary.get("missed_fill_evidence") or 0))
    false_positive = int(basis.get("false_positive_plans") or 0) + int(summary.get("false_positive_or_quick_stop_signals") or 0)
    if not run:
        blockers.append("run_report_missing")
    if not profile:
        blockers.append("balanced_profile_missing")
    if summary.get("blocked_actions"):
        risk_issues.append("blocked_actions_seen")
    if summary.get("blocked_duplicate_or_oversell_signals"):
        risk_issues.append("duplicate_or_oversell_signal_seen")
    if summary.get("stale_tp_signals"):
        risk_issues.append("stale_target_signals_seen")
    if (run.get("open_orders_summary") or {}).get("duplicate_open_d3_exit_positions"):
        risk_issues.append("duplicate_open_d3_exit_seen")
    if summary.get("errors") or summary.get("llm_provider_errors") or summary.get("llm_corrupt_outputs"):
        runtime_issues.append("runtime_or_llm_errors_seen")
    if summary.get("duplicate_cycle_evidence") or run.get("duplicate_cycle_evidence"):
        runtime_issues.append("duplicate_cycle_evidence_seen")
    if summary.get("atomic_write_errors") or run.get("atomic_write_errors"):
        runtime_issues.append("atomic_write_errors_seen")
    if summary.get("state_write_errors") or run.get("state_write_errors"):
        runtime_issues.append("state_write_errors_seen")
    if summary.get("lifecycle_exceptions") or run.get("lifecycle_exceptions"):
        runtime_issues.append("lifecycle_exceptions_seen")
    d3_clean = not summary.get("lifecycle_exceptions") and not (run.get("open_orders_summary") or {}).get("duplicate_open_d3_exit_positions")
    if blockers or runtime_issues:
        recommendation = "stop_and_fix"
        profile_action = "no_profile_activation"
    elif false_positive:
        recommendation = "continue_mode_a"
        profile_action = "tighten_not_loosen"
    elif missed_fill and not risk_issues:
        recommendation = "continue_mode_a"
        profile_action = "review_conservative_candidate"
    elif missed_opp >= 5 and not missed_fill:
        recommendation = "continue_mode_a"
        profile_action = "keep_baseline"
    elif risk_issues:
        recommendation = "review_before_continue"
        profile_action = "keep_baseline"
    else:
        recommendation = "continue_mode_a"
        profile_action = "keep_baseline"
    mode_b_possible = d3_clean and not risk_issues and not runtime_issues and not blockers
    mode_b_action = "prepare_mode_b_after_explicit_ack" if mode_b_possible else "keep_mode_b_blocked"
    allowed = ["continue_mode_a", "keep_baseline"]
    if profile_action == "review_conservative_candidate":
        allowed.append("review_conservative_profile")
    if mode_b_possible:
        allowed.append("prepare_mode_b")
    blocked = ["activate_mode_b_automatically", "activate_profile_without_hash_ack", "enable_learning_to_execution_bridge"]
    if profile_action == "no_profile_activation":
        blocked.append("activate_any_profile")
    return {
        "phase": "autonomous_run_next_steps_v1",
        "generated_at": now_iso(),
        "allowed_next_steps": allowed,
        "blocked_next_steps": blocked,
        "recommendation": recommendation,
        "blockers": blockers,
        "profile_action": profile_action,
        "mode_b_action": mode_b_action,
        "required_ack_if_any": "MODE_B_AND_PROFILE_CHANGES_REQUIRE_SEPARATE_EXACT_ACK" if mode_b_possible or "review_conservative" in profile_action else "",
        "human_summary": (
            "Stop and fix runtime/lifecycle evidence before parameter changes."
            if blockers or runtime_issues
            else "Review the conservative profile because missed-fill evidence exists without risk errors."
            if profile_action == "review_conservative_candidate"
            else "Continue Mode A on the current baseline; evidence is not strong enough to loosen."
        ),
        "diagnostics": {
            "bot_too_strict": bool(missed_fill or missed_opp),
            "bot_too_loose": bool(false_positive or summary.get("blocked_actions")),
            "missed_fills": missed_fill,
            "stale_targets": int(summary.get("stale_tp_signals") or 0),
            "duplicate_or_oversell_attempts": int(len((run.get("open_orders_summary") or {}).get("duplicate_open_d3_exit_positions") or [])),
            "llm_provider_errors": int(summary.get("llm_provider_errors") or 0),
            "atomic_cycle_process_issues": int(summary.get("errors") or 0)
            + int(summary.get("duplicate_cycle_evidence") or 0)
            + int(summary.get("atomic_write_errors") or 0),
            "d3_lifecycle_clean": d3_clean,
            "risk_issues": risk_issues,
            "runtime_issues": runtime_issues,
        },
        "profile_hashes": {k: v.get("hash") for k, v in (profile.get("profiles") or {}).items() if isinstance(v, dict)},
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize evidence-driven autonomous run next steps.")
    parser.add_argument("--run-report", required=True)
    parser.add_argument("--balanced-profile", required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_next_steps_summary(run_report=args.run_report, balanced_profile=args.balanced_profile)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"recommendation={report['recommendation']} profile_action={report['profile_action']} mode_b_action={report['mode_b_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_next_steps_summary", "main", "parse_args"]
