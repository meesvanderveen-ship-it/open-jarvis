from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_report_manifest import REQUIRED_SAFETY_FLAGS, build_phase_d6_report_manifest


D6_RESEARCH_SAFETY_VALIDATOR_PHASE = "D6_research_safety_validator_v1"
PROHIBITED_PHRASES = [
    "best parameter",
    "change parameter",
    "recommendation",
    "live signal",
    "execute this trade",
    "approved parameter",
]


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


def _load_text(path: str | Path) -> str:
    safe = assert_research_path(path)
    return safe.read_text(encoding="utf-8")


def _load_json(path: str | Path) -> Optional[Dict[str, Any]]:
    safe = assert_research_path(path)
    if safe.suffix.lower() != ".json":
        return None
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def _phrase_hits(text: str) -> List[str]:
    hits = []
    lowered = text.lower()
    for phrase in PROHIBITED_PHRASES:
        if re.search(r"(?<![a-z0-9_])" + re.escape(phrase) + r"(?![a-z0-9_])", lowered):
            hits.append(phrase)
    return hits


def _missing_flags(report: Dict[str, Any]) -> List[str]:
    return [key for key, expected in REQUIRED_SAFETY_FLAGS.items() if report.get(key) != expected]


def _row_status(missing: List[str], hits: List[str], report: Optional[Dict[str, Any]]) -> str:
    if hits:
        return "blocked"
    if report is None:
        return "insufficient_metadata"
    if missing:
        return "warning"
    return "pass"


def validate_report_path(path: str | Path) -> Dict[str, Any]:
    safe = assert_research_path(path)
    text = _load_text(safe)
    report = _load_json(safe)
    missing = _missing_flags(report or {}) if report is not None else list(REQUIRED_SAFETY_FLAGS)
    hits = _phrase_hits(text)
    status = _row_status(missing, hits, report)
    return {
        "source_path": str(safe),
        "detected_phase": (report or {}).get("phase"),
        "validation_status": status,
        "missing_safety_flags": missing,
        "prohibited_phrase_hits": hits,
        "warning_count": 1 if missing and not hits else 0,
        "blocker_count": 1 if hits else 0,
        "human_review_required": True,
        "parameter_review_approved": False,
        "parameter_change_allowed": False,
    }


def _paths_from_manifest(manifest: Dict[str, Any]) -> List[str]:
    return [str(row.get("source_path")) for row in manifest.get("manifest_rows") or [] if row.get("source_path")]


def _overall(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "insufficient_metadata"
    if any(row["validation_status"] == "blocked" for row in rows):
        return "blocked"
    if all(row["validation_status"] == "insufficient_metadata" for row in rows):
        return "insufficient_metadata"
    if any(row["validation_status"] in {"warning", "insufficient_metadata"} for row in rows):
        return "warning"
    return "pass"


def _count(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def build_phase_d6_research_safety_validation_report(
    *,
    report_paths: Optional[Iterable[str | Path]] = None,
    manifest_report: Optional[Dict[str, Any]] = None,
    manifest_path: str | Path | None = None,
) -> Dict[str, Any]:
    paths = list(report_paths or [])
    if manifest_path is not None:
        manifest_report = json.loads(assert_research_path(manifest_path).read_text(encoding="utf-8"))
    if manifest_report is not None:
        paths.extend(_paths_from_manifest(manifest_report))
    if not paths:
        raise ValueError("d6_research_safety_validator_requires_report_or_manifest")
    rows = [validate_report_path(path) for path in sorted(set(str(path) for path in paths))]
    missing_counts = _count(flag for row in rows for flag in row.get("missing_safety_flags") or [])
    phrase_counts = _count(hit for row in rows for hit in row.get("prohibited_phrase_hits") or [])
    return {
        "generated_at": now_iso(),
        "phase": D6_RESEARCH_SAFETY_VALIDATOR_PHASE,
        "status": "d6_research_safety_validation_ready",
        "validation_rows": rows,
        "pass_count": sum(1 for row in rows if row["validation_status"] == "pass"),
        "warning_count": sum(int(row.get("warning_count") or 0) for row in rows),
        "blocker_count": sum(int(row.get("blocker_count") or 0) for row in rows),
        "missing_flag_counts": missing_counts,
        "prohibited_phrase_hits": phrase_counts,
        "overall_status": _overall(rows),
        "warnings": [
            "research_safety_validator_only",
            "not_parameter_review",
            "not_parameter_search",
            "not_optimization",
        ],
        "blockers": sorted(phrase_counts),
        **_safety_flags(),
    }


__all__ = [
    "D6_RESEARCH_SAFETY_VALIDATOR_PHASE",
    "PROHIBITED_PHRASES",
    "build_phase_d6_research_safety_validation_report",
    "validate_report_path",
]
