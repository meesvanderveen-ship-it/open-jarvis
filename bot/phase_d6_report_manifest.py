from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_REPORT_MANIFEST_PHASE = "D6_report_manifest_reproducibility_index_v1"
REQUIRED_SAFETY_FLAGS: Dict[str, Any] = {
    "research_only": True,
    "no_coinbase_call": True,
    "no_live_action": True,
    "state_write_performed": False,
    "no_optimization": True,
    "parameter_search_performed": False,
    "parameter_change_allowed": False,
    "learning_to_execution_allowed": False,
    "contains_rankings": False,
    "contains_recommendations": False,
    "contains_live_instructions": False,
    "human_review_required": True,
    "parameter_review_approved": False,
}


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


def assert_reports_d6_path(path: str | Path) -> Path:
    safe = assert_research_path(path)
    parts = [part.lower() for part in safe.parts]
    if "reports" in parts:
        for index, part in enumerate(parts[:-1]):
            if part == "reports" and parts[index + 1] == "d6":
                return safe
        raise ValueError("d6_report_path_must_be_under_reports_d6")
    return safe


def _expand_paths(paths: Iterable[str | Path] = (), directories: Iterable[str | Path] = ()) -> List[Path]:
    out: List[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = assert_research_path(raw)
        if path.is_symlink():
            raise ValueError("d6_report_manifest_refuses_symlink_paths")
        if path.is_file():
            key = str(path)
            if key not in seen:
                seen.add(key)
                out.append(path)
    for raw_dir in directories:
        root = assert_reports_d6_path(raw_dir)
        if root.is_symlink():
            raise ValueError("d6_report_manifest_refuses_symlink_paths")
        if not root.is_dir():
            raise ValueError("d6_report_manifest_directory_not_found")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                continue
            if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".md"}:
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    out.append(path)
    if not out:
        raise ValueError("d6_report_manifest_requires_at_least_one_report_path")
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if path.suffix.lower() != ".json":
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _input_paths(report: Dict[str, Any]) -> List[str]:
    keys = [
        "input_paths",
        "candle_paths",
        "d5_evidence_paths",
        "regime_report_paths",
        "fill_realism_evidence_paths",
        "guardrail_report_paths",
        "source_paths",
    ]
    found: List[str] = []
    for key in keys:
        value = report.get(key)
        if isinstance(value, list):
            found.extend(str(item) for item in value)
    for section_key in ("source_summary", "input_summary"):
        section = report.get(section_key)
        if isinstance(section, dict):
            for key, value in section.items():
                if "path" in str(key).lower() and isinstance(value, list):
                    found.extend(str(item) for item in value)
                elif "path" in str(key).lower() and value not in (None, ""):
                    found.append(str(value))
    return sorted(set(found))


def _output_paths(report: Dict[str, Any]) -> List[str]:
    found: List[str] = []
    for key, value in report.items():
        if "output_path" in str(key).lower() and value not in (None, ""):
            found.append(str(value))
    return sorted(set(found))


def _source_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    summary = report.get("source_summary") or report.get("input_summary") or {}
    return summary if isinstance(summary, dict) else {}


def _safety_detected(report: Dict[str, Any]) -> Dict[str, Any]:
    return {key: report.get(key) for key in REQUIRED_SAFETY_FLAGS if key in report}


def _missing_safety_flags(report: Dict[str, Any]) -> List[str]:
    missing = []
    for key, expected in REQUIRED_SAFETY_FLAGS.items():
        if report.get(key) != expected:
            missing.append(key)
    return missing


def _repro_status(*, report: Optional[Dict[str, Any]], missing_flags: List[str], blockers: List[str], input_paths: List[str]) -> str:
    if blockers:
        return "blocked"
    if report is None:
        return "insufficient_metadata"
    if missing_flags:
        return "missing_safety_flags"
    if not input_paths and not report.get("source_summary") and not report.get("input_summary"):
        return "missing_hashable_inputs"
    return "reproducible_metadata_present"


