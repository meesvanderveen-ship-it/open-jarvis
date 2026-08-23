from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_d5_evidence_adapter import build_phase_d6_d5_evidence_adapter_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_GOVERNANCE_EVIDENCE_BUNDLE_PHASE = "D6_governance_evidence_bundle_v1"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def parse_function_preservation_audit(text: str) -> Dict[str, Any]:
    status_match = re.search(r"^Status:\s+(.+)$", text, flags=re.MULTILINE)
    order_match = re.search(
        r"total_records=(\d+)\s+total_open_orders=(\d+)\s+open_c43_entry=(\d+)\s+open_d3_exit=(\d+)",
        text,
    )
    warnings = []
    in_warnings = False
    for line in text.splitlines():
        if line.strip() == "Warnings:":
            in_warnings = True
            continue
        if in_warnings and line.startswith("Next steps:"):
            break
        if in_warnings and line.strip().startswith("- "):
            warnings.append(line.strip()[2:])
    return {
        "status": status_match.group(1).strip() if status_match else "unknown",
        "total_open_orders": int(order_match.group(2)) if order_match else None,
        "open_d3_exit": int(order_match.group(4)) if order_match else None,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _open_orders_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(report.get("summary") or {})
    return {
        "total_orders": summary.get("total_orders"),
        "open_orders": summary.get("open_orders"),
        "open_by_ticker": summary.get("open_by_ticker") or {},
        "reserved_base_by_ticker": summary.get("reserved_base_by_ticker") or {},
    }


def _d3_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    governance = dict(report.get("reservation_governance") or {})
    open_orders = dict(report.get("open_d3_exit_orders") or {})
    return {
        "status": report.get("status"),
        "live_order_submitted": bool(report.get("live_order_submitted")),
        "live_submission_attempted": bool(report.get("live_submission_attempted")),
        "open_d3_exit_count": open_orders.get("total_open_d3_exit_orders"),
        "position_present": bool(report.get("position_present")),
        "reserved_base_open_exit_orders": governance.get("reserved_base_open_exit_orders"),
        "governance_blockers": list(governance.get("blockers") or []),
        "fail_closed": bool(governance.get("fail_closed_recommendation")),
    }


def _state_hash_summary(state_hashes: Dict[str, str]) -> Dict[str, str]:
    return {str(path): str(value) for path, value in sorted((state_hashes or {}).items())}


def build_evidence_summary_from_paths(input_paths: Iterable[str | Path]) -> Dict[str, Any]:
    paths = [assert_research_path(path) for path in input_paths]
    if not paths:
        return {
            "source_count": 0,
            "evidence_row_count": 0,
            "evidence_category_counts": {},
            "parameter_category_counts": {},
            "evidence_strength_counts": {},
            "source_summary": [],
            "blockers": [],
        }
    evidence_report = build_phase_d6_d5_evidence_adapter_report(
        input_paths=paths,
        source_type="lifecycle_order_events",
    )
    return {
        "source_count": len(paths),
        "evidence_row_count": evidence_report.get("evidence_row_count"),
        "evidence_category_counts": evidence_report.get("evidence_category_counts") or {},
        "parameter_category_counts": evidence_report.get("parameter_category_counts") or {},
        "evidence_strength_counts": evidence_report.get("evidence_strength_counts") or {},
        "source_summary": list(evidence_report.get("source_summary") or []),
        "blockers": list(evidence_report.get("blockers") or []),
    }


def _overall_status(
    *,
    open_orders: Dict[str, Any],
    function_audit: Dict[str, Any],
    d3: Dict[str, Any],
    evidence: Dict[str, Any],
) -> str:
    blockers: List[str] = []
    if open_orders.get("open_orders") not in (0, "0"):
        blockers.append("open_orders_present")
    if function_audit.get("status") != "ok_observe_only":
        blockers.append("function_audit_not_observe_only")
    if function_audit.get("open_d3_exit") not in (0, "0"):
        blockers.append("function_audit_open_d3_exit_present")
    if d3.get("open_d3_exit_count") not in (0, "0"):
        blockers.append("d3_open_exit_present")
    if d3.get("live_order_submitted") or d3.get("live_submission_attempted"):
        blockers.append("d3_live_submit_detected")
    if evidence.get("blockers"):
        blockers.append("evidence_blockers_present")
    return "pass" if not blockers else "blocked"


def build_phase_d6_governance_evidence_bundle(
    *,
    open_orders_report: Dict[str, Any],
    function_audit_text: str,
    d3_controlled_exits_report: Dict[str, Any],
    state_hashes_before: Dict[str, str],
    state_hashes_after: Optional[Dict[str, str]] = None,
    evidence_input_paths: Iterable[str | Path] = (),
    environment_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    open_summary = _open_orders_summary(open_orders_report)
    audit_summary = parse_function_preservation_audit(function_audit_text)
    d3 = _d3_summary(d3_controlled_exits_report)
    evidence = build_evidence_summary_from_paths(evidence_input_paths)
    status = _overall_status(open_orders=open_summary, function_audit=audit_summary, d3=d3, evidence=evidence)
    return {
        "generated_at": now_iso(),
        "phase": D6_GOVERNANCE_EVIDENCE_BUNDLE_PHASE,
        "status": "d6_governance_evidence_bundle_ready",
        "overall_status": status,
        "scope": {
            "report_only": True,
            "local_checks_only": True,
            "coinbase_interaction": False,
            "trading_state_mutation": False,
            "system_mutation": False,
        },
        "local_lifecycle_safety": {
            "open_orders": open_summary,
            "function_preservation_audit": audit_summary,
            "d3_controlled_exits": d3,
            "state_hashes_before": _state_hash_summary(state_hashes_before),
            "state_hashes_after": _state_hash_summary(state_hashes_after or state_hashes_before),
            "state_hashes_match": _state_hash_summary(state_hashes_before)
            == _state_hash_summary(state_hashes_after or state_hashes_before),
        },
        "historical_evidence_summary": evidence,
        "environment_summary": dict(environment_summary or {}),
        "warnings": [
            "governance_evidence_bundle_report_only",
            "not_parameter_review",
            "not_parameter_search",
            "not_optimization",
            "no_live_actions_approved",
            "no_state_repairs_approved",
        ],
        "blockers": [] if status == "pass" else ["governance_bundle_status_blocked"],
        **_safety_flags(),
    }


__all__ = [
    "D6_GOVERNANCE_EVIDENCE_BUNDLE_PHASE",
    "build_evidence_summary_from_paths",
    "build_phase_d6_governance_evidence_bundle",
    "parse_function_preservation_audit",
]
