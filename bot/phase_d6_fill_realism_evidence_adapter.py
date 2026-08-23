from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_fill_realism_assumptions import build_phase_d6_fill_realism_assumption_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_FILL_REALISM_EVIDENCE_ADAPTER_PHASE = "D6_fill_realism_evidence_adapter_v1"

FILL_REALISM_EVIDENCE_CATEGORIES = [
    "post_only_fill_behavior",
    "fill_probability_context",
    "no_fill_duration",
    "cancel_replace_churn",
    "spread_distance_context",
    "tiny_notional_lifecycle_overhead",
    "maker_taker_liquidity",
    "cost_fill_realism_interaction",
]


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


def load_fill_realism_report(path: str | Path) -> Dict[str, Any]:
    safe_path = assert_research_path(path)
    loaded = json.loads(safe_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("d6_fill_realism_evidence_requires_report_object")
    return loaded


def _evidence_id(source_file: str, index: int, row: Dict[str, Any]) -> str:
    basis = json.dumps(
        {
            "source_file": source_file,
            "index": index,
            "product_id": row.get("product_id"),
            "order_label": row.get("order_label"),
            "fill_realism_class": row.get("fill_realism_class"),
        },
        sort_keys=True,
        default=str,
    )
    return "d6fill-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _metric_name(row: Dict[str, Any]) -> str:
    fill_class = str(row.get("fill_realism_class") or "unknown")
    return f"fill_realism_class:{fill_class}"


def _count(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def build_evidence_rows_from_fill_realism_report(
    report: Dict[str, Any],
    *,
    source_file: str = "provided_fill_realism_report",
) -> List[Dict[str, Any]]:
    generated = now_iso()
    rows = []
    for index, row in enumerate(report.get("fill_realism_rows") or []):
        if not isinstance(row, dict):
            continue
        categories = list(row.get("evidence_categories") or [])
        parameter_categories = list(row.get("parameter_categories_implicated") or [])
        rows.append(
            {
                "evidence_id": _evidence_id(source_file, index, row),
                "generated_at": generated,
                "source_type": "d6_fill_realism_assumption_pack",
                "source_file": source_file,
                "event_type": "fill_realism_assumption_observed",
                "ticker": row.get("product_id") or "UNKNOWN",
                "order_label": row.get("order_label"),
                "lifecycle_stage": "research_assumption",
                "outcome_class": row.get("fill_realism_class"),
                "metric_name": _metric_name(row),
                "metric_value": row.get("fill_realism_class"),
                "metric_unit": "class",
                "evidence_categories": categories,
                "parameter_categories_implicated": parameter_categories,
                "parameter_candidates_implicated": _candidate_hints(categories),
                "evidence_strength": row.get("evidence_strength") or "insufficient",
                "warnings": sorted(set((row.get("warnings") or []) + ["fill_realism_evidence_adapter_report_only"])),
                "blockers": list(row.get("blockers") or []),
                "human_review_required": True,
                "parameter_change_allowed": False,
                "parameter_review_approved": False,
            }
        )
    return rows


def _candidate_hints(categories: Iterable[str]) -> List[str]:
    mapping = {
        "post_only_fill_behavior": ["post_only_crossing_guard", "post_only_fill_behavior"],
        "fill_probability_context": ["no_fill_duration_thresholds", "refresh_tolerance"],
        "no_fill_duration": ["stale_order_age_threshold", "no_fill_duration_thresholds"],
        "cancel_replace_churn": ["cancel_replace_trigger", "cooldown_after_failed_replace"],
        "spread_distance_context": ["spread_filters", "minimum_liquidity_conditions"],
        "tiny_notional_lifecycle_overhead": ["min_base_quote_handling", "small_position_fallback"],
        "maker_taker_liquidity": ["minimum_liquidity_conditions", "post_only_crossing_guard"],
        "cost_fill_realism_interaction": ["fee_spread_slippage_buffer", "minimum_expected_net_edge"],
    }
    out: set[str] = set()
    for category in categories:
        out.update(mapping.get(category, []))
    return sorted(out)


def build_phase_d6_fill_realism_evidence_report(
    *,
    fill_realism_reports: Iterable[Dict[str, Any]] | None = None,
    fill_realism_report_paths: Iterable[str | Path] | None = None,
    input_paths: Iterable[str | Path] | None = None,
    maker_fee_pct: Any = "0.004",
) -> Dict[str, Any]:
    reports = list(fill_realism_reports or [])
    source_summary = []
    for path in fill_realism_report_paths or []:
        safe_path = assert_research_path(path)
        report = load_fill_realism_report(safe_path)
        reports.append(report)
        source_summary.append({"source_file": str(safe_path), "source_type": "fill_realism_report"})
    if input_paths:
        report = build_phase_d6_fill_realism_assumption_report(input_paths=input_paths, maker_fee_pct=maker_fee_pct)
        reports.append(report)
        source_summary.extend(report.get("source_summary") or [])
    if not reports:
        raise ValueError("d6_fill_realism_evidence_requires_report_or_input_path")

    evidence_rows: List[Dict[str, Any]] = []
    for index, report in enumerate(reports):
        source_file = source_summary[index]["source_file"] if index < len(source_summary) else f"provided_fill_realism_report_{index}"
        evidence_rows.extend(build_evidence_rows_from_fill_realism_report(report, source_file=source_file))
    blockers = sorted({blocker for row in evidence_rows for blocker in row.get("blockers") or []})
    return {
        "generated_at": now_iso(),
        "phase": D6_FILL_REALISM_EVIDENCE_ADAPTER_PHASE,
        "status": "d6_fill_realism_evidence_ready",
        "source_summary": source_summary,
        "evidence_row_count": len(evidence_rows),
        "evidence_rows": evidence_rows,
        "evidence_category_counts": _count(category for row in evidence_rows for category in row.get("evidence_categories") or []),
        "parameter_category_counts": _count(category for row in evidence_rows for category in row.get("parameter_categories_implicated") or []),
        "evidence_strength_counts": _count(row.get("evidence_strength") for row in evidence_rows),
        "warnings": [
            "fill_realism_evidence_adapter_only",
            "not_parameter_review",
            "not_parameter_search",
            "not_optimization",
        ],
        "blockers": blockers,
        **_safety_flags(),
    }


__all__ = [
    "D6_FILL_REALISM_EVIDENCE_ADAPTER_PHASE",
    "FILL_REALISM_EVIDENCE_CATEGORIES",
    "build_evidence_rows_from_fill_realism_report",
    "build_phase_d6_fill_realism_evidence_report",
]
