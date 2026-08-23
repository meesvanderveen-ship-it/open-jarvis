from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_REPORT_BUNDLE_WRITER_PHASE = "D6_report_bundle_writer_atomic_output_v1"


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


def assert_reports_d6_output_path(path: str | Path) -> Path:
    output = assert_research_path(path)
    parts = [part.lower() for part in output.parts]
    for index, part in enumerate(parts[:-1]):
        if part == "reports" and parts[index + 1] == "d6":
            if output.name == ".env" or ".env" in output.name:
                raise ValueError("d6_report_bundle_writer_refuses_env_output")
            return output
    raise ValueError("d6_report_bundle_writer_output_must_be_under_reports_d6")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_source_paths(paths: Iterable[str | Path] | None) -> list[str]:
    safe_paths: list[str] = []
    for raw in paths or []:
        safe = assert_research_path(raw)
        if safe.is_symlink():
            raise ValueError("d6_report_bundle_writer_refuses_symlink_source")
        safe_paths.append(str(safe))
    return sorted(set(safe_paths))


def _input_hashes(paths: Iterable[str | Path] | None) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    for raw in paths or []:
        safe = assert_research_path(raw)
        if safe.is_file():
            hashes[str(safe)] = _sha256_file(safe)
    return dict(sorted(hashes.items()))


def build_phase_d6_report_bundle(
    *,
    report_type: str,
    content: Dict[str, Any] | str,
    source_paths: Iterable[str | Path] | None = None,
    input_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    safe_sources = _safe_source_paths(source_paths)
    supplied_hashes = dict(input_hashes or {})
    return {
        "generated_at": now_iso(),
        "phase": D6_REPORT_BUNDLE_WRITER_PHASE,
        "status": "d6_report_bundle_ready",
        "report_type": str(report_type or "generic_research_report"),
        "source_paths": safe_sources,
        "input_hashes": supplied_hashes or _input_hashes(safe_sources),
        "content": content,
        "warnings": [
            "report_bundle_writer_only",
            "not_parameter_review",
            "not_parameter_search",
            "not_optimization",
        ],
        "blockers": [],
        **_safety_flags(),
    }


def serialize_report(report: Dict[str, Any], *, markdown: bool = False) -> bytes:
    if markdown:
        lines = [
            "# D.6 Research Report Bundle",
            "",
            "Safety: research-only output. No live trading instruction. No parameter changes approved.",
            "",
            f"- generated_at: `{report.get('generated_at', '')}`",
            f"- report_type: `{report.get('report_type', '')}`",
            f"- phase: `{report.get('phase', '')}`",
            f"- source_path_count: `{len(report.get('source_paths') or [])}`",
            f"- human_review_required: `{report.get('human_review_required')}`",
            f"- parameter_review_approved: `{report.get('parameter_review_approved')}`",
            "",
            "## Content",
            "",
            "```json",
            json.dumps(report.get("content"), indent=2, sort_keys=True, ensure_ascii=False),
            "```",
            "",
        ]
        return ("\n".join(lines)).encode("utf-8")
    return (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)


def metadata_sidecar_path(output_path: str | Path) -> Path:
    path = assert_reports_d6_output_path(output_path)
    return path.with_name(f"{path.name}.metadata.json")


def build_metadata_sidecar(
    *,
    output_path: str | Path,
    report: Dict[str, Any],
    report_bytes: bytes,
) -> Dict[str, Any]:
    safe_output = assert_reports_d6_output_path(output_path)
    return {
        "generated_at": now_iso(),
        "phase": D6_REPORT_BUNDLE_WRITER_PHASE,
        "status": "d6_report_bundle_metadata_ready",
        "output_path": str(safe_output),
        "sha256": _sha256_bytes(report_bytes),
        "report_type": report.get("report_type"),
        "source_paths": list(report.get("source_paths") or []),
        "input_hashes": dict(report.get("input_hashes") or {}),
        **_safety_flags(),
    }


def write_phase_d6_report_bundle(
    report: Dict[str, Any],
    output_path: str | Path,
    *,
    markdown: bool = False,
    metadata_sidecar: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    safe_output = assert_reports_d6_output_path(output_path)
    report_bytes = serialize_report(report, markdown=markdown)
    sidecar = build_metadata_sidecar(output_path=safe_output, report=report, report_bytes=report_bytes)
    sidecar_path = metadata_sidecar_path(safe_output)
    if not dry_run:
        _atomic_write_bytes(safe_output, report_bytes)
        if metadata_sidecar:
            _atomic_write_bytes(
                sidecar_path,
                (json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
            )
    return {
        "generated_at": now_iso(),
        "phase": D6_REPORT_BUNDLE_WRITER_PHASE,
        "status": "d6_report_bundle_write_preview" if dry_run else "d6_report_bundle_written",
        "output_path": str(safe_output),
        "metadata_sidecar_path": str(sidecar_path) if metadata_sidecar else None,
        "dry_run": dry_run,
        "would_write_report": True,
        "would_write_metadata_sidecar": bool(metadata_sidecar),
        "report_sha256": sidecar["sha256"],
        "report_type": report.get("report_type"),
        **_safety_flags(),
    }


__all__ = [
    "D6_REPORT_BUNDLE_WRITER_PHASE",
    "assert_reports_d6_output_path",
    "build_metadata_sidecar",
    "build_phase_d6_report_bundle",
    "metadata_sidecar_path",
    "serialize_report",
    "write_phase_d6_report_bundle",
]
