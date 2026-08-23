from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_evidence_review_bundle import load_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_parameter_review_pack import build_phase_d6_parameter_review_pack


D6_HUMAN_REVIEW_EXPORT_PHASE = "D6_human_review_export_bundle_v1"


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


def assert_reports_d6_output_path(path: str | Path) -> Path:
    output = assert_research_path(path)
    parts = [part.lower() for part in output.parts]
    for index, part in enumerate(parts[:-1]):
        if part == "reports" and parts[index + 1] == "d6":
            return output
    raise ValueError("d6_human_review_export_output_must_be_under_reports_d6")


def build_phase_d6_human_review_export(
    *,
    parameter_review_pack: Dict[str, Any] | None = None,
    parameter_review_pack_path: str | Path | None = None,
) -> Dict[str, Any]:
    pack = parameter_review_pack
    if parameter_review_pack_path is not None:
        pack = load_report(parameter_review_pack_path)
    if pack is None:
        pack = build_phase_d6_parameter_review_pack()
    return {
        "generated_at": now_iso(),
        "phase": D6_HUMAN_REVIEW_EXPORT_PHASE,
        "status": "d6_human_review_export_ready",
        "source_phase": pack.get("phase"),
        "source_status": pack.get("status"),
        "review_readiness": pack.get("review_readiness"),
        "parameter_review_pack": pack,
        "human_review_checklist": [
            "confirm_dataset_and_evidence_sources_are_reproducible",
            "inspect_blockers_before_interpreting_any_section",
            "treat_insufficient_evidence_as_a_valid_result",
            "require_separate_parameter_proposal_task_for_any_future_change",
            "require_observe_only_or_shadow_validation_before_live_use",
        ],
        "explicit_conclusion": "no_parameter_changes_approved",
        "warnings": [
            "human_review_export_only",
            "no_parameter_changes_approved",
            "not_parameter_search",
            "not_optimization",
            "not_live_trading_instruction",
        ],
        "blockers": list(pack.get("blockers") or []),
        **_safety_flags(),
    }


def human_review_export_to_markdown(export: Dict[str, Any]) -> str:
    pack = dict(export.get("parameter_review_pack") or {})
    source = dict(pack.get("source_summary") or {})
    blockers = dict(pack.get("blocker_counts") or {})
    warnings = dict(pack.get("warning_counts") or {})
    lines = [
        "# D.6 Human Review Export",
        "",
        "Safety: research-only export. No live trading instruction. No parameter changes approved.",
        "",
        "## Source Summary",
        "",
        f"- generated_at: `{export.get('generated_at', '')}`",
        f"- source_phase: `{export.get('source_phase', '')}`",
        f"- review_readiness: `{export.get('review_readiness', '')}`",
        f"- review_section_count: `{source.get('review_section_count', 0)}`",
        f"- guardrail_summary_present: `{source.get('guardrail_summary_present')}`",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        for name, count in sorted(blockers.items()):
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        for name, count in sorted(warnings.items()):
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Category Sections", ""])
    for section in pack.get("review_sections") or []:
        lines.extend(
            [
                f"### {section.get('category')}",
                "",
                f"- review_status: `{section.get('review_status')}`",
                f"- evidence_count: `{section.get('evidence_count')}`",
                f"- warning_count: `{section.get('warning_count')}`",
                f"- blocker_count: `{section.get('blocker_count')}`",
                f"- guardrail_status: `{section.get('guardrail_status')}`",
                f"- parameter_review_approved: `{section.get('parameter_review_approved')}`",
                f"- parameter_change_allowed: `{section.get('parameter_change_allowed')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Evidence Summaries",
            "",
            f"- d5_evidence_rows: `{(pack.get('evidence_summary') or {}).get('evidence_row_count', 0)}`",
            f"- regime_windows: `{(pack.get('regime_summary') or {}).get('regime_window_count', 0)}`",
            f"- fill_realism_rows: `{(pack.get('fill_realism_summary') or {}).get('evidence_row_count', 0)}`",
            "",
            "## Human Review Checklist",
            "",
        ]
    )
    for item in export.get("human_review_checklist") or []:
        lines.append(f"- `{item}`")
    lines.extend(
        [
            "",
            "## Explicit Conclusion",
            "",
            "No parameter changes approved.",
            "",
            "## Next Research-Only Steps",
            "",
        ]
    )
    for item in pack.get("suggested_next_research_steps") or []:
        lines.append(f"- `{item}`")
    return "\n".join(lines) + "\n"


def write_human_review_export(export: Dict[str, Any], output_path: str | Path, *, markdown: bool = False) -> Path:
    path = assert_reports_d6_output_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if markdown:
        path.write_text(human_review_export_to_markdown(export), encoding="utf-8")
    else:
        path.write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_HUMAN_REVIEW_EXPORT_PHASE",
    "assert_reports_d6_output_path",
    "build_phase_d6_human_review_export",
    "human_review_export_to_markdown",
    "write_human_review_export",
]
