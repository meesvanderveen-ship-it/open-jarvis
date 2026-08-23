from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso, to_decimal


D6_D5_EVIDENCE_ADAPTER_PHASE = "D6_D5_execution_evidence_adapter_v1"

D5_EVIDENCE_CATEGORIES = [
    "fill_quality",
    "no_fill_duration",
    "cancel_replace_outcome",
    "post_only_fill_behavior",
    "maker_taker_liquidity",
    "slippage_fee_realization",
    "reservation_drift",
    "duplicate_or_oversell_incidents",
    "lifecycle_terminal_handling",
    "tiny_notional_lifecycle_overhead",
    "stale_label_or_workflow_confusion",
    "parameter_categories_implicated",
]


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_approved": False,
        "parameter_review_allowed": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
    }


def _load_json_or_jsonl(path: str | Path) -> List[Dict[str, Any]]:
    safe_path = assert_research_path(path)
    text = safe_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if safe_path.suffix.lower() == ".jsonl":
        rows: List[Dict[str, Any]] = []
        for line in text.splitlines():
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        return rows
    loaded = json.loads(text)
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, dict)]
    if isinstance(loaded, dict):
        for key in ("events", "rows", "learning_events", "evidence_rows", "reports"):
            nested = loaded.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [loaded]
    return []


def _first_present(row: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _event_type(row: Dict[str, Any]) -> str:
    return str(_first_present(row, ["event_type", "phase", "status", "lifecycle_branch"]) or "unknown_event")


def _ticker(row: Dict[str, Any]) -> str:
    return str(_first_present(row, ["ticker", "product_id", "product"]) or "UNKNOWN")


def _order_label(row: Dict[str, Any]) -> Optional[str]:
    label = _first_present(row, ["order_label", "label", "exit_label"])
    if label:
        return str(label)
    client_order_id = str(row.get("client_order_id") or "")
    for token in ("TP_CLOSE", "TP1", "TP2", "STOP", "TRAIL"):
        if token.lower().replace("_", "") in client_order_id.lower().replace("_", "").replace("-", ""):
            return token
    return None


def _lifecycle_stage(row: Dict[str, Any]) -> str:
    return str(_first_present(row, ["lifecycle_stage", "lifecycle_branch", "branch", "status"]) or "unknown")


def _outcome_class(row: Dict[str, Any]) -> str:
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "final_outcome",
            "outcome_class",
            "status",
            "lifecycle_branch",
            "event_type",
            "cancel_replace_outcome",
            "no_fill_reason_label",
        )
    ).lower()
    if "duplicate" in text or "oversell" in text:
        return "safety_incident"
    if "filled" in text or "fill" in text:
        return "filled_or_fill_related"
    if "cancel" in text or "terminal" in text or "expired" in text or "rejected" in text:
        return "terminal_or_cancel_related"
    if "no_fill" in text or "open" in text or "stale" in text:
        return "open_or_no_fill_related"
    return "unclassified"


