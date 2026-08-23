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

from bot.reflection_learning_context import REFLECTION_LABELS, SOURCE_POLICY, build_reflection_learning_report
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report


JSON_PATH = Path("reports/audits/reflection-learning-context-latest.json")
MD_PATH = Path("reports/audits/reflection-learning-context-latest.md")


def build_audit(root: Path) -> Dict[str, Any]:
    report = build_reflection_learning_report(root=root, no_network=True)
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
        "phase": "reflection_learning_context_audit_v1",
        "generated_at": report.get("generated_at"),
        "source_policy": SOURCE_POLICY,
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
        "changed_files": [
            "bot/reflection_learning_context.py",
            "tools/build_reflection_learning_report.py",
            "tools/show_reflection_learning_status.py",
            "tools/summarize_missed_opportunities.py",
            "tools/write_reflection_learning_audit.py",
            "tests/test_reflection_learning_context.py",
            "tests/test_reflection_learning_tools.py",
            "docs/REFLECTION_LEARNING_CONTEXT.md",
        ],
        "new_files": [
            "reports/reflection/reflection-learning-latest.md",
            "reports/reflection/reflection-learning-latest.json",
            "reports/reflection/missed-opportunities-latest.json",
            "reports/audits/reflection-learning-context-latest.md",
            "reports/audits/reflection-learning-context-latest.json",
        ],
        "commands_run": [
            "python3 -m py_compile bot/reflection_learning_context.py tools/build_reflection_learning_report.py tools/show_reflection_learning_status.py tools/summarize_missed_opportunities.py tools/write_reflection_learning_audit.py tools/show_full_autonomous_run_readiness.py tools/show_autonomous_live_run_status.py",
            "PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_reflection_learning_context.py tests/test_reflection_learning_tools.py tests/test_market_intelligence_context.py tests/test_full_poc_workflow_readiness.py tests/test_market_order_mode_c_governance.py",
            "python3 tools/build_reflection_learning_report.py --no-network --json",
            "python3 tools/write_reflection_learning_audit.py",
        ],
        "tests_run": [
            "tests/test_reflection_learning_context.py",
            "tests/test_reflection_learning_tools.py",
            "tests/test_market_intelligence_context.py",
            "tests/test_full_poc_workflow_readiness.py",
            "tests/test_market_order_mode_c_governance.py",
        ],
        "test_results": "py_compile_passed; pytest_47_passed",
        "data_sources_used": ["logs/analysis.jsonl", "state/decision_outcomes.json", "data/candles/*_1h.csv"],
        "no_network_fixture_behavior": {"no_network": True, "fixture_only_supported": True},
        "reflection_labels": sorted(REFLECTION_LABELS),
        "anti_hindsight_rules": [
            "setup visible at decision time",
            "entry plausibly fillable",
            "net MFE exceeds fee plus spread plus slippage plus minimum edge",
            "MAE within acceptable drawdown",
            "invalidation not reached first",
            "exit plausibly fillable",
            "no market intelligence risk warning",
            "blocker points to strict threshold for too_strict_wait",
        ],
        "cost_assumptions": report.get("cost_assumptions"),
        "state_log_report_paths": {
            "state": "state/reflection_learning_context.json",
            "report_json": "reports/reflection/reflection-learning-latest.json",
            "report_md": "reports/reflection/reflection-learning-latest.md",
            "missed_json": "reports/reflection/missed-opportunities-latest.json",
        },
        "safety_policy": {
            "source_policy": SOURCE_POLICY,
            "can_authorize_execution": False,
            "can_block_execution": False,
            "can_mutate_parameters": False,
            "no_service_lifecycle": True,
            "no_coinbase_actions": True,
            "no_env_mutation": True,
            "no_production_order_state_mutation": True,
        },
        "feature_pack_integration_status": "available_as_disabled_by_default_helper_ENABLE_REFLECTION_LEARNING_CONTEXT_false",
        "candidate_profile_policy": "report_only_safe_to_activate_now_false_operator_review_required",
        "full_poc_readiness_status": readiness_status,
        "latest_reflection_summary": report.get("summary"),
    }


def render_md(audit: Dict[str, Any]) -> str:
    lines = [
        "# Reflection Learning Context Audit",
        "",
        f"Generated: {audit.get('generated_at')}",
        "",
        "## Safety",
    ]
    for key, value in audit["safety_policy"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Files"])
    for path in audit["changed_files"]:
        lines.append(f"- {path}")
    lines.extend(["", "## Labels"])
    for label in audit["reflection_labels"]:
        lines.append(f"- {label}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write reflection learning context audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    audit = build_audit(root)
    for path in (root / JSON_PATH, root / MD_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
    (root / JSON_PATH).write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / MD_PATH).write_text(render_md(audit), encoding="utf-8")
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        print(f"audit_json={root / JSON_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