def _report_type(phase: str, extension: str, explicit_report_type: str = "") -> str:
    if explicit_report_type:
        return explicit_report_type
    phase_l = phase.lower()
    if "parameter_inventory" in phase_l:
        return "parameter_inventory"
    if "evidence_review_bundle" in phase_l or "combined_evidence" in phase_l:
        return "evidence_review_bundle"
    if "parameter_review_pack" in phase_l:
        return "parameter_review_pack"
    if "human_review_export" in phase_l:
        return "human_review_export"
    if "guardrail" in phase_l:
        return "guardrail_report"
    if "lineage" in phase_l:
        return "lineage_report"
    if "manifest" in phase_l:
        return "manifest_report"
    if extension == ".md":
        return "markdown_report"
    return "generic_research_report"


def build_manifest_row(path: str | Path) -> Dict[str, Any]:
    report_path = assert_research_path(path)
    if report_path.is_symlink():
        raise ValueError("d6_report_manifest_refuses_symlink_paths")
    stat = report_path.stat()
    report = _load_json(report_path)
    phase = str((report or {}).get("phase") or "")
    status = (report or {}).get("status")
    missing_flags = _missing_safety_flags(report or {}) if report is not None else list(REQUIRED_SAFETY_FLAGS)
    warnings = (report or {}).get("warnings") or []
    blockers = (report or {}).get("blockers") or []
    input_paths = _input_paths(report or {})
    row = {
        "report_id": "d6report-" + hashlib.sha256(str(report_path).encode("utf-8")).hexdigest()[:16],
        "source_path": str(report_path),
        "path_kind": "file",
        "file_extension": report_path.suffix.lower(),
        "file_size_bytes": stat.st_size,
        "modified_time_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sha256": _sha256(report_path),
        "detected_phase": phase or None,
        "detected_status": status,
        "generated_at_from_report": (report or {}).get("generated_at"),
        "report_type": _report_type(phase, report_path.suffix.lower(), str((report or {}).get("report_type") or "")),
        "source_summary": _source_summary(report or {}),
        "safety_flags_detected": _safety_detected(report or {}),
        "missing_safety_flags": missing_flags,
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
        "blocker_count": len(blockers) if isinstance(blockers, list) else 0,
        "input_paths_detected": input_paths,
        "output_paths_detected": _output_paths(report or {}),
        "reproducibility_status": _repro_status(
            report=report,
            missing_flags=missing_flags,
            blockers=list(blockers) if isinstance(blockers, list) else [],
            input_paths=input_paths,
        ),
        "human_review_required": True,
        "parameter_review_approved": False,
        "parameter_change_allowed": False,
    }
    return row


def build_phase_d6_report_manifest(
    *,
    report_paths: Iterable[str | Path] = (),
    report_directories: Iterable[str | Path] = (),
) -> Dict[str, Any]:
    paths = _expand_paths(report_paths, report_directories)
    rows = [build_manifest_row(path) for path in paths]
    return {
        "generated_at": now_iso(),
        "phase": D6_REPORT_MANIFEST_PHASE,
        "status": "d6_report_manifest_ready",
        "source_summary": {"report_count": len(rows), "directory_scan_count": len(list(report_directories or []))},
        "manifest_rows": rows,
        "reproducibility_status_counts": _count(row["reproducibility_status"] for row in rows),
        "report_type_counts": _count(row["report_type"] for row in rows),
        "missing_safety_flag_counts": _count(flag for row in rows for flag in row.get("missing_safety_flags") or []),
        "warnings": [
            "report_manifest_metadata_only",
            "not_parameter_review",
            "not_parameter_search",
            "not_optimization",
        ],
        "blockers": sorted({status for status in [row["reproducibility_status"] for row in rows] if status == "blocked"}),
        **_safety_flags(),
    }


def _count(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


__all__ = [
    "D6_REPORT_MANIFEST_PHASE",
    "REQUIRED_SAFETY_FLAGS",
    "assert_reports_d6_path",
    "build_manifest_row",
    "build_phase_d6_report_manifest",
]
