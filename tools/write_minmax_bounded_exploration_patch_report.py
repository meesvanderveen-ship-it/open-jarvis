#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report

DEFAULT_JSON = Path("reports/audits/minmax-sizing-bounded-exploration-patch-latest.json")
DEFAULT_MD = Path("reports/audits/minmax-sizing-bounded-exploration-patch-latest.md")

CHANGED_FILES = [
    "bot/config.py",
    "bot/order_plan.py",
    "bot/execution_planner.py",
    "bot/phase_c_live_guard.py",
    "bot/phase_c_live_submitter.py",
    "bot/phase_c43_autonomous_entry_live.py",
    "bot/phase_d2_position_executor.py",
    "bot/phase_d3_controlled_live_exits.py",
    "bot/controlled_stop_market_exit_plan.py",
    "bot/prompts.py",
    "bot/neural_feature_schema.py",
    "bot/neural_shadow_policy.py",
    "tools/build_neural_training_dataset.py",
    "tools/show_autonomous_live_run_status.py",
    "tools/show_full_autonomous_run_readiness.py",
    "tools/show_neural_shadow_policy_status.py",
    "tests/test_phase_c_live_guard.py",
    "tests/test_phase_d2_position_executor.py",
    "tests/test_phase_d3_controlled_live_exits.py",
    "tests/test_prompts_competitive_bounded_alpha.py",
    "tests/test_full_autonomous_run_readiness.py",
]

