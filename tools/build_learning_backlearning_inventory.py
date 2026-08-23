#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text


JSON_OUT = Path("reports/live_learning/learning_backlearning_inventory_latest.json")
MD_OUT = Path("docs/LEARNING_BACKLEARNING_INVENTORY.md")


COMPONENTS = [
    ("trade_reflection", ["bot/trade_reflection.py", "logs/trade_reflections.jsonl", "state/trade_reflections.jsonl"]),
    ("decision_outcome_tracker", ["bot/decision_outcome_tracker.py", "tools/show_decision_outcomes.py", "state/decision_outcomes.json", "logs/decision_outcomes.jsonl"]),
    ("execution_outcome_tracker", ["bot/execution_outcome_tracker.py", "tools/show_execution_outcomes.py", "logs/execution_outcomes.jsonl"]),
    ("phase_d5_execution_metrics", ["bot/phase_d5_execution_metrics.py", "tools/show_phase_d5_execution_metrics.py"]),
    ("phase_d5_learning_log", ["bot/phase_d5_learning_log.py", "tools/show_phase_d5_learning_log.py", "logs/trade_learning_report.json"]),
    ("phase_d6_backlearning", ["bot/phase_d6_backlearning_scaffold_v4.py", "bot/phase_d6_backlearning_multisource_v11.py", "reports/d6"]),
    ("phase_d6_walk_forward_oos_overfitting", ["bot/phase_d6_walk_forward_splits.py", "bot/phase_d6_oos_degradation.py", "bot/phase_d6_overfitting_guardrails.py"]),
    ("paper_pending_intents", ["bot/pending_order_intents.py", "state/pending_order_intents.json", "logs/pending_order_intents.jsonl"]),
    ("approved_parameter_profile", ["bot/approved_parameter_profile.py", "tools/prepare_approved_parameter_profile_activation.py", "state/approved_parameter_profile.json"]),
    ("balanced_start_profiles", ["tools/propose_balanced_start_parameter_profile.py", "reports/live_learning/balanced-start-profile-candidate.json"]),
    ("live_learning_sidecar", ["tools/build_live_learning_sidecar.py", "reports/live_learning/live-learning-sidecar-latest.json"]),
    ("shadow_parameter_packs", ["bot/phase_shadow_parameter_approximation_pack.py", "tools/build_shadow_parameter_approximation_pack.py", "reports/live_learning/shadow_parameter_pack_latest.json"]),
    ("historical_candle_backtest", ["bot/phase_d6_historical_data_sources.py", "bot/phase_d6_baseline_backtest.py", "bot/phase_d6_cost_aware_split_baseline.py"]),
    ("cost_aware_learning", ["bot/phase_d6_cost_aware_baseline_bundle.py", "bot/phase_d6_cost_aware_split_baseline.py", "tools/run_cost_aware_backlearning.py"]),
    ("live_learning_orchestrator", ["bot/live_learning_orchestrator.py", "reports/live_learning/live-learning-context-latest.json"]),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _exists(root: Path, rel: str) -> bool:
    path = root / rel
    return path.exists()


def _read(root: Path, rel: str) -> str:
    try:
        path = root / rel
        if path.is_file() and path.stat().st_size < 1_000_000:
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def _component(root: Path, name: str, paths: List[str]) -> Dict[str, Any]:
    existing = [p for p in paths if _exists(root, p)]
    text = "\n".join(_read(root, p) for p in paths)
    input_files = [p for p in paths if p.startswith(("state/", "logs/", "reports/")) and _exists(root, p)]
    output_files = [p for p in paths if p.startswith(("state/", "logs/", "reports/"))]
    coinbase_calls = "CoinbaseClient" in text or "coinbase" in text.lower() and "call_attempted" not in text
    llm_calls = "json_response" in text or "OpenAI" in text or "llm" in text.lower()
    runtime_hook = name in {"trade_reflection", "decision_outcome_tracker", "execution_outcome_tracker", "paper_pending_intents", "approved_parameter_profile", "live_learning_orchestrator"}
    used_prompt = name in {"trade_reflection", "decision_outcome_tracker", "paper_pending_intents", "live_learning_orchestrator"}
    used_candidate = name in {"live_learning_sidecar", "balanced_start_profiles", "phase_d6_backlearning", "shadow_parameter_packs", "cost_aware_learning"}
    writes_state = "atomic_write" in text or "write_text" in text or ".append(" in text
    missing: List[str] = []
    if not existing:
        missing.append("component_files_missing")
    if used_candidate and name != "live_learning_orchestrator":
        missing.append("not_centralized_into_runtime_context_before_this_run")
    if name.startswith("phase_d6") or name in {"shadow_parameter_packs", "cost_aware_learning"}:
        missing.append("report_only_research_no_direct_activation")
    risk = "low"
    if coinbase_calls:
        risk = "medium"
    if name == "approved_parameter_profile":
        risk = "medium_ack_gated"
    return {
        "component_name": name,
        "file_paths": paths,
        "current_enabled_status": "present" if existing else "missing",
        "input_files": input_files,
        "output_files": output_files,
        "runtime_hook_present": runtime_hook,
        "used_in_prompt_or_decision_context": used_prompt,
        "used_for_parameter_candidate": used_candidate,
        "writes_state": writes_state,
        "coinbase_calls": coinbase_calls,
        "llm_calls": llm_calls,
        "risk_level": risk,
        "missing_integration": missing,
        "recommended_action": (
            "keep_report_only_and_feed_compact_orchestrator_context"
            if name != "approved_parameter_profile"
            else "use_only_hash_ack_gated_activation"
        ),
    }


def build_inventory(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    rows = [_component(project_root, name, paths) for name, paths in COMPONENTS]
    return {
        "phase": "learning_backlearning_inventory_v1",
        "generated_at": _now_iso(),
        "components": rows,
        "summary": {
            "component_count": len(rows),
            "runtime_hooks": sum(1 for row in rows if row["runtime_hook_present"]),
            "parameter_candidate_components": sum(1 for row in rows if row["used_for_parameter_candidate"]),
            "coinbase_call_components": [row["component_name"] for row in rows if row["coinbase_calls"]],
            "llm_call_components": [row["component_name"] for row in rows if row["llm_calls"]],
        },
        "safety_policy": {
            "direct_learning_flags_required": False,
            "activation_route": "approved_parameter_profile_hash_ack",
            "backlearning_default": "local_report_only",
        },
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = ["# Learning/Backlearning Inventory", "", f"Generated: `{report.get('generated_at')}`", ""]
    lines.append("| Component | Status | Runtime hook | Candidate | Risk | Action |")
    lines.append("|---|---:|---:|---:|---|---|")
    for row in report.get("components", []):
        lines.append(
            f"| {row['component_name']} | {row['current_enabled_status']} | {row['runtime_hook_present']} | "
            f"{row['used_for_parameter_candidate']} | {row['risk_level']} | {row['recommended_action']} |"
        )
    lines.append("")
    lines.append("Direct learning-to-execution flags remain unnecessary; activation is via approved profile hash ACK.")
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build learning/backlearning component inventory.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default=str(JSON_OUT))
    parser.add_argument("--md-out", default=str(MD_OUT))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_inventory(root=args.root)
    atomic_write_json(Path(args.json_out), report)
    atomic_write_text(Path(args.md_out), render_markdown(report))
    print(json.dumps({"status": "inventory_written", "json_out": args.json_out, "md_out": args.md_out}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_inventory", "main", "parse_args", "render_markdown"]
