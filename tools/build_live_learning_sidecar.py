from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DEFAULT_OUTPUT = Path("reports/live_learning/live-learning-sidecar-latest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_jsonl_tail(path: Path, *, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return rows
    for line in lines[-max(0, limit):]:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _latest(root: Path, pattern: str) -> Tuple[Dict[str, Any], str]:
    matches = sorted((root / "reports/d6").glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    if not matches:
        return {}, ""
    path = matches[-1]
    return _load_json(path), str(path)


def _source(path: Path, available: bool, *, records: int = 0) -> Dict[str, Any]:
    return {"path": str(path), "available": bool(available), "records_loaded": int(records)}


def _summarize_decisions(state_payload: Dict[str, Any], report_payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = report_payload.get("summary") if isinstance(report_payload.get("summary"), dict) else {}
    outcomes = state_payload.get("outcomes") if isinstance(state_payload.get("outcomes"), list) else []
    return {
        "state_records": len(outcomes),
        "report_keys": sorted(report_payload.keys()),
        "summary": summary,
        "missed_opportunities_count": len(report_payload.get("missed_opportunities") or []),
        "false_positive_plans_count": len(report_payload.get("false_positive_plans") or []),
        "correct_avoids_count": len(report_payload.get("correct_avoids") or []),
    }


def _summarize_execution(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    labels: Dict[str, int] = {}
    for row in rows:
        for label in row.get("labels") or [row.get("primary_label")]:
            if not label:
                continue
            labels[str(label)] = labels.get(str(label), 0) + 1
    return {
        "records": len(rows),
        "label_counts": labels,
        "recent": rows[-10:],
    }


def _parameter_recommendations(
    *,
    decision_summary: Dict[str, Any],
    execution_summary: Dict[str, Any],
    d5_report: Dict[str, Any],
    d6_metrics: Dict[str, Any],
    d6_shadow_reports: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    recommendations: List[Dict[str, Any]] = []
    missed = int(decision_summary.get("missed_opportunities_count") or 0)
    if missed:
        recommendations.append({
            "parameter_area": "entry_gating_parameters",
            "recommendation": "review_thresholds_human_only",
            "reason": "decision_outcomes_include_missed_opportunities",
            "evidence_count": missed,
            "mutation_allowed": False,
        })
    label_counts = execution_summary.get("label_counts") if isinstance(execution_summary.get("label_counts"), dict) else {}
    no_fill_count = int(label_counts.get("missed_fill_opportunity") or 0)
    if no_fill_count:
        recommendations.append({
            "parameter_area": "orderbook_entry_placement_parameters",
            "recommendation": "review_limit_placement_human_only",
            "reason": "execution_outcomes_include_missed_fill_opportunity",
            "evidence_count": no_fill_count,
            "mutation_allowed": False,
        })
    if d6_metrics.get("warnings"):
        recommendations.append({
            "parameter_area": "d6_metric_quality",
            "recommendation": "do_not_promote_parameters_until_metric_warnings_are_resolved",
            "reason": "d6_metrics_warnings_present",
            "warnings": d6_metrics.get("warnings"),
            "mutation_allowed": False,
        })
    if not d6_shadow_reports:
        recommendations.append({
            "parameter_area": "d6_shadow_parameter_reports",
            "recommendation": "build_or_refresh_shadow_parameter_reports_before_any_profile_proposal",
            "reason": "no_shadow_parameter_reports_loaded",
            "mutation_allowed": False,
        })
    if d5_report:
        recommendations.append({
            "parameter_area": "d5_execution_learning",
            "recommendation": "use_d5_as_review_context_only",
            "reason": "d5_report_available_but_bridge_disabled",
            "mutation_allowed": False,
        })
    return recommendations


def build_live_learning_sidecar_report(*, root: str | Path = ".", generated_at: Optional[str] = None, tail_limit: int = 200) -> Dict[str, Any]:
    project_root = Path(root)
    decision_state_path = project_root / "state/decision_outcomes.json"
    decision_report_path = project_root / "logs/decision_outcome_report.json"
    execution_outcomes_path = project_root / "logs/execution_outcomes.jsonl"
    d5_report_path = project_root / "logs/trade_learning_report.json"

    decision_state = _load_json(decision_state_path)
    decision_report = _load_json(decision_report_path)
    execution_rows = _load_jsonl_tail(execution_outcomes_path, limit=tail_limit)
    d5_report = _load_json(d5_report_path)
    d6_metrics, d6_metrics_path = _latest(project_root, "*metrics*.json")
    d6_shadow_sources: List[Dict[str, Any]] = []
    d6_shadow_reports: List[Dict[str, Any]] = []
    for pattern in ("*shadow*parameter*.json", "*parameter*review*.json", "d6-shadow-learning-report-*.json"):
        payload, path = _latest(project_root, pattern)
        if path:
            d6_shadow_sources.append({"path": path, "available": bool(payload), "phase": payload.get("phase")})
            if payload:
                d6_shadow_reports.append(payload)

    decision_summary = _summarize_decisions(decision_state, decision_report)
    execution_summary = _summarize_execution(execution_rows)
    recommendations = _parameter_recommendations(
        decision_summary=decision_summary,
        execution_summary=execution_summary,
        d5_report=d5_report,
        d6_metrics=d6_metrics,
        d6_shadow_reports=d6_shadow_reports,
    )
    classification = "WATCH" if recommendations else "OK"
    return {
        "phase": "live_learning_sidecar_v1",
        "generated_at": generated_at or _now_iso(),
        "classification": classification,
        "report_only": True,
        "read_only": True,
        "coinbase_call_attempted": False,
        "market_data_fetch_attempted": False,
        "http_call_attempted": False,
        "state_write_performed": False,
        "orders_write_performed": False,
        "runtime_config_write_performed": False,
        "env_write_performed": False,
        "parameter_mutation_performed": False,
        "learning_to_execution_bridge_created": False,
        "learning_to_execution_allowed": False,
        "approved_parameter_profile_written": False,
        "sources": {
            "decision_outcomes_state": _source(decision_state_path, bool(decision_state), records=len(decision_state.get("outcomes") or [])),
            "decision_outcome_report": _source(decision_report_path, bool(decision_report)),
            "execution_outcomes": _source(execution_outcomes_path, bool(execution_rows), records=len(execution_rows)),
            "d5_trade_learning_report": _source(d5_report_path, bool(d5_report)),
            "d6_metrics": {"path": d6_metrics_path, "available": bool(d6_metrics), "phase": d6_metrics.get("phase")},
            "d6_shadow_parameter_reports": d6_shadow_sources,
        },
        "decision_outcomes": decision_summary,
        "execution_outcomes": execution_summary,
        "d5_metrics": d5_report,
        "d6_metrics": d6_metrics,
        "d6_shadow_parameter_reports": d6_shadow_reports,
        "parameter_recommendations": recommendations,
        "governance": {
            "recommendations_are_non_executable": True,
            "requires_separate_profile_file": True,
            "requires_enable_flag": "ENABLE_APPROVED_PARAMETER_PROFILE=true",
            "requires_exact_hash": "APPROVED_PARAMETER_PROFILE_HASH",
            "no_direct_learning_to_execution_bridge": True,
            "no_automatic_parameter_mutation": True,
        },
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    from bot.atomic_io import atomic_write_json

    target = path.resolve()
    allowed = (Path.cwd() / "reports/live_learning").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/live_learning")
    atomic_write_json(target, payload)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only live learning sidecar report. No Coinbase calls and no state/config mutation.")
    parser.add_argument("--json-out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--tail-limit", type=int, default=200)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_live_learning_sidecar_report(tail_limit=args.tail_limit)
    _write_json(Path(args.json_out), report)
    print(json.dumps({"status": "live_learning_sidecar_written", "json_out": args.json_out, "classification": report["classification"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DEFAULT_OUTPUT", "build_live_learning_sidecar_report", "main", "parse_args"]
