#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST
from bot.atomic_io import atomic_write_json, atomic_write_text


DEFAULT_JSON_OUT = Path("reports/research/learning-parameter-dynamic-capability-latest.json")
DEFAULT_MD_OUT = Path("reports/research/learning-parameter-dynamic-capability-latest.md")
DIRECT_MUTATION_FLAGS = [
    "LEARNING_TO_EXECUTION_ALLOWED",
    "LIVE_LEARNING_ALLOWED",
    "PARAMETER_CHANGE_ALLOWED",
    "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _env_values(root: Path) -> Dict[str, str]:
    text = _read(root / ".env")
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in DIRECT_MUTATION_FLAGS or key in {
            "ENABLE_APPROVED_PARAMETER_PROFILE",
            "APPROVED_PARAMETER_PROFILE_HASH",
            "MARKET_ORDER_ENABLED",
            "ENABLE_MARKET_ORDERS",
            "ALLOW_MARKET_ORDERS",
            "REPLICATION_ENABLED",
            "REPLICATION_LIFECYCLE_ENABLED",
            "REPLICATION_LIFECYCLE_HTTP_ENABLED",
        }:
            out[key] = value.strip()
    return out


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _contains_any(root: Path, rel: str, patterns: Sequence[str]) -> bool:
    text = _read(root / rel)
    return any(re.search(pattern, text) for pattern in patterns)


def build_capability_report(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root)
    env = _env_values(project_root)
    direct_flags_enabled = {key: _enabled(env.get(key, "false")) for key in DIRECT_MUTATION_FLAGS}
    direct_mutation_possible = any(direct_flags_enabled.values())
    sidecar = _load_json(project_root / "reports/live_learning/live-learning-sidecar-latest.json")
    backlearning = _load_json(project_root / "reports/live_learning/cost-aware-backlearning-latest.json")
    if not backlearning:
        matches = sorted((project_root / "reports/live_learning").glob("*backlearning*.json"))
        if matches:
            backlearning = _load_json(matches[-1])
    backtest_candidate = _load_json(project_root / "reports/backtests/approved-profile-candidate-from-backtest.json")

    can_propose = (
        _contains_any(project_root, "tools/build_live_learning_sidecar.py", [r"parameter_recommendations", r"candidate"])
        or _contains_any(project_root, "tools/run_cost_aware_backlearning.py", [r"APPROVED_PARAMETER_PROFILE_WHITELIST", r"safe_to_activate"])
        or bool(sidecar)
        or bool(backlearning)
        or bool(backtest_candidate)
    )
    hash_gate = _contains_any(project_root, "bot/approved_parameter_profile.py", [r"APPROVED_PARAMETER_PROFILE_HASH", r"sha256_file"])
    activation_tool_hash = _contains_any(project_root, "tools/activate_approved_parameter_profile.py", [r"required_ack", r"APPROVED_PARAMETER_PROFILE_HASH"])
    safety_blockers = []
    if direct_mutation_possible:
        safety_blockers.append("direct_live_parameter_mutation_flag_enabled")
    if not hash_gate:
        safety_blockers.append("approved_profile_hash_gate_missing")

    dynamic_candidate_parameters = sorted(APPROVED_PARAMETER_PROFILE_WHITELIST)
    hard_env_parameters = sorted(set(dynamic_candidate_parameters) | {
        "MIN_LIVE_ORDER_QUOTE_USDC",
        "MAX_LIVE_ORDER_QUOTE_USDC",
        "ENABLE_BOUNDED_EXPLORATION_MODE",
        "EXPLORATION_MIN_ORDER_QUOTE_USDC",
        "EXPLORATION_MAX_ORDER_QUOTE_USDC",
        "REPLICATION_ENABLED",
        "MARKET_ORDER_ENABLED",
        "ENABLE_MARKET_ORDERS",
        "ALLOW_MARKET_ORDERS",
    })
    measured_not_applied = [
        "fill_quality",
        "no_fill_rate",
        "missed_opportunity",
        "bad_wait",
        "good_entry_candidate",
        "bad_entry_candidate",
        "orderbook_timing",
        "spread_friction",
    ]

    return {
        "phase": "learning_parameter_dynamic_capability_v1",
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "service_touched": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "learning_can_propose_parameters": bool(can_propose),
        "learning_can_directly_mutate_live_parameters": bool(direct_mutation_possible),
        "approved_profile_exact_hash_required": bool(hash_gate),
        "activation_tool_exact_ack_present": bool(activation_tool_hash),
        "operator_review_required": True,
        "direct_mutation_flags": direct_flags_enabled,
        "safety_blockers": safety_blockers,
        "dynamic_candidate_parameters": dynamic_candidate_parameters,
        "hard_config_or_env_parameters": hard_env_parameters,
        "profile_activation_only_parameters": dynamic_candidate_parameters,
        "measured_but_not_automatically_applied": measured_not_applied,
        "sources": {
            "live_learning_sidecar_available": bool(sidecar),
            "cost_aware_backlearning_available": bool(backlearning),
            "backtest_candidate_available": bool(backtest_candidate),
            "env_relevant_flags": env,
        },
        "desired_outcome_met": bool(can_propose) and not direct_mutation_possible and bool(hash_gate),
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines = [
        "# Learning Parameter Dynamic Capability",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        f"- learning_can_propose_parameters: `{report['learning_can_propose_parameters']}`",
        f"- learning_can_directly_mutate_live_parameters: `{report['learning_can_directly_mutate_live_parameters']}`",
        f"- approved_profile_exact_hash_required: `{report['approved_profile_exact_hash_required']}`",
        f"- operator_review_required: `{report['operator_review_required']}`",
        f"- safety_blockers: `{', '.join(report['safety_blockers']) or 'none'}`",
        "",
        "## Candidateable Parameters",
        "",
    ]
    for key in report["dynamic_candidate_parameters"]:
        lines.append(f"- `{key}`")
    lines.extend([
        "",
        "## Measured But Not Auto-Applied",
        "",
    ])
    for key in report["measured_but_not_automatically_applied"]:
        lines.append(f"- `{key}`")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report learning/backlearning parameter mutation capability.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--md-out", default=str(DEFAULT_MD_OUT))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_capability_report(root=args.root)
    atomic_write_json(Path(args.json_out), report)
    atomic_write_text(Path(args.md_out), _render_md(report))
    print(json.dumps({"json_out": args.json_out, "desired_outcome_met": report["desired_outcome_met"], "safety_blockers": report["safety_blockers"]}, indent=2, sort_keys=True))
    return 0 if not report["safety_blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_capability_report", "main", "parse_args"]
