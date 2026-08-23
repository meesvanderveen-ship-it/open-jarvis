from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_parameter_inventory import build_phase_d6_parameter_inventory_report


D6_EVIDENCE_REVIEW_BUNDLE_PHASE = "D6_combined_evidence_review_bundle_v2"


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


def load_report(path: str | Path) -> Dict[str, Any]:
    safe_path = assert_research_path(path)
    loaded = json.loads(safe_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("d6_evidence_review_bundle_requires_json_object_reports")
    return loaded


def _load_many(paths: Optional[Iterable[str | Path]]) -> List[Dict[str, Any]]:
    return [load_report(path) for path in (paths or [])]


def _sum_counts(reports: Iterable[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for report in reports:
        for name, count in (report.get(key) or {}).items():
            counts[str(name)] = counts.get(str(name), 0) + int(count or 0)
    return dict(sorted(counts.items()))


def _warning_counts(reports: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for report in reports:
        for warning in report.get("warnings") or []:
            counts[str(warning)] = counts.get(str(warning), 0) + 1
        for row in report.get("evidence_rows") or report.get("window_rows") or []:
            for warning in row.get("warnings") or []:
                counts[str(warning)] = counts.get(str(warning), 0) + 1
    return dict(sorted(counts.items()))


def _blocker_counts(reports: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for report in reports:
        for blocker in report.get("blockers") or []:
            counts[str(blocker)] = counts.get(str(blocker), 0) + 1
        for row in report.get("evidence_rows") or report.get("window_rows") or []:
            for blocker in row.get("blockers") or []:
                counts[str(blocker)] = counts.get(str(blocker), 0) + 1
    return dict(sorted(counts.items()))


def _review_readiness(*, d5_count: int, regime_count: int, fill_realism_count: int, blockers: Dict[str, int]) -> str:
    if blockers:
        return "blocked_by_quality"
    if d5_count == 0 and regime_count == 0 and fill_realism_count == 0:
        return "insufficient_evidence"
    if d5_count >= 5 and regime_count >= 3 and fill_realism_count >= 3:
        return "ready_for_human_research_review"
    return "exploratory_only"


def build_phase_d6_evidence_review_bundle(
    *,
    d5_evidence_reports: Optional[Iterable[Dict[str, Any]]] = None,
    d5_evidence_paths: Optional[Iterable[str | Path]] = None,
    regime_reports: Optional[Iterable[Dict[str, Any]]] = None,
    regime_report_paths: Optional[Iterable[str | Path]] = None,
    fill_realism_evidence_reports: Optional[Iterable[Dict[str, Any]]] = None,
    fill_realism_evidence_paths: Optional[Iterable[str | Path]] = None,
    parameter_inventory_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    d5_reports = list(d5_evidence_reports or []) + _load_many(d5_evidence_paths)
    regime_report_list = list(regime_reports or []) + _load_many(regime_report_paths)
    fill_realism_reports = list(fill_realism_evidence_reports or []) + _load_many(fill_realism_evidence_paths)
    inventory = parameter_inventory_report or build_phase_d6_parameter_inventory_report()
    all_reports = [inventory, *d5_reports, *regime_report_list, *fill_realism_reports]

    d5_row_count = sum(int(report.get("evidence_row_count") or len(report.get("evidence_rows") or [])) for report in d5_reports)
    regime_window_count = sum(int(report.get("regime_window_count") or len(report.get("window_rows") or [])) for report in regime_report_list)
    fill_realism_row_count = sum(
        int(report.get("evidence_row_count") or len(report.get("evidence_rows") or [])) for report in fill_realism_reports
    )
    warnings = _warning_counts(all_reports)
    blockers = _blocker_counts(all_reports)
    source_summary = {
        "parameter_inventory_present": True,
        "d5_evidence_report_count": len(d5_reports),
        "regime_report_count": len(regime_report_list),
        "fill_realism_evidence_report_count": len(fill_realism_reports),
        "d5_evidence_row_count": d5_row_count,
        "regime_window_count": regime_window_count,
        "fill_realism_evidence_row_count": fill_realism_row_count,
    }
    return {
        "generated_at": now_iso(),
        "phase": D6_EVIDENCE_REVIEW_BUNDLE_PHASE,
        "status": "d6_combined_evidence_review_bundle_ready",
        "source_summary": source_summary,
        "parameter_inventory_summary": {
            "candidate_count": inventory.get("candidate_count"),
            "category_counts": inventory.get("category_counts"),
            "safety_class_counts": inventory.get("safety_class_counts"),
            "parameter_change_allowed": False,
        },
        "d5_evidence_summary": {
            "report_count": len(d5_reports),
            "evidence_row_count": d5_row_count,
            "evidence_category_counts": _sum_counts(d5_reports, "evidence_category_counts"),
            "parameter_category_counts": _sum_counts(d5_reports, "parameter_category_counts"),
            "evidence_strength_counts": _sum_counts(d5_reports, "evidence_strength_counts"),
        },
        "regime_summary": {
            "report_count": len(regime_report_list),
            "regime_window_count": regime_window_count,
            "regime_counts": _sum_counts(regime_report_list, "regime_counts"),
            "usable_report_count": sum(1 for report in regime_report_list if report.get("usable_for_future_research") is True),
        },
        "fill_realism_summary": {
            "report_count": len(fill_realism_reports),
            "evidence_row_count": fill_realism_row_count,
            "evidence_category_counts": _sum_counts(fill_realism_reports, "evidence_category_counts"),
            "parameter_category_counts": _sum_counts(fill_realism_reports, "parameter_category_counts"),
            "evidence_strength_counts": _sum_counts(fill_realism_reports, "evidence_strength_counts"),
        },
        "fill_realism_warning_counts": _warning_counts(fill_realism_reports),
        "fill_realism_blocker_counts": _blocker_counts(fill_realism_reports),
        "warning_counts": warnings,
        "blocker_counts": blockers,
        "review_readiness": _review_readiness(
            d5_count=d5_row_count,
            regime_count=regime_window_count,
            fill_realism_count=fill_realism_row_count,
            blockers=blockers,
        ),
        "suggested_next_research_steps": [
            "collect_more_fixture_backed_d5_evidence",
            "run_regime_segmentation_on_cached_research_candles",
            "collect_fill_realism_fixture_evidence",
            "add_post_only_queue_assumption_sensitivity_as_report_only",
            "keep_parameter_review_approval_separate",
        ],
        "prohibited_interpretations": [
            "do_not_infer_parameter_change",
            "do_not_rank_parameters",
            "do_not_generate_live_trading_instruction",
            "do_not_connect_learning_to_execution",
        ],
        "warnings": [
            "combined_evidence_review_bundle_only",
            "not_parameter_review",
            "not_parameter_search",
            "not_optimization",
        ],
        "blockers": sorted(blockers),
        **_safety_flags(),
    }


__all__ = [
    "D6_EVIDENCE_REVIEW_BUNDLE_PHASE",
    "build_phase_d6_evidence_review_bundle",
    "load_report",
]