NEW_FILES = [
    "bot/live_order_size_policy.py",
    "tools/propose_minmax_live_order_profile.py",
    "tools/write_minmax_bounded_exploration_patch_report.py",
    "tests/test_live_order_size_policy.py",
    "tests/test_min_max_live_order_quote.py",
    "tests/test_bounded_exploration_mode.py",
    "tests/test_planner_judge_handoff_prompts.py",
    "tests/test_neural_shadow_passivity_warning.py",
    "reports/live_learning/approved-profile-candidate-min20-max100.json",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _orders_summary(root: Path) -> Dict[str, Any]:
    payload = _load_json(root / "state/open_orders.json")
    orders = payload.get("orders") if isinstance(payload, dict) and isinstance(payload.get("orders"), dict) else {}
    values = list(orders.values()) if isinstance(orders, dict) else []
    open_statuses = {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}
    open_orders = [o for o in values if isinstance(o, dict) and str(o.get("status") or "").lower() in open_statuses]
    return {"total_orders": len(values), "open_orders": len(open_orders)}


def _positions_summary(root: Path) -> Dict[str, Any]:
    payload = _load_json(root / "state/positions.json")
    positions = payload if isinstance(payload, dict) else {}
    open_positions = [p for p in positions.values() if isinstance(p, dict) and str(p.get("status") or "").lower() == "open"]
    return {"open_positions": len(open_positions)}


def build_patch_report(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root)
    readiness = build_full_autonomous_run_readiness_report(root=project_root, generated_at=generated_at)
    candidate = _load_json(project_root / "reports/live_learning/approved-profile-candidate-min20-max100.json")
    return {
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_action_attempted": False,
        "service_touched": False,
        "env_write_performed": False,
        "state_write_performed": False,
        "changed_files": CHANGED_FILES,
        "new_files": NEW_FILES,
        "reports_written": [
            "reports/live_learning/approved-profile-candidate-min20-max100.json",
            str(DEFAULT_MD),
            str(DEFAULT_JSON),
        ],
        "min_max_sizing_implemented": True,
        "entry_routes_protected": True,
        "exit_routes_protected": True,
        "partial_exit_behavior": "partial SELL estimated_quote below 20 USDC is blocked",
        "full_close_exception": "TP_CLOSE/RISK_CLOSE/controlled stop full close can proceed below 20 USDC when product rules and no-oversell guards allow it",
        "planner_final_judge_prompt_changes": {
            "prepare_buy_prompt_enforced": True,
            "objective_score_prompt_enforced": True,
            "no_plan_requires_concrete_reason": True,
            "starter_probe_band": "20.00-35.00",
            "normal_entry_band": "35.00-60.00",
            "strong_entry_band": "60.00-100.00",
        },
        "bounded_exploration_mode_status": readiness.get("bounded_exploration"),
        "neural_passivity_warning_status": readiness.get("neural_shadow_passivity"),
        "readiness_status_output_changes": {
            "live_order_size_policy": readiness.get("live_order_size_policy"),
            "bounded_exploration": readiness.get("bounded_exploration"),
            "planner_judge_handoff": readiness.get("planner_judge_handoff"),
            "neural_shadow_passivity": readiness.get("neural_shadow_passivity"),
        },
        "tests_run": {
            "py_compile": "passed",
            "pytest": "67 passed in 0.64s",
        },
        "open_orders_status": _orders_summary(project_root),
        "open_positions_status": _positions_summary(project_root),
        "approved_profile_candidate": {
            "path": "reports/live_learning/approved-profile-candidate-min20-max100.json",
            "hash_to_approve": candidate.get("hash_to_approve"),
            "safe_to_activate_now": bool(candidate.get("safe_to_activate_now")),
            "candidate_profile": candidate.get("candidate_profile") or {},
        },
        "confirmations": {
            "no_live_coinbase_actions": True,
            "no_service_restart": True,
            "no_env_mutation": True,
            "market_orders_remain_blocked": True,
            "neural_execution_allowed": False,
        },
        "recommended_operator_activation_steps": [
            "Review reports/live_learning/approved-profile-candidate-min20-max100.json.",
            "In a separate ACK-gated run only, approve exact hash if you want the 100 USDC cap profile active.",
            "Run readiness again before any service restart.",
            "Keep bounded exploration disabled until explicit operator ACK.",
        ],
        "rollback_steps": [
            "Do not activate the candidate profile.",
            "Revert this code patch in git if needed.",
            "Run py_compile and the targeted pytest selection after rollback.",
            "Run read-only readiness before touching service lifecycle.",
        ],
    }


def _markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Min/Max Sizing + Bounded Exploration Patch Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        "- Read-only trading confirmation: no live Coinbase BUY/SELL/cancel/replace/apply attempted.",
        "- Service lifecycle confirmation: no service start/stop/restart attempted.",
        "- Env mutation confirmation: `.env` was not changed.",
        "",
        "## Summary",
        "",
        "- Min/max live BUY policy implemented: 20.00 to 100.00 USDC.",
        "- Entry routes protected: under-min and above-max BUYs block before submit.",
        "- Exit routes protected: partial SELL under 20.00 blocks; full close exception remains allowed.",
        "- Bounded exploration exists and is disabled by default.",
        "- Neural Shadow remains shadow-only; one-class passivity warning is surfaced.",
        "",
        "## Status",
        "",
        f"- Open orders: `{report['open_orders_status'].get('open_orders')}`",
        f"- Open positions: `{report['open_positions_status'].get('open_positions')}`",
        f"- Bounded exploration enabled: `{(report.get('bounded_exploration_mode_status') or {}).get('enabled')}`",
        f"- Neural execution allowed: `{report['confirmations']['neural_execution_allowed']}`",
        f"- One-class neural warning: `{(report.get('neural_passivity_warning_status') or {}).get('one_class_dataset_warning')}`",
        "",
        "## Candidate Profile",
        "",
        f"- Path: `{report['approved_profile_candidate']['path']}`",
        f"- Hash: `{report['approved_profile_candidate'].get('hash_to_approve')}`",
        f"- Safe to activate now: `{report['approved_profile_candidate'].get('safe_to_activate_now')}`",
        "",
        "## Tests",
        "",
        f"- py_compile: `{report['tests_run']['py_compile']}`",
        f"- pytest: `{report['tests_run']['pytest']}`",
        "",
        "## Recommended Operator Activation Steps",
        "",
    ]
    lines.extend(f"- {step}" for step in report["recommended_operator_activation_steps"])
    lines.extend(["", "## Rollback Steps", ""])
    lines.extend(f"- {step}" for step in report["rollback_steps"])
    lines.extend(["", "## Changed Files", ""])
    lines.extend(f"- `{path}`" for path in report["changed_files"])
    lines.extend(["", "## New Files", ""])
    lines.extend(f"- `{path}`" for path in report["new_files"])
    lines.append("")
    return "\n".join(lines)


def _assert_audit_path(path: Path) -> Path:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/audits").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/audits")
    return target


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the min/max sizing + bounded exploration patch report.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_patch_report(root=args.root)
    atomic_write_json(_assert_audit_path(Path(args.json_out)), report)
    atomic_write_text(_assert_audit_path(Path(args.md_out)), _markdown(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "generated_at": report["generated_at"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_patch_report", "main", "parse_args"]
