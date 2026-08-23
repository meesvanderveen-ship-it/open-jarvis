#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.atomic_io import atomic_write_json
from bot.adaptive_policy_lab import HISTORY_PATH, load_candidate_history


LATEST_JSON = Path("reports/sidecars/reflection-adaptive-sidecar-latest.json")
LATEST_MD = Path("reports/sidecars/reflection-adaptive-sidecar-latest.md")
JSONL_LOG = Path("logs/reflection_adaptive_sidecar.jsonl")

COMMANDS = [
    ("build_reflection_learning_report", ["tools/build_reflection_learning_report.py", "--json"]),
    ("show_reflection_persistence_status", ["tools/show_reflection_persistence_status.py", "--json"]),
    ("build_adaptive_policy_candidate", ["tools/build_adaptive_policy_candidate.py", "--json"]),
    ("analyze_parameter_candidate", ["tools/analyze_parameter_candidate.py", "--json"]),
    ("show_adaptive_policy_lab_status", ["tools/show_adaptive_policy_lab_status.py", "--json"]),
    ("show_autonomous_parameter_governor_status", ["tools/show_autonomous_parameter_governor_status.py", "--json"]),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_from_stdout(stdout: str) -> Dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_command(name: str, args: Sequence[str], *, root: Path) -> Dict[str, Any]:
    started = time.monotonic()
    cmd = [sys.executable, *args, "--root", str(root)]
    result = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    payload = _json_from_stdout(result.stdout)
    return {
        "name": name,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "duration_sec": round(time.monotonic() - started, 3),
        "summary": _summary_for(name, payload),
        "stderr_tail": result.stderr[-1000:],
    }


def _summary_for(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if name == "build_reflection_learning_report":
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        return {
            "available": payload.get("available"),
            "total_events": summary.get("total_events") or len(payload.get("evaluations") or []),
            "validated_conclusions": summary.get("validated_conclusions"),
        }
    if name == "show_reflection_persistence_status":
        return {
            "total_events": payload.get("total_events"),
            "validated_conclusions": payload.get("validated_conclusions"),
            "corrupt_lines": payload.get("corrupt_lines"),
        }
    if name in {"build_adaptive_policy_candidate", "analyze_parameter_candidate", "show_adaptive_policy_lab_status"}:
        return {
            "candidate_available": payload.get("candidate_available"),
            "reason": payload.get("reason"),
            "recommendation": payload.get("recommendation"),
            "market_regimes": (payload.get("evidence_summary") or {}).get("market_regimes") or payload.get("market_regimes"),
        }
    if name == "show_autonomous_parameter_governor_status":
        return {
            "enabled": payload.get("enabled"),
            "mode": payload.get("mode"),
            "governor_activation_allowed": payload.get("governor_activation_allowed"),
            "reason": payload.get("reason"),
        }
    return {}


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def build_sidecar_summary(*, root: Path = Path("."), commands: Optional[Sequence[tuple[str, Sequence[str]]]] = None) -> Dict[str, Any]:
    command_results: List[Dict[str, Any]] = []
    status = "completed"
    for name, args in list(commands or COMMANDS):
        result = _run_command(name, args, root=root)
        command_results.append(result)
        if not result["ok"]:
            status = "failed"
            break

    reflection = _load_json(root / "reports/reflection/reflection-learning-latest.json")
    reflection_status = _load_json(root / "reports/reflection/persistence-status-latest.json")
    candidate = _load_json(root / "reports/adaptive_policy/adaptive-policy-candidate-latest.json")
    analysis = _load_json(root / "reports/adaptive_policy/analysis/parameter-candidate-analysis-latest.json")
    governor = _load_json(root / "reports/autonomous_parameter_governor/governor-status-latest.json")
    reflection_summary = reflection.get("summary") if isinstance(reflection.get("summary"), dict) else {}
    command_summary_by_name = {
        str(item.get("name")): item.get("summary") if isinstance(item.get("summary"), dict) else {}
        for item in command_results
    }
    persistence_command_summary = command_summary_by_name.get("show_reflection_persistence_status") or {}
    evidence = candidate.get("evidence_summary") if isinstance(candidate.get("evidence_summary"), dict) else {}
    history_rows = load_candidate_history(root)
    analysis_items = analysis.get("parameter_analysis") if isinstance(analysis.get("parameter_analysis"), list) else []
    first_analysis = next((item for item in analysis_items if isinstance(item, dict)), {})
    direction_history = first_analysis.get("direction_history") if isinstance(first_analysis.get("direction_history"), dict) else {}
    first_gates = first_analysis.get("statistical_gates") if isinstance(first_analysis.get("statistical_gates"), dict) else {}
    direction_stability = first_gates.get("direction_stability_gate") if isinstance(first_gates.get("direction_stability_gate"), dict) else {}
    return {
        "generated_at": now_iso(),
        "status": status,
        "commands": command_results,
        "reflection": {
            "validated_conclusions": persistence_command_summary.get("validated_conclusions") or reflection_status.get("validated_conclusions") or reflection_summary.get("validated_conclusions") or 0,
            "total_events": persistence_command_summary.get("total_events") or reflection_status.get("total_events") or reflection_summary.get("total_events") or len(reflection.get("evaluations") or []),
            "corrupt_lines": persistence_command_summary.get("corrupt_lines") or reflection_status.get("corrupt_lines") or 0,
        },
        "adaptive": {
            "candidate_available": bool(candidate.get("candidate_available") or analysis.get("candidate_available")),
            "reason": candidate.get("reason") or analysis.get("reason") or "",
            "recommendation": candidate.get("recommendation") or analysis.get("recommendation") or "collect_more_data",
            "market_regimes": evidence.get("market_regimes") or [],
            "candidate_history_path": str(root / HISTORY_PATH),
            "sidecar_runs_seen": len(history_rows),
            "direction_history": {
                "history_items_available": direction_history.get("history_items_available", len(history_rows)),
                "last_3_direction_entries": direction_history.get("last_3_direction_entries", []),
                "sidecar_runs_seen": direction_history.get("sidecar_runs_seen", len(history_rows)),
                "candidate_history_path": direction_history.get("candidate_history_path", str(root / HISTORY_PATH)),
            },
            "direction_stability": {
                "history_items_available": direction_stability.get("history_items_available", direction_history.get("history_items_available", len(history_rows))),
                "matched_scope_key": direction_stability.get("matched_scope_key", direction_history.get("matched_scope_key", "")),
                "match_strategy": direction_stability.get("match_strategy", direction_history.get("match_strategy", "not_found")),
                "observed_runs": direction_stability.get("observed_runs", direction_history.get("observed_runs", 0)),
                "required_runs": direction_stability.get("required_runs", direction_history.get("required_runs", 0)),
                "stability_reason": direction_stability.get("stability_reason", direction_history.get("stability_reason", "")),
            },
        },
        "governor": {
            "enabled": bool(governor.get("enabled")),
            "mode": governor.get("mode") or "report_only",
            "governor_activation_allowed": bool(governor.get("governor_activation_allowed")),
            "reason": governor.get("reason") or "candidate_not_available",
        },
        "safety": {
            "service_lifecycle_performed": False,
            "coinbase_action_performed": False,
            "env_mutation_performed": False,
            "production_order_state_mutation_performed": False,
            "approved_profile_live_mutation_performed": False,
        },
    }


def render_markdown(summary: Dict[str, Any]) -> str:
    adaptive = summary.get("adaptive") or {}
    governor = summary.get("governor") or {}
    direction_stability = adaptive.get("direction_stability") or {}
    lines = [
        "# Reflection Adaptive Sidecar",
        "",
        f"Generated: {summary.get('generated_at')}",
        f"Status: {summary.get('status')}",
        "",
        "## Adaptive",
        f"- candidate_available: {adaptive.get('candidate_available')}",
        f"- recommendation: {adaptive.get('recommendation')}",
        f"- reason: {adaptive.get('reason')}",
        f"- market_regimes: {', '.join(adaptive.get('market_regimes') or []) or 'none'}",
        f"- candidate_history_path: {adaptive.get('candidate_history_path')}",
        f"- sidecar_runs_seen: {adaptive.get('sidecar_runs_seen')}",
        "- direction_stability:",
        f"  - history_items_available: {direction_stability.get('history_items_available')}",
        f"  - matched_scope_key: {direction_stability.get('matched_scope_key') or 'none'}",
        f"  - match_strategy: {direction_stability.get('match_strategy')}",
        f"  - observed_runs: {direction_stability.get('observed_runs')}/{direction_stability.get('required_runs')}",
        f"  - stability_reason: {direction_stability.get('stability_reason')}",
        "",
        "## Governor",
        f"- enabled: {governor.get('enabled')}",
        f"- mode: {governor.get('mode')}",
        f"- governor_activation_allowed: {governor.get('governor_activation_allowed')}",
        f"- reason: {governor.get('reason')}",
        "",
        "## Safety",
        "- report-only",
        "- no service lifecycle",
        "- no Coinbase actions",
        "- no .env mutation",
        "- no production order-state mutation",
        "- no approved profile live mutation",
    ]
    return "\n".join(lines) + "\n"


def write_sidecar_outputs(summary: Dict[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    json_path = root / LATEST_JSON
    md_path = root / LATEST_MD
    log_path = root / JSONL_LOG
    atomic_write_json(json_path, summary)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    return {"json": str(json_path), "markdown": str(md_path), "jsonl_log": str(log_path)}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run report-only reflection/adaptive/governor sidecar.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root)
    summary = build_sidecar_summary(root=root)
    summary["outputs"] = write_sidecar_outputs(summary, root=root)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"reflection_adaptive_sidecar status={summary['status']} candidate_available={summary['adaptive']['candidate_available']} governor_allowed={summary['governor']['governor_activation_allowed']}")
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["COMMANDS", "build_sidecar_summary", "main", "parse_args", "render_markdown", "write_sidecar_outputs"]
