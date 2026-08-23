from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_evidence_review_bundle import build_phase_d6_evidence_review_bundle, load_report
from bot.phase_d6_guardrail_summary_adapter import build_phase_d6_guardrail_summary_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_parameter_inventory import CATEGORY_LABELS, build_phase_d6_parameter_inventory_report


D6_PARAMETER_REVIEW_PACK_PHASE = "D6_parameter_review_pack_scaffold_v1"


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


def _load_optional_report(path: str | Path | None) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    return load_report(assert_research_path(path))


def _load_many(paths: Optional[Iterable[str | Path]]) -> List[Dict[str, Any]]:
    return [load_report(assert_research_path(path)) for path in (paths or [])]


def _count(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _merge_counts(*counts: Dict[str, Any]) -> Dict[str, int]:
    merged: Dict[str, int] = {}
    for mapping in counts:
        for key, value in (mapping or {}).items():
            merged[str(key)] = merged.get(str(key), 0) + int(value or 0)
    return dict(sorted(merged.items()))


def _build_evidence_bundle(
    *,
    evidence_review_bundle: Optional[Dict[str, Any]],
    evidence_review_bundle_path: str | Path | None,
    d5_evidence_paths: Optional[Iterable[str | Path]],
    regime_report_paths: Optional[Iterable[str | Path]],
    fill_realism_evidence_paths: Optional[Iterable[str | Path]],
    parameter_inventory_report: Dict[str, Any],
) -> Dict[str, Any]:
    if evidence_review_bundle is not None:
        return evidence_review_bundle
    loaded = _load_optional_report(evidence_review_bundle_path)
    if loaded is not None:
        return loaded
    return build_phase_d6_evidence_review_bundle(
        d5_evidence_paths=d5_evidence_paths,
        regime_report_paths=regime_report_paths,
        fill_realism_evidence_paths=fill_realism_evidence_paths,
        parameter_inventory_report=parameter_inventory_report,
    )


def _build_guardrail_summary(
    *,
    guardrail_summary_report: Optional[Dict[str, Any]],
    guardrail_summary_path: str | Path | None,
    guardrail_report_paths: Optional[Iterable[str | Path]],
) -> Optional[Dict[str, Any]]:
    if guardrail_summary_report is not None:
        return guardrail_summary_report
    loaded = _load_optional_report(guardrail_summary_path)
    if loaded is not None:
        return loaded
    paths = list(guardrail_report_paths or [])
    if not paths:
        return None
    return build_phase_d6_guardrail_summary_report(report_paths=paths)


def _section_status(*, evidence_count: int, warning_count: int, blocker_count: int, guardrail_status: str) -> str:
    if blocker_count or guardrail_status == "blocked":
        return "blocked"
    if evidence_count <= 0:
        return "insufficient_evidence"
    if evidence_count >= 3 and guardrail_status in {"pass", "warning"}:
        return "ready_for_human_review"
    if warning_count or guardrail_status in {"warning", "insufficient"}:
        return "exploratory_only"
    return "exploratory_only"


def _guardrail_status_for(category: str, rows: List[Dict[str, Any]]) -> str:
    statuses = [row.get("guardrail_status") for row in rows if category in (row.get("implicated_parameter_categories") or [])]
    if not statuses:
        return "insufficient"
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if "insufficient" in statuses:
        return "insufficient"
    return "pass"


def _review_sections(
    *,
    inventory: Dict[str, Any],
    evidence_bundle: Dict[str, Any],
    guardrail_summary: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    d5_counts = dict((evidence_bundle.get("d5_evidence_summary") or {}).get("parameter_category_counts") or {})
    fill_counts = dict((evidence_bundle.get("fill_realism_summary") or {}).get("parameter_category_counts") or {})
    evidence_counts = _merge_counts(d5_counts, fill_counts)
    d5_strength = dict((evidence_bundle.get("d5_evidence_summary") or {}).get("evidence_strength_counts") or {})
    fill_strength = dict((evidence_bundle.get("fill_realism_summary") or {}).get("evidence_strength_counts") or {})
    global_strength = _merge_counts(d5_strength, fill_strength)
    guardrail_rows = list((guardrail_summary or {}).get("guardrail_summary_rows") or [])
    guardrail_category_counts = dict((guardrail_summary or {}).get("implicated_parameter_category_counts") or {})
    inventory_counts = dict(inventory.get("category_counts") or {})
    sections: List[Dict[str, Any]] = []
    for category in CATEGORY_LABELS:
        evidence_count = int(evidence_counts.get(category, 0)) + int(guardrail_category_counts.get(category, 0))
        section_guardrails = [row for row in guardrail_rows if category in (row.get("implicated_parameter_categories") or [])]
        warning_count = sum(int(row.get("warning_count") or 0) for row in section_guardrails)
        blocker_count = sum(int(row.get("blocker_count") or 0) for row in section_guardrails)
        guardrail_status = _guardrail_status_for(category, guardrail_rows)
        if evidence_count <= 0:
            sample_warning = "no_category_evidence_present"
        elif evidence_count < 3:
            sample_warning = "limited_category_evidence"
        else:
            sample_warning = "sample_size_still_requires_human_review"
        sections.append(
            {
                "category": category,
                "candidate_count": int(inventory_counts.get(category, 0)),
                "evidence_count": evidence_count,
                "warning_count": warning_count,
                "blocker_count": blocker_count,
                "evidence_strength_counts": global_strength,
                "sample_size_warning": sample_warning,
                "guardrail_status": guardrail_status,
                "review_status": _section_status(
                    evidence_count=evidence_count,
                    warning_count=warning_count,
                    blocker_count=blocker_count,
                    guardrail_status=guardrail_status,
                ),
                "prohibited_interpretations": [
                    "do_not_infer_best_parameter",
                    "do_not_infer_parameter_value",
                    "do_not_approve_runtime_change",
                    "do_not_use_as_live_signal",
                ],
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
            }
        )
    return sections


def _review_readiness(sections: List[Dict[str, Any]], blockers: Dict[str, int]) -> str:
    if blockers or any(section["review_status"] == "blocked" for section in sections):
        return "blocked"
    if all(section["review_status"] == "insufficient_evidence" for section in sections):
        return "insufficient_evidence"
    if any(section["review_status"] == "ready_for_human_review" for section in sections):
        return "ready_for_human_review"
    return "exploratory_only"


def build_phase_d6_parameter_review_pack(
    *,
    parameter_inventory_report: Optional[Dict[str, Any]] = None,
    parameter_inventory_path: str | Path | None = None,
    evidence_review_bundle: Optional[Dict[str, Any]] = None,
    evidence_review_bundle_path: str | Path | None = None,
    d5_evidence_paths: Optional[Iterable[str | Path]] = None,
    regime_report_paths: Optional[Iterable[str | Path]] = None,
    fill_realism_evidence_paths: Optional[Iterable[str | Path]] = None,
    guardrail_summary_report: Optional[Dict[str, Any]] = None,
    guardrail_summary_path: str | Path | None = None,
    guardrail_report_paths: Optional[Iterable[str | Path]] = None,
) -> Dict[str, Any]:
    inventory = parameter_inventory_report or _load_optional_report(parameter_inventory_path) or build_phase_d6_parameter_inventory_report()
    evidence_bundle = _build_evidence_bundle(
        evidence_review_bundle=evidence_review_bundle,
        evidence_review_bundle_path=evidence_review_bundle_path,
        d5_evidence_paths=d5_evidence_paths,
        regime_report_paths=regime_report_paths,
        fill_realism_evidence_paths=fill_realism_evidence_paths,
        parameter_inventory_report=inventory,
    )
    guardrails = _build_guardrail_summary(
        guardrail_summary_report=guardrail_summary_report,
        guardrail_summary_path=guardrail_summary_path,
        guardrail_report_paths=guardrail_report_paths,
    )
    sections = _review_sections(inventory=inventory, evidence_bundle=evidence_bundle, guardrail_summary=guardrails)
    warning_counts = _merge_counts(evidence_bundle.get("warning_counts") or {}, (guardrails or {}).get("warning_counts") or {})
    blocker_counts = _merge_counts(evidence_bundle.get("blocker_counts") or {}, (guardrails or {}).get("blocker_counts") or {})
    return {
        "generated_at": now_iso(),
        "phase": D6_PARAMETER_REVIEW_PACK_PHASE,
        "status": "d6_parameter_review_pack_ready",
        "source_summary": {
            "inventory_source": "provided_or_built_local_inventory",
            "evidence_bundle_phase": evidence_bundle.get("phase"),
            "guardrail_summary_present": guardrails is not None,
            "review_section_count": len(sections),
        },
        "parameter_inventory_summary": evidence_bundle.get("parameter_inventory_summary")
        or {
            "candidate_count": inventory.get("candidate_count"),
            "category_counts": inventory.get("category_counts"),
            "safety_class_counts": inventory.get("safety_class_counts"),
            "parameter_change_allowed": False,
        },
        "evidence_summary": evidence_bundle.get("d5_evidence_summary") or {},
        "regime_summary": evidence_bundle.get("regime_summary") or {},
        "fill_realism_summary": evidence_bundle.get("fill_realism_summary") or {},
        "guardrail_summary": {
            "present": guardrails is not None,
            "guardrail_status_counts": (guardrails or {}).get("guardrail_status_counts") or {},
            "implicated_parameter_category_counts": (guardrails or {}).get("implicated_parameter_category_counts") or {},
        },
        "review_sections": sections,
        "review_section_status_counts": _count(section["review_status"] for section in sections),
        "warning_counts": warning_counts,
        "blocker_counts": blocker_counts,
        "review_readiness": _review_readiness(sections, blocker_counts),
        "suggested_next_research_steps": [
            "collect_category_specific_fixture_evidence",
            "add_guardrail_reports_for_missing_categories",
            "keep_do_not_change_parameters_as_valid_human_review_outcome",
            "separate_any_future_parameter_proposal_from_this_report",
        ],
        "prohibited_interpretations": [
            "do_not_infer_best_parameter",
            "do_not_rank_parameters",
            "do_not_infer_parameter_value",
            "do_not_approve_runtime_config_change",
            "do_not_generate_live_trading_instruction",
            "do_not_connect_learning_to_execution",
        ],
        "warnings": [
            "parameter_review_pack_scaffold_only",
            "human_review_required",
            "not_parameter_review_approval",
            "not_parameter_search",
            "not_optimization",
        ],
        "blockers": sorted(blocker_counts),
        **_safety_flags(),
    }


__all__ = [
    "D6_PARAMETER_REVIEW_PACK_PHASE",
    "build_phase_d6_parameter_review_pack",
]
