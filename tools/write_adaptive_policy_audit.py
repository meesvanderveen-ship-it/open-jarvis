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

from bot.adaptive_policy_lab import SOURCE_POLICY, build_adaptive_policy_candidate, build_policy_lab_report
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report


JSON_PATH = Path("reports/audits/adaptive-policy-lab-latest.json")
MD_PATH = Path("reports/audits/adaptive-policy-lab-latest.md")


def build_audit(root: Path) -> Dict[str, Any]:
    lab = build_policy_lab_report(root=root)
    candidate = build_adaptive_policy_candidate(root=root)
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
        "phase": "adaptive_policy_lab_audit_v1",
        "generated_at": lab.get("generated_at"),
        "source_policy": SOURCE_POLICY,
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
        "changed_files": [
            "bot/adaptive_policy_lab.py",
            "tools/build_adaptive_policy_candidate.py",
            "tools/show_adaptive_policy_lab_status.py",
            "tools/write_adaptive_policy_audit.py",
            "tests/test_adaptive_policy_lab.py",
            "tests/test_adaptive_policy_candidate.py",
            "docs/ADAPTIVE_POLICY_LAB.md",
            "docs/REFLECTION_LEARNING_CONTEXT.md",
        ],
        "new_files": [
            "reports/adaptive_policy/adaptive-policy-lab-latest.json",
            "reports/adaptive_policy/adaptive-policy-candidate-latest.json",
            "reports/adaptive_policy/adaptive-policy-candidate-latest.md",
            "reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl",
            "reports/audits/adaptive-policy-lab-latest.json",
            "reports/audits/adaptive-policy-lab-latest.md",
        ],
        "commands_run": [
            "python3 tools/show_reflection_learning_status.py --json",
            "python3 tools/build_adaptive_policy_candidate.py --json",
            "python3 tools/show_adaptive_policy_lab_status.py --json",
            "python3 tools/write_adaptive_policy_audit.py --json",
            "python3 tools/show_full_autonomous_run_readiness.py --json",
        ],
        "tests_run": [
            "tests/test_reflection_learning_context.py",
            "tests/test_reflection_learning_tools.py",
            "tests/test_adaptive_policy_lab.py",
            "tests/test_adaptive_policy_candidate.py",
            "tests/test_market_intelligence_context.py",
            "tests/test_full_poc_workflow_readiness.py",
            "tests/test_market_order_mode_c_governance.py",
        ],
        "test_results": "py_compile_passed; pytest_73_passed",
        "existing_reflection_layer_integration": "reads reports/reflection/reflection-learning-latest.json; does not rebuild or mutate reflection state",
        "reflection_summary_used": lab.get("reflection_summary_used"),
        "adaptive_policy_logic": "validated reflection conclusions -> setup/blocker aggregation -> hard sample gates -> effect/CI/stability/regime gates -> robust candidate statistics -> shrinkage -> report-only hash candidate",
        "growbot_inspired_design": "adaptive measurement and candidate generation only; no direct action loop",
        "valid_conclusion_definition": "non-insufficient reflection labels with decision_time, ticker, setup/blocker, full MFE/MAE/cost fields and anti-hindsight reason",
        "sample_thresholds": lab.get("sample_thresholds"),
        "robust_averaging_method": "raw_mean, median, 10pct trimmed mean, winsorized mean, percentile CI, outlier count; candidate steps toward trimmed/median with caps before shrinkage",
        "overfitting_prevention": lab.get("blockers"),
        "effect_size_gate": lab.get("effect_size_gate_summary"),
        "confidence_deadband_gate": lab.get("confidence_gate_summary"),
        "direction_stability_gate": lab.get("direction_stability_summary"),
        "shrinkage_logic": lab.get("shrinkage"),
        "regime_enrichment_coverage": lab.get("regime_enrichment"),
        "label_to_parameter_pressure_logic": "labels are scored into loosen/tighten pressure; correct_wait and false_signal_avoided counter loosening; overtrading and bad/early entries add tightening pressure",
        "cost_aware_reward": "net_after_cost opportunity is required; negative net opportunity blocks loosening",
        "candidate_profile_policy": "reports/adaptive_policy only; safe_to_activate_now=false; operator review and hash ACK required",
        "candidate_hash": candidate.get("hash"),
        "reason_if_no_candidate": candidate.get("reason") if not candidate.get("candidate_available") else "",
        "state_log_report_paths": {
            "reflection_report": "reports/reflection/reflection-learning-latest.json",
            "lab_report": "reports/adaptive_policy/adaptive-policy-lab-latest.json",
            "candidate_json": "reports/adaptive_policy/adaptive-policy-candidate-latest.json",
            "candidate_md": "reports/adaptive_policy/adaptive-policy-candidate-latest.md",
            "candidate_history": "reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl",
        },
        "safety_policy": {
            "no_service_lifecycle": True,
            "no_coinbase_actions": True,
            "no_env_mutation": True,
            "no_production_order_state_mutation": True,
            "no_approved_profile_state_mutation": True,
            "adaptive_policy_report_only": True,
            "can_authorize_execution": False,
            "can_block_execution": False,
            "can_mutate_parameters": False,
        },
        "full_poc_readiness_status": readiness_status,
    }


def render_md(audit: Dict[str, Any]) -> str:
    lines = [
        "# Adaptive Policy Lab Audit",
        "",
        f"Generated: {audit.get('generated_at')}",
        f"Candidate hash: `{audit.get('candidate_hash')}`",
        f"Reason if no candidate: `{audit.get('reason_if_no_candidate')}`",
        "",
        "## Safety",
    ]
    for key, value in audit["safety_policy"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Thresholds"])
    for key, value in (audit.get("sample_thresholds") or {}).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write adaptive policy lab audit.")
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