def _metric_pairs(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    metric_keys = [
        ("fill_count", "count"),
        ("filled_base", "base"),
        ("filled_quote", "quote"),
        ("avg_fill_price", "quote_per_base"),
        ("fill_latency_seconds", "seconds"),
        ("no_fill_duration_seconds", "seconds"),
        ("stale_order_age_seconds", "seconds"),
        ("slippage_vs_decision_mid_pct", "pct"),
        ("slippage_vs_best_bid_or_ask_pct", "pct"),
        ("fee_quote", "quote"),
        ("fee_bps_estimate", "bps"),
        ("realized_vs_planned_edge_pct", "pct"),
        ("target_distance_pct", "pct"),
        ("remaining_size", "base"),
    ]
    out = []
    for key, unit in metric_keys:
        if key in row and row.get(key) not in (None, ""):
            out.append({"metric_name": key, "metric_value": row.get(key), "metric_unit": unit})
    if not out:
        out.append({"metric_name": "event_observed", "metric_value": 1, "metric_unit": "count"})
    return out


def _categories_for(row: Dict[str, Any], metric_name: str) -> List[str]:
    event = _event_type(row).lower()
    text = json.dumps(row, sort_keys=True, default=str).lower()
    categories: List[str] = []
    if metric_name in {"fill_count", "filled_base", "filled_quote", "avg_fill_price", "fill_latency_seconds"} or "fill" in event:
        categories.append("fill_quality")
    if metric_name in {"no_fill_duration_seconds", "stale_order_age_seconds", "target_distance_pct"} or "no_fill" in text or "stale" in text:
        categories.append("no_fill_duration")
    if "cancel_replace" in text or "replace" in event or "reprice" in event:
        categories.append("cancel_replace_outcome")
    if "post_only" in text or "maker" in text or "taker" in text:
        categories.extend(["post_only_fill_behavior", "maker_taker_liquidity"])
    if metric_name in {"slippage_vs_decision_mid_pct", "slippage_vs_best_bid_or_ask_pct", "fee_quote", "fee_bps_estimate", "realized_vs_planned_edge_pct"}:
        categories.append("slippage_fee_realization")
    if "reservation" in text or "drift" in text:
        categories.append("reservation_drift")
    if "duplicate" in text or "oversell" in text:
        categories.append("duplicate_or_oversell_incidents")
    if "terminal" in text or "cancelled" in text or "filled" in text or "expired" in text or "rejected" in text:
        categories.append("lifecycle_terminal_handling")
    quote_value = _first_present(row, ["filled_quote", "planned_quote", "notional_quote", "quote_size"])
    if quote_value is not None and to_decimal(quote_value) > 0 and to_decimal(quote_value) < to_decimal("10"):
        categories.append("tiny_notional_lifecycle_overhead")
    if "stale" in text or "confusion" in text or "label" in text:
        categories.append("stale_label_or_workflow_confusion")
    if not categories:
        categories.append("parameter_categories_implicated")
    return sorted(set(categories))


def _parameter_categories(categories: Iterable[str]) -> List[str]:
    mapped: set[str] = set()
    for category in categories:
        if category in {"fill_quality", "no_fill_duration", "maker_taker_liquidity", "slippage_fee_realization"}:
            mapped.add("d5_execution_learning")
        if category in {"cancel_replace_outcome", "post_only_fill_behavior"}:
            mapped.add("d4_dynamic_order_management")
        if category in {"reservation_drift", "duplicate_or_oversell_incidents", "lifecycle_terminal_handling", "tiny_notional_lifecycle_overhead"}:
            mapped.add("d3_controlled_exit")
        if category == "stale_label_or_workflow_confusion":
            mapped.add("gatekeeper_analysis_routing")
    return sorted(mapped or {"d5_execution_learning"})


def _candidate_hints(categories: Iterable[str]) -> List[str]:
    hints: set[str] = set()
    mapping = {
        "fill_quality": ["fill_rate", "post_only_fill_behavior"],
        "no_fill_duration": ["stale_order_age_threshold", "no_fill_duration_thresholds"],
        "cancel_replace_outcome": ["cancel_replace_trigger", "cooldown_after_failed_replace"],
        "post_only_fill_behavior": ["post_only_crossing_guard"],
        "maker_taker_liquidity": ["spread_filters", "minimum_liquidity_conditions"],
        "slippage_fee_realization": ["fee_spread_slippage_buffer", "minimum_expected_net_edge"],
        "reservation_drift": ["open_exit_reservation_model"],
        "duplicate_or_oversell_incidents": ["duplicate_exit_prevention", "max_open_exit_orders"],
        "lifecycle_terminal_handling": ["terminal_lifecycle_rules", "partial_fill_handling"],
        "tiny_notional_lifecycle_overhead": ["min_base_quote_handling", "small_position_fallback"],
        "stale_label_or_workflow_confusion": ["duplicate_intent_suppression", "prompt_output_schema_strictness"],
    }
    for category in categories:
        hints.update(mapping.get(category, []))
    return sorted(hints)


def _evidence_strength(row: Dict[str, Any], metric_name: str) -> str:
    if metric_name == "event_observed":
        return "weak"
    if row.get("is_complete_lifecycle_event") is True or _outcome_class(row) in {"filled_or_fill_related", "terminal_or_cancel_related"}:
        return "medium"
    if metric_name in {"fill_count", "filled_base", "filled_quote", "no_fill_duration_seconds", "fee_quote"}:
        return "medium"
    return "weak"


def _warnings_for(row: Dict[str, Any], categories: Iterable[str]) -> List[str]:
    warnings = ["d5_evidence_adapter_report_only", "not_parameter_recommendation"]
    if "tiny_notional_lifecycle_overhead" in set(categories):
        warnings.append("tiny_notional_evidence_requires_manual_context")
    if not _order_label(row):
        warnings.append("missing_order_label")
    if _ticker(row) == "UNKNOWN":
        warnings.append("missing_ticker")
    return sorted(set(warnings))


def _blockers_for(row: Dict[str, Any]) -> List[str]:
    blockers = []
    text = json.dumps(row, sort_keys=True, default=str).lower()
    if "contains_rankings" in row and row.get("contains_rankings") is True:
        blockers.append("source_contains_rankings")
    if "contains_recommendations" in row and row.get("contains_recommendations") is True:
        blockers.append("source_contains_recommendations")
    if "live_instruction" in text or "submit_order" in text or "cancel_order" in text:
        blockers.append("source_may_contain_live_instruction_language")
    return sorted(set(blockers))


def _evidence_id(*, source_file: str, index: int, metric_name: str, row: Dict[str, Any]) -> str:
    basis = json.dumps(
        {
            "source_file": source_file,
            "index": index,
            "metric_name": metric_name,
            "event_type": _event_type(row),
            "client_order_id": row.get("client_order_id"),
            "exchange_order_id": row.get("exchange_order_id"),
        },
        sort_keys=True,
        default=str,
    )
    return "d6d5-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def build_evidence_rows_from_records(
    records: Iterable[Dict[str, Any]],
    *,
    source_file: str,
    source_type: str,
    generated_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    generated = generated_at or now_iso()
    rows: List[Dict[str, Any]] = []
    for index, record in enumerate(records):
        for metric in _metric_pairs(record):
            categories = _categories_for(record, str(metric["metric_name"]))
            rows.append(
                {
                    "evidence_id": _evidence_id(
                        source_file=source_file,
                        index=index,
                        metric_name=str(metric["metric_name"]),
                        row=record,
                    ),
                    "generated_at": generated,
                    "source_type": source_type,
                    "source_file": source_file,
                    "event_type": _event_type(record),
                    "ticker": _ticker(record),
                    "order_label": _order_label(record),
                    "lifecycle_stage": _lifecycle_stage(record),
                    "outcome_class": _outcome_class(record),
                    **metric,
                    "evidence_categories": categories,
                    "parameter_categories_implicated": _parameter_categories(categories),
                    "parameter_candidates_implicated": _candidate_hints(categories),
                    "evidence_strength": _evidence_strength(record, str(metric["metric_name"])),
                    "warnings": _warnings_for(record, categories),
                    "blockers": _blockers_for(record),
                    "human_review_required": True,
                    "parameter_change_allowed": False,
                    "parameter_review_approved": False,
                }
            )
    return rows


def _count(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def build_phase_d6_d5_evidence_adapter_report(
    *,
    input_paths: Iterable[str | Path],
    source_type: str = "auto",
) -> Dict[str, Any]:
    generated = now_iso()
    paths = [assert_research_path(path) for path in input_paths]
    if not paths:
        raise ValueError("d6_d5_evidence_adapter_requires_at_least_one_input_path")
    evidence_rows: List[Dict[str, Any]] = []
    source_summary = []
    for path in paths:
        records = _load_json_or_jsonl(path)
        inferred_type = source_type if source_type != "auto" else _infer_source_type(path, records)
        rows = build_evidence_rows_from_records(
            records,
            source_file=str(path),
            source_type=inferred_type,
            generated_at=generated,
        )
        evidence_rows.extend(rows)
        source_summary.append(
            {
                "source_file": str(path),
                "source_type": inferred_type,
                "record_count": len(records),
                "evidence_row_count": len(rows),
            }
        )
    warnings = [
        "d5_evidence_adapter_only",
        "not_parameter_review",
        "not_parameter_search",
        "not_optimization",
        "not_live_order_monitor",
    ]
    blockers = sorted({blocker for row in evidence_rows for blocker in row.get("blockers") or []})
    return {
        "generated_at": generated,
        "phase": D6_D5_EVIDENCE_ADAPTER_PHASE,
        "status": "d6_d5_evidence_ready",
        "source_summary": source_summary,
        "evidence_category_counts": _count(
            category for row in evidence_rows for category in row.get("evidence_categories") or []
        ),
        "parameter_category_counts": _count(
            category for row in evidence_rows for category in row.get("parameter_categories_implicated") or []
        ),
        "evidence_strength_counts": _count(row.get("evidence_strength") for row in evidence_rows),
        "evidence_row_count": len(evidence_rows),
        "evidence_rows": evidence_rows,
        "warnings": warnings,
        "blockers": blockers,
        **_safety_flags(),
    }


def _infer_source_type(path: Path, records: List[Dict[str, Any]]) -> str:
    name = path.name.lower()
    if "learning" in name:
        return "d5_learning_log"
    if "metric" in name:
        return "d5_execution_metrics"
    if "order_events" in name:
        return "lifecycle_order_events"
    if records and any("lifecycle_branch" in row for row in records):
        return "d5_learning_log"
    if records and any("fill_quality_label" in row for row in records):
        return "d5_execution_metrics"
    return "generic_local_evidence"


__all__ = [
    "D5_EVIDENCE_CATEGORIES",
    "D6_D5_EVIDENCE_ADAPTER_PHASE",
    "build_evidence_rows_from_records",
    "build_phase_d6_d5_evidence_adapter_report",
]
