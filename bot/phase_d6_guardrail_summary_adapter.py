from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_GUARDRAIL_SUMMARY_ADAPTER_PHASE = "D6_guardrail_summary_adapter_v1"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
    }


def load_json_report(path: str | Path) -> Dict[str, Any]:
    safe_path = assert_research_path(path)
    loaded = json.loads(safe_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("d6_guardrail_summary_requires_json_object_report")
    return loaded


def _count(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _report_type(report: Dict[str, Any]) -> str:
    phase = str(report.get("phase") or "").lower()
    if "dataset_quality_aggregate" in phase:
        return "dataset_quality_aggregate"
    if "dataset_quality_report" in phase:
        return "dataset_quality_report"
    if "walk_forward" in phase:
        return "walk_forward_split"
    if "out_of_sample" in phase or "oos" in phase:
        return "oos_degradation"
    if "overfitting" in phase or "trial_accounting" in phase:
        return "overfitting_trial_accounting"
    if "cost" in phase or "fee_slippage" in phase:
        return "cost_assumptions"
    if "fill_realism" in phase:
        return "fill_realism"
    return "generic_guardrail_report"


def _warnings(report: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    warnings.extend(str(item) for item in report.get("warnings") or [])
    warnings.extend(str(item) for item in report.get("guardrail_warnings") or [])
    summary = dict(report.get("summary") or {})
    for key, count in (summary.get("warning_counts") or {}).items():
        if int(count or 0) > 0:
            warnings.append(str(key))
    for key, count in (report.get("warning_counts") or {}).items():
        if int(count or 0) > 0:
            warnings.append(str(key))
    return sorted(set(warnings))


def _blockers(report: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    blockers.extend(str(item) for item in report.get("blockers") or [])
    blockers.extend(str(item) for item in report.get("fatal_errors") or [])
    summary = dict(report.get("summary") or {})
    blockers.extend(str(item) for item in summary.get("blockers") or [])
    for key, count in (report.get("blocker_counts") or {}).items():
        if int(count or 0) > 0:
            blockers.append(str(key))
    return sorted(set(blockers))


def _guardrail_status(report: Dict[str, Any], warnings: List[str], blockers: List[str]) -> str:
    if blockers:
        return "blocked"
    status = str(report.get("status") or "").lower()
    quality = str(report.get("quality_class") or dict(report.get("summary") or {}).get("aggregate_quality_class") or "").lower()
    guardrail_class = str(report.get("guardrail_class") or "").lower()
    if "invalid" in status or quality == "invalid" or "insufficient" in guardrail_class:
        return "blocked"
    if not report:
        return "insufficient"
    if warnings or quality in {"poor", "usable_with_warnings"} or guardrail_class == "exploratory_only":
        return "warning"
    return "pass"


def _categories(report_type: str) -> List[str]:
    mapping = {
        "dataset_quality_report": ["universe_market_selection", "market_data_features"],
        "dataset_quality_aggregate": ["universe_market_selection", "market_data_features"],
        "walk_forward_split": ["entry_signal", "position_sizing_risk", "d2_position_executor"],
        "oos_degradation": ["entry_signal", "position_sizing_risk", "d2_position_executor", "d5_execution_learning"],
        "overfitting_trial_accounting": ["entry_signal", "position_sizing_risk", "ai_prompt_judge"],
        "cost_assumptions": ["d2_position_executor", "position_sizing_risk"],
        "fill_realism": ["d3_controlled_exit", "d4_dynamic_order_management", "d5_execution_learning"],
    }
    return mapping.get(report_type, ["d5_execution_learning"])


def _strength(status: str, report: Dict[str, Any]) -> str:
    if status == "blocked":
        return "medium"
    if status == "insufficient":
        return "insufficient"
    if report.get("research_only") is True:
        return "medium" if status == "warning" else "weak"
    return "weak"


def _row_id(source_file: str, report: Dict[str, Any]) -> str:
    basis = json.dumps(
        {"source_file": source_file, "phase": report.get("phase"), "status": report.get("status")},
        sort_keys=True,
        default=str,
    )
    return "d6guard-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def build_guardrail_summary_rows(
    reports: Iterable[Dict[str, Any]],
    *,
    source_files: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    files = list(source_files or [])
    rows: List[Dict[str, Any]] = []
    for index, report in enumerate(reports):
        source_file = files[index] if index < len(files) else f"provided_guardrail_report_{index}"
        report_type = _report_type(report)
        warnings = _warnings(report)
        blockers = _blockers(report)
        status = _guardrail_status(report, warnings, blockers)
        rows.append(
            {
                "guardrail_id": _row_id(source_file, report),
                "source_file": source_file,
                "report_phase": report.get("phase"),
                "report_status": report.get("status"),
                "guardrail_type": report_type,
                "guardrail_status": status,
                "warning_count": len(warnings),
                "blocker_count": len(blockers),
                "warnings": warnings,
                "blockers": blockers,
                "implicated_parameter_categories": _categories(report_type),
                "evidence_strength": _strength(status, report),
                "human_review_required": True,
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
            }
        )
    return rows


def build_phase_d6_guardrail_summary_report(
    *,
    report_paths: Optional[Iterable[str | Path]] = None,
    reports: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    loaded_reports = list(reports or [])
    source_files = [f"provided_guardrail_report_{index}" for index, _ in enumerate(loaded_reports)]
    for raw_path in report_paths or []:
        path = assert_research_path(raw_path)
        loaded_reports.append(load_json_report(path))
        source_files.append(str(path))
    if not loaded_reports:
        raise ValueError("d6_guardrail_summary_requires_at_least_one_report")
    rows = build_guardrail_summary_rows(loaded_reports, source_files=source_files)
    return {
        "generated_at": now_iso(),
        "phase": D6_GUARDRAIL_SUMMARY_ADAPTER_PHASE,
        "status": "d6_guardrail_summary_ready",
        "source_summary": {
            "report_count": len(loaded_reports),
            "report_types": sorted({row["guardrail_type"] for row in rows}),
        },
        "guardrail_summary_rows": rows,
        "guardrail_status_counts": _count(row["guardrail_status"] for row in rows),
        "warning_counts": _count(warning for row in rows for warning in row.get("warnings") or []),
        "blocker_counts": _count(blocker for row in rows for blocker in row.get("blockers") or []),
        "implicated_parameter_category_counts": _count(
            category for row in rows for category in row.get("implicated_parameter_categories") or []
        ),
        "warnings": [
            "guardrail_summary_adapter_only",
            "not_parameter_review_approval",
            "not_parameter_search",
            "not_optimization",
        ],
        "blockers": sorted({blocker for row in rows for blocker in row.get("blockers") or []}),
        **_safety_flags(),
    }


__all__ = [
    "D6_GUARDRAIL_SUMMARY_ADAPTER_PHASE",
    "build_guardrail_summary_rows",
    "build_phase_d6_guardrail_summary_report",
    "load_json_report",
]
