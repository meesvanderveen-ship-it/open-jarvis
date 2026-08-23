from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_D6_BACKLEARNING_LABEL_EXPORT_PACK = "d6_backlearning_label_export_pack_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _rows(rows: Any) -> List[Dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _sources(root: Path) -> Dict[str, Dict[str, Any]]:
    rels = {
        "multi_ticker_paper_lifecycle_replay": "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json",
        "per_ticker_product_rule_evidence_cache": "reports/d6/per-ticker-product-rule-evidence-cache-20260609.json",
        "product_rule_fixture_evidence": "reports/d6/product-rule-fixture-evidence-20260609.json",
        "d5_d6_evidence_expansion": "reports/d6/d5-d6-evidence-expansion-20260609.json",
        "d6_human_review_decision_pack": "reports/d6/d6-human-review-decision-pack-20260609.json",
        "d6_acceptance_policy": "reports/d6/d6-acceptance-policy-20260609.json",
        "state_hygiene_cleanup_preview": "reports/d6/state-hygiene-cleanup-preview-20260609.json",
    }
    return {key: _load_json(root / rel) for key, rel in rels.items()}


def _ticker_labels(cache: Dict[str, Any], replay: Dict[str, Any]) -> List[Dict[str, Any]]:
    cache_by_ticker = {str(row.get("ticker")): row for row in _rows(cache.get("per_ticker_matrix"))}
    labels: List[Dict[str, Any]] = []
    for row in _rows(replay.get("per_ticker_replay_matrix")):
        ticker = str(row.get("ticker"))
        cache_row = cache_by_ticker.get(ticker, {})
        labels.append(
            {
                "label_group": "ticker",
                "ticker": ticker,
                "is_btc_usdc": ticker == "BTC-USDC",
                "is_non_btc": ticker != "BTC-USDC",
                "configured": bool(row.get("configured", True)),
                "evidence_strength": row.get("product_rule_evidence_strength") or cache_row.get("evidence_strength"),
                "fixture_product_rule_evidence": bool(cache_row.get("fixture_product_rule_evidence")),
                "live_readonly_cached": (row.get("product_rule_evidence_strength") or cache_row.get("evidence_strength"))
                == "live_readonly_cached",
                "paper_replay_usable": bool(row.get("paper_replay_usable")),
                "live_ready": False,
            }
        )
    return labels


def _lifecycle_labels(replay: Dict[str, Any]) -> List[Dict[str, Any]]:
    keys = [
        "paper_c4_entry_replay_status",
        "paper_d1_fill_to_position_replay_status",
        "paper_d2_plan_replay_status",
        "paper_d3_exit_replay_status",
        "paper_d4_cancel_replace_replay_status",
        "paper_d5_evidence_replay_status",
    ]
    labels: List[Dict[str, Any]] = []
    for row in _rows(replay.get("per_ticker_replay_matrix")):
        for key in keys:
            labels.append(
                {
                    "label_group": "paper_lifecycle",
                    "ticker": row.get("ticker"),
                    "label": key,
                    "value": row.get(key),
                    "paper_only": True,
                    "state_write_performed": False,
                }
            )
    return labels


