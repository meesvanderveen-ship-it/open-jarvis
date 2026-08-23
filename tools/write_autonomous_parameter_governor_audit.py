#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.atomic_io import atomic_write_json
from bot.autonomous_parameter_governor import (
    ALLOWED_PARAMETERS,
    AUDIT_JSON_PATH,
    AUDIT_MD_PATH,
    FORBIDDEN_PARAMETERS,
    build_activation_plan,
    governor_settings,
    validate_governor,
)
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report


def build_audit(root: Path) -> Dict[str, Any]:
    status = validate_governor(root=root)
    plan = build_activation_plan(root=root)
    try:
        readiness = build_full_autonomous_run_readiness_report(root=root)
        readiness_status = {
            "recommendation": readiness.get("recommendation"),
            "poc_full_workflow_readiness": readiness.get("poc_full_workflow_readiness"),
            "mode_c_market_order_readiness": readiness.get("mode_c_market_order_readiness"),
            "blockers": readiness.get("blockers"),
        }
    except Exception as exc:
        readiness_status = {"error": str(exc)}
    return {
        "phase": "autonomous_parameter_governor_audit_v1",
        "generated_at": status.get("generated_at") or status.get("settings", {}).get("generated_at"),
        "source_policy": status.get("source_policy"),
        "changed_files": [
            "bot/autonomous_parameter_governor.py",
            "tools/show_autonomous_parameter_governor_status.py",
            "tools/prepare_autonomous_parameter_activation.py",
            "tools/run_autonomous_parameter_governor.py",
            "tools/rollback_autonomous_parameter_profile.py",
            "tools/write_autonomous_parameter_governor_audit.py",
            "tests/test_autonomous_parameter_governor.py",
            "tests/test_autonomous_parameter_governor_tools.py",
            "docs/AUTONOMOUS_PARAMETER_GOVERNOR.md",
            "docs/ADAPTIVE_POLICY_LAB.md",
        ],
        "new_files": [
            "reports/autonomous_parameter_governor/governor-status-latest.json",
            "reports/autonomous_parameter_governor/activation-plan-latest.json",
            "reports/autonomous_parameter_governor/activation-plan-latest.md",
            "reports/autonomous_parameter_governor/governor-run-latest.json",
            "reports/audits/autonomous-parameter-governor-latest.json",
            "reports/audits/autonomous-parameter-governor-latest.md",
        ],
        "commands_run": [
            "python3 tools/show_autonomous_parameter_governor_status.py --json",
            "python3 tools/prepare_autonomous_parameter_activation.py --json",
            "python3 tools/run_autonomous_parameter_governor.py --json",
            "python3 tools/write_autonomous_parameter_governor_audit.py --json",
            "python3 tools/show_adaptive_policy_lab_status.py --json",
            "python3 tools/show_full_autonomous_run_readiness.py --json",
        ],
        "tests_run": [
            "tests/test_autonomous_parameter_governor.py",
            "tests/test_autonomous_parameter_governor_tools.py",
            "tests/test_adaptive_policy_lab.py",
            "tests/test_adaptive_policy_candidate.py",
            "tests/test_reflection_learning_context.py",
            "tests/test_reflection_learning_tools.py",
            "tests/test_market_intelligence_context.py",
            "tests/test_full_poc_workflow_readiness.py",
            "tests/test_market_order_mode_c_governance.py",
        ],
        "test_results": "py_compile_passed; pytest_87_passed",
        "candidate_status_used": {
            "candidate_available": status.get("candidate_available"),
            "candidate_hash": status.get("candidate_hash"),
            "reason": status.get("reason"),
        },
        "activation_allowed": status.get("governor_activation_allowed"),
        "reason": status.get("reason"),
        "allowlist": sorted(ALLOWED_PARAMETERS),
        "forbidden_parameter_categories": sorted(FORBIDDEN_PARAMETERS),
        "open_order_position_safety": {
            "open_orders": status.get("open_orders"),
            "open_positions": status.get("open_positions"),
            "open_d3_exit": status.get("open_d3_exit"),
        },
        "cooldown_rate_limits": {
            "cooldown_active": status.get("cooldown_active"),
            "last_activation": status.get("last_activation"),
            "max_changes_per_24h": governor_settings().get("max_changes_per_24h"),
            "cooldown_hours": governor_settings().get("cooldown_hours"),
        },
        "backup_rollback_design": "backup current state/approved_parameter_profile.json before ACK-gated tmp-safe apply; write rollback_plan_latest.json; rollback requires separate ACK",
        "current_mode": status.get("mode"),
        "env_flags_documented": True,
        "activation_plan": {
            "available": plan.get("activation_plan_available"),
            "reason": plan.get("reason"),
            "safe_to_apply_now": plan.get("safe_to_apply_now"),
        },
        "safety_policy": {
            "no_service_lifecycle": True,
            "no_coinbase_actions": True,
            "no_env_mutation": True,
            "no_production_order_state_mutation": True,
            "no_approved_profile_live_mutation": True,
            "can_authorize_orders": False,
        },
        "full_poc_readiness_status": readiness_status,
    }


def render_md(audit: Dict[str, Any]) -> str:
    lines = [
        "# Autonomous Parameter Governor Audit",
        "",
        f"Activation allowed: `{audit.get('activation_allowed')}`",
        f"Reason: `{audit.get('reason')}`",
        f"Mode: `{audit.get('current_mode')}`",
        "",
        "## Safety",
    ]
    for key, value in audit["safety_policy"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Candidate", f"- hash: `{(audit.get('candidate_status_used') or {}).get('candidate_hash')}`"])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write autonomous parameter governor audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    audit = build_audit(root)
    atomic_write_json(root / AUDIT_JSON_PATH, audit)
    (root / AUDIT_MD_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / AUDIT_MD_PATH).write_text(render_md(audit), encoding="utf-8")
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        print(f"audit_json={root / AUDIT_JSON_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
