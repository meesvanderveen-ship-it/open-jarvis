from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_report_lineage import build_phase_d6_report_lineage
from bot.phase_d6_report_manifest import assert_reports_d6_path, build_phase_d6_report_manifest
from bot.phase_d6_research_safety_validator import build_phase_d6_research_safety_validation_report


D6_RESEARCH_INDEX_EXPORT_PHASE = "D6_research_index_export_v1"


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


def _load_report(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(assert_research_path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("d6_research_index_export_requires_json_object")
    return loaded


def build_phase_d6_research_index_export(
    *,
    manifest_report: Optional[Dict[str, Any]] = None,
    manifest_path: str | Path | None = None,
    lineage_report: Optional[Dict[str, Any]] = None,
    lineage_path: str | Path | None = None,
    safety_validation_report: Optional[Dict[str, Any]] = None,
    safety_validation_path: str | Path | None = None,
    report_paths: Optional[Iterable[str | Path]] = None,
) -> Dict[str, Any]:
    manifest = manifest_report or (_load_report(manifest_path) if manifest_path else None)
    if manifest is None:
        manifest = build_phase_d6_report_manifest(report_paths=report_paths or [])
    lineage = lineage_report or (_load_report(lineage_path) if lineage_path else None)
    if lineage is None:
        lineage = build_phase_d6_report_lineage(manifest_report=manifest)
    safety = safety_validation_report or (_load_report(safety_validation_path) if safety_validation_path else None)
    if safety is None:
        safety = build_phase_d6_research_safety_validation_report(manifest_report=manifest)
    return {
        "generated_at": now_iso(),
        "phase": D6_RESEARCH_INDEX_EXPORT_PHASE,
        "status": "d6_research_index_export_ready",
        "source_summary": {
            "manifest_phase": manifest.get("phase"),
            "lineage_phase": lineage.get("phase"),
            "safety_validation_phase": safety.get("phase"),
            "manifest_report_count": (manifest.get("source_summary") or {}).get("report_count"),
            "lineage_status": lineage.get("lineage_status"),
            "safety_overall_status": safety.get("overall_status"),
        },
        "manifest_summary": {
            "reproducibility_status_counts": manifest.get("reproducibility_status_counts") or {},
            "report_type_counts": manifest.get("report_type_counts") or {},
            "missing_safety_flag_counts": manifest.get("missing_safety_flag_counts") or {},
        },
        "lineage_summary": {
            "lineage_status": lineage.get("lineage_status"),
            "node_count": (lineage.get("source_summary") or {}).get("node_count"),
            "edge_count": (lineage.get("source_summary") or {}).get("edge_count"),
            "missing_input_references": lineage.get("missing_input_references") or [],
        },
        "safety_validation_summary": {
            "overall_status": safety.get("overall_status"),
            "pass_count": safety.get("pass_count"),
            "warning_count": safety.get("warning_count"),
            "blocker_count": safety.get("blocker_count"),
            "missing_flag_counts": safety.get("missing_flag_counts") or {},
            "prohibited_phrase_hits": safety.get("prohibited_phrase_hits") or {},
        },
        "blockers": sorted(set((manifest.get("blockers") or []) + (lineage.get("blockers") or []) + (safety.get("blockers") or []))),
        "warnings": [
            "research_index_export_only",
            "not_parameter_review",
            "not_parameter_search",
            "not_optimization",
            "no_parameter_changes_approved",
            "no_live_actions_approved",
            "no_learning_to_execution_enabled",
        ],
        "human_review_checklist": [
            "confirm_manifest_hashes_match_expected_artifacts",
            "inspect_missing_safety_flags_before_review",
            "resolve_blocked_safety_validation_before_parameter_review",
            "treat_incomplete_lineage_as_research_debt",
            "keep_parameter_change_tasks_separate",
        ],
        "explicit_conclusion": {
            "no_parameter_changes_approved": True,
            "no_live_actions_approved": True,
            "no_learning_to_execution_enabled": True,
        },
        **_safety_flags(),
    }


def research_index_export_to_markdown(export: Dict[str, Any]) -> str:
    manifest = dict(export.get("manifest_summary") or {})
    lineage = dict(export.get("lineage_summary") or {})
    safety = dict(export.get("safety_validation_summary") or {})
    lines = [
        "# D.6 Research Index Export",
        "",
        "Safety: research-only index. No parameter changes approved. No live actions approved. No learning-to-execution enabled.",
        "",
        "## Report Manifest Summary",
        "",
        f"- report_type_counts: `{manifest.get('report_type_counts', {})}`",
        f"- reproducibility_status_counts: `{manifest.get('reproducibility_status_counts', {})}`",
        f"- missing_safety_flag_counts: `{manifest.get('missing_safety_flag_counts', {})}`",
        "",
        "## Reproducibility Status",
        "",
        f"- lineage_status: `{lineage.get('lineage_status')}`",
        f"- safety_overall_status: `{safety.get('overall_status')}`",
        "",
        "## Lineage Summary",
        "",
        f"- node_count: `{lineage.get('node_count')}`",
        f"- edge_count: `{lineage.get('edge_count')}`",
        f"- missing_input_references: `{lineage.get('missing_input_references', [])}`",
        "",
        "## Safety Validation Summary",
        "",
        f"- pass_count: `{safety.get('pass_count')}`",
        f"- warning_count: `{safety.get('warning_count')}`",
        f"- blocker_count: `{safety.get('blocker_count')}`",
        f"- prohibited_phrase_hits: `{safety.get('prohibited_phrase_hits', {})}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = export.get("blockers") or []
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    for warning in export.get("warnings") or []:
        lines.append(f"- `{warning}`")
    lines.extend(["", "## Missing Metadata", ""])
    missing = manifest.get("missing_safety_flag_counts") or {}
    if missing:
        for key, count in sorted(missing.items()):
            lines.append(f"- `{key}`: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Human Review Checklist", ""])
    for item in export.get("human_review_checklist") or []:
        lines.append(f"- `{item}`")
    lines.extend(
        [
            "",
            "## Explicit Conclusion",
            "",
            "- No parameter changes approved.",
            "- No live actions approved.",
            "- No learning-to-execution enabled.",
            "",
            "## Next Research-Only Steps",
            "",
            "- address_missing_metadata",
            "- preserve_report_hashes_for_future_review",
            "- keep_config_changes_in_a_separate_approved_task",
        ]
    )
    return "\n".join(lines) + "\n"


def write_research_index_export(export: Dict[str, Any], output_path: str | Path, *, markdown: bool = False) -> Path:
    path = assert_reports_d6_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if markdown:
        path.write_text(research_index_export_to_markdown(export), encoding="utf-8")
    else:
        path.write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_RESEARCH_INDEX_EXPORT_PHASE",
    "build_phase_d6_research_index_export",
    "research_index_export_to_markdown",
    "write_research_index_export",
]