def _outcome_labels(replay: Dict[str, Any], d5: Dict[str, Any], hygiene: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels: List[Dict[str, Any]] = []
    for row in _rows(replay.get("scenario_coverage")):
        for scenario in _rows(row.get("scenarios")):
            labels.append(
                {
                    "label_group": "outcome",
                    "ticker": row.get("ticker"),
                    "label": scenario.get("scenario"),
                    "value": scenario.get("status"),
                    "paper_only": True,
                }
            )
    fee = d5.get("fee_evidence") if isinstance(d5.get("fee_evidence"), dict) else {}
    no_fill = d5.get("no_fill_duration_evidence") if isinstance(d5.get("no_fill_duration_evidence"), dict) else {}
    cancel = d5.get("cancel_replace_timing_evidence") if isinstance(d5.get("cancel_replace_timing_evidence"), dict) else {}
    partial = d5.get("partial_fill_evidence") if isinstance(d5.get("partial_fill_evidence"), dict) else {}
    labels.extend(
        [
            {"label_group": "outcome", "label": "fee_gap", "value": fee.get("fee_gap_present", "unknown")},
            {"label_group": "outcome", "label": "no_fill", "value": no_fill.get("open_or_no_fill_event_count", 0)},
            {"label_group": "outcome", "label": "cancel_replace", "value": cancel.get("chain_count", 0)},
            {"label_group": "outcome", "label": "partial_fill", "value": partial.get("partial_fills_present", "unknown")},
            {
                "label_group": "outcome",
                "label": "state_hygiene_watch",
                "value": hygiene.get("status", hygiene.get("classification", "unknown")),
            },
        ]
    )
    return labels


def _review_labels(decision_pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels: List[Dict[str, Any]] = []
    for row in _rows(decision_pack.get("decision_matrix")):
        labels.append(
            {
                "label_group": "review",
                "area": row.get("area"),
                "decision_status": row.get("decision_status"),
                "review_severity": row.get("review_severity"),
                "blocks_parameter_review": bool(row.get("blocks_parameter_review")),
                "blocks_learning_to_execution": bool(row.get("blocks_learning_to_execution")),
            }
        )
    return labels


def _governance_labels(decision_pack: Dict[str, Any], acceptance: Dict[str, Any]) -> List[Dict[str, Any]]:
    flags = {}
    if isinstance(decision_pack.get("governance_flags"), dict):
        flags.update(decision_pack["governance_flags"])
    if isinstance(acceptance.get("governance_flags"), dict):
        flags.update(acceptance["governance_flags"])
    return [
        {"label_group": "governance", "label": "parameter_review_candidate", "value": bool(flags.get("parameter_review_candidate", False))},
        {"label_group": "governance", "label": "parameter_change_allowed", "value": bool(flags.get("parameter_change_allowed", False))},
        {"label_group": "governance", "label": "learning_to_execution_ready", "value": bool(flags.get("learning_to_execution_ready", False))},
        {"label_group": "governance", "label": "live_learning_allowed", "value": bool(flags.get("live_learning_allowed", False))},
    ]


def build_d6_backlearning_label_export_pack_report(
    *, root: str | Path = ".", generated_at: Optional[str] = None
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    sources = _sources(project_root)
    missing = [key for key, payload in sources.items() if not payload]
    ticker_labels = _ticker_labels(sources["per_ticker_product_rule_evidence_cache"], sources["multi_ticker_paper_lifecycle_replay"])
    lifecycle_labels = _lifecycle_labels(sources["multi_ticker_paper_lifecycle_replay"])
    outcome_labels = _outcome_labels(
        sources["multi_ticker_paper_lifecycle_replay"],
        sources["d5_d6_evidence_expansion"],
        sources["state_hygiene_cleanup_preview"],
    )
    review_labels = _review_labels(sources["d6_human_review_decision_pack"])
    governance_labels = _governance_labels(sources["d6_human_review_decision_pack"], sources["d6_acceptance_policy"])
    export_records = ticker_labels + lifecycle_labels + outcome_labels + review_labels + governance_labels
    warnings = ["export_is_report_only_not_training_input_approval"]
    if missing:
        warnings.append("missing_optional_label_sources")
    report = {
        "phase": PHASE_D6_BACKLEARNING_LABEL_EXPORT_PACK,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "export_only": True,
            "training_performed": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_proposed": False,
            "parameter_mutation_performed": False,
            "learning_to_execution_ready": False,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "state_write_performed": False,
        },
        "classification": "WATCH" if missing else "OK",
        "missing_label_sources": missing,
        "warnings": warnings,
        "label_counts": {
            "ticker_label_count": len(ticker_labels),
            "lifecycle_label_count": len(lifecycle_labels),
            "outcome_label_count": len(outcome_labels),
            "review_label_count": len(review_labels),
            "governance_label_count": len(governance_labels),
            "export_record_count": len(export_records),
        },
        "ticker_labels": ticker_labels,
        "paper_lifecycle_labels": lifecycle_labels,
        "outcome_labels": outcome_labels,
        "review_labels": review_labels,
        "governance_labels": governance_labels,
        "export_records": export_records,
        "governance_flags": {
            "d6_backlearning_label_export_pack_ready": True,
            "parameter_review_candidate": False,
            "parameter_values_proposed": False,
            "parameter_review_approved": False,
            "parameter_change_allowed": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
        },
    }
    return _json_safe(report)


def render_d6_backlearning_label_export_pack_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    counts = report.get("label_counts") or {}
    flags = report.get("governance_flags") or {}
    lines = [
        "# D6 Backlearning Label Export Pack",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- export_only: `{meta.get('export_only')}`",
        f"- training_performed: `{meta.get('training_performed')}`",
        f"- optimization_performed: `{meta.get('optimization_performed')}`",
        f"- ranking_performed: `{meta.get('ranking_performed')}`",
        f"- parameter_values_proposed: `{meta.get('parameter_values_proposed')}`",
        f"- state_write_performed: `{meta.get('state_write_performed')}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in counts.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Governance Flags", ""])
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_D6_BACKLEARNING_LABEL_EXPORT_PACK",
    "build_d6_backlearning_label_export_pack_report",
    "render_d6_backlearning_label_export_pack_markdown",
]
