from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.approved_parameter_profile import load_approved_parameter_profile
from bot.atomic_io import atomic_write_json


DEFAULT_CONTEXT_PATH = Path("reports/live_learning/live-learning-context-latest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload


def _load_jsonl_tail(path: Path, *, limit: int) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-max(0, limit):]:
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _latest(root: Path, patterns: Iterable[str]) -> Tuple[Dict[str, Any], str]:
    matches: List[Path] = []
    for pattern in patterns:
        matches.extend((root / "reports/d6").glob(pattern))
        matches.extend((root / "reports/live_learning").glob(pattern))
    matches = sorted(set(matches), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    if not matches:
        return {}, ""
    path = matches[-1]
    payload = _load_json(path)
    return (payload if isinstance(payload, dict) else {}), str(path)


def _compact_strings(values: Iterable[Any], *, limit: int = 5) -> List[str]:
    out: List[str] = []
    for value in values:
        if isinstance(value, dict):
            text = (
                value.get("lesson")
                or value.get("reason")
                or value.get("pattern")
                or value.get("label")
                or value.get("ticker")
                or json.dumps(value, sort_keys=True, default=str)
            )
        else:
            text = value
        text = str(text or "").strip()
        if text and text not in out:
            out.append(text[:220])
        if len(out) >= limit:
            break
    return out


def _reflection_lessons(rows: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    avoid: List[Any] = []
    prefer: List[Any] = []
    for row in reversed(rows):
        payload = row.get("reflection") if isinstance(row.get("reflection"), dict) else row
        avoid.extend(payload.get("avoid_conditions") or payload.get("avoid_lessons") or [])
        prefer.extend(payload.get("prefer_conditions") or payload.get("prefer_lessons") or [])
        if payload.get("lesson"):
            outcome = str(payload.get("outcome") or "").lower()
            (prefer if "win" in outcome or "good" in outcome else avoid).append(payload.get("lesson"))
    return _compact_strings(avoid), _compact_strings(prefer)


def _decision_patterns(state_payload: Any, log_rows: List[Dict[str, Any]]) -> List[str]:
    rows: List[Any] = []
    if isinstance(state_payload, dict):
        rows.extend(state_payload.get("missed_opportunities") or [])
        rows.extend(state_payload.get("outcomes") or [])
    rows.extend(log_rows)
    patterns = []
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        label = row.get("outcome_label") or row.get("result") or row.get("event") or row.get("ticker")
        if "miss" in str(label).lower() or "opportun" in str(label).lower():
            patterns.append(row.get("reason") or row.get("setup_type") or label)
    return _compact_strings(patterns)


def _execution_labels(rows: List[Dict[str, Any]]) -> List[str]:
    counts: Dict[str, int] = {}
    for row in rows:
        labels = row.get("labels") or [row.get("primary_label")]
        for label in labels:
            if label:
                counts[str(label)] = counts.get(str(label), 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [f"{label}:{count}" for label, count in ranked[:5]]


def _approved_profile_status(root: Path) -> Dict[str, Any]:
    try:
        result = load_approved_parameter_profile(path=root / "state/approved_parameter_profile.json")
        return {
            "status": result.status,
            "path": result.path,
            "hash_valid": result.status == "loaded",
            "actual_hash": result.actual_hash,
            "expected_hash": result.expected_hash,
            "parameters": result.values,
            "reason": result.reason,
        }
    except Exception as exc:
        return {
            "status": "rejected",
            "path": str(root / "state/approved_parameter_profile.json"),
            "hash_valid": False,
            "parameters": {},
            "reason": str(exc),
        }


def build_live_learning_context(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    tail_limit: int = 300,
    write_report: bool = False,
    output_path: str | Path = DEFAULT_CONTEXT_PATH,
) -> Dict[str, Any]:
    project_root = Path(root)
    generated = generated_at or _now_iso()

    reflection_rows = _load_jsonl_tail(project_root / "logs/trade_reflections.jsonl", limit=tail_limit)
    decision_state = _load_json(project_root / "state/decision_outcomes.json")
    decision_rows = _load_jsonl_tail(project_root / "logs/decision_outcomes.jsonl", limit=tail_limit)
    execution_rows = _load_jsonl_tail(project_root / "logs/execution_outcomes.jsonl", limit=tail_limit)
    pending_intents = _load_json(project_root / "state/pending_order_intents.json")
    d5_metrics = _load_json(project_root / "logs/trade_learning_report.json")
    d6_evidence, d6_path = _latest(project_root, ("*backlearning*.json", "*walk*forward*.json", "*oos*.json", "*overfit*.json"))
    sidecar = _load_json(project_root / "reports/live_learning/live-learning-sidecar-latest.json")
    balanced = _load_json(project_root / "reports/live_learning/balanced-start-profile-candidate.json")
    backlearning, backlearning_path = _latest(project_root, ("cost-aware-backlearning-latest.json", "start-parameter-candidates-latest.json"))
    approved = _approved_profile_status(project_root)

    avoid, prefer = _reflection_lessons(reflection_rows)
    suggestions = []
    for source in (sidecar, balanced, backlearning):
        if isinstance(source, dict):
            suggestions.extend(source.get("parameter_recommendations") or [])
            candidates = source.get("candidates") or []
            suggestions.extend(candidates if isinstance(candidates, list) else [])
    compact_suggestions = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        compact_suggestions.append({
            "parameter_area": item.get("parameter_area") or item.get("profile_name") or item.get("parameter"),
            "recommendation": item.get("recommendation") or item.get("reason"),
            "confidence": item.get("confidence"),
            "safe_to_activate_now": bool(item.get("safe_to_activate_now", False)),
            "mutation_allowed": False,
        })
        if len(compact_suggestions) >= 5:
            break

    classification = "WATCH"
    if approved.get("status") == "loaded":
        classification = "APPROVED"
    elif backlearning and (backlearning.get("safe_to_activate_now") or backlearning.get("candidates")):
        classification = "READY"

    runtime_context = {
        "classification": classification,
        "top_avoid_lessons": avoid[:5],
        "top_prefer_lessons": prefer[:5],
        "top_missed_opportunity_patterns": _decision_patterns(decision_state, decision_rows)[:5],
        "top_poor_execution_labels": _execution_labels(execution_rows)[:5],
        "top_parameter_suggestions": compact_suggestions[:5],
        "current_approved_profile_summary": {
            "status": approved.get("status"),
            "hash_valid": approved.get("hash_valid"),
            "hash": approved.get("actual_hash") or approved.get("expected_hash") or "",
            "parameters": approved.get("parameters") or {},
        },
        "safety_policy": {
            "soft_context_only": True,
            "parameter_mutation_allowed": False,
            "orders_allowed": False,
            "fail_open_for_analysis_context": True,
            "fail_closed_for_parameter_activation": True,
        },
    }

    report = {
        "phase": "live_learning_orchestrator_context_v1",
        "generated_at": generated,
        "classification": classification,
        "runtime_context": runtime_context,
        "sources": {
            "trade_reflections": {"path": "logs/trade_reflections.jsonl", "records_loaded": len(reflection_rows)},
            "decision_outcomes_state": {"path": "state/decision_outcomes.json", "available": bool(decision_state)},
            "decision_outcomes_log": {"path": "logs/decision_outcomes.jsonl", "records_loaded": len(decision_rows)},
            "execution_outcomes": {"path": "logs/execution_outcomes.jsonl", "records_loaded": len(execution_rows)},
            "paper_pending_intents": {"path": "state/pending_order_intents.json", "available": bool(pending_intents)},
            "d5_execution_metrics": {"path": "logs/trade_learning_report.json", "available": bool(d5_metrics)},
            "d6_backlearning_evidence": {"path": d6_path, "available": bool(d6_evidence)},
            "sidecar": {"path": "reports/live_learning/live-learning-sidecar-latest.json", "available": bool(sidecar)},
            "balanced_profile_candidate": {"path": "reports/live_learning/balanced-start-profile-candidate.json", "available": bool(balanced)},
            "cost_aware_backlearning": {"path": backlearning_path, "available": bool(backlearning)},
            "approved_parameter_profile": approved,
        },
        "report_only": True,
        "read_only": True,
        "coinbase_call_attempted": False,
        "llm_call_attempted": False,
        "parameter_mutation_performed": False,
        "order_submit_attempted": False,
        "state_write_performed": False,
    }
    if write_report:
        atomic_write_json(Path(output_path), report)
        report["state_write_performed"] = False
        report["report_write_performed"] = True
    return report


def run_live_learning_maintenance(
    *,
    root: str | Path = ".",
    output_path: str | Path = DEFAULT_CONTEXT_PATH,
    tail_limit: int = 300,
) -> Dict[str, Any]:
    return build_live_learning_context(root=root, output_path=output_path, tail_limit=tail_limit, write_report=True)


def load_runtime_learning_context(*, root: str | Path = ".") -> Dict[str, Any]:
    try:
        report = _load_json(Path(root) / DEFAULT_CONTEXT_PATH)
        runtime = report.get("runtime_context") if isinstance(report, dict) else {}
        if isinstance(runtime, dict):
            return runtime
    except Exception:
        pass
    return {
        "classification": "WATCH",
        "top_avoid_lessons": [],
        "top_prefer_lessons": [],
        "top_missed_opportunity_patterns": [],
        "top_poor_execution_labels": [],
        "top_parameter_suggestions": [],
        "current_approved_profile_summary": {"status": "unavailable", "parameters": {}},
        "safety_policy": {
            "soft_context_only": True,
            "parameter_mutation_allowed": False,
            "orders_allowed": False,
            "fail_open_for_analysis_context": True,
        },
    }


__all__ = [
    "DEFAULT_CONTEXT_PATH",
    "build_live_learning_context",
    "load_runtime_learning_context",
    "run_live_learning_maintenance",
]
