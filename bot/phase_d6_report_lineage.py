from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_report_manifest import build_phase_d6_report_manifest


D6_REPORT_LINEAGE_PHASE = "D6_report_lineage_dependency_graph_v1"


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


def load_manifest(path: str | Path) -> Dict[str, Any]:
    safe_path = assert_research_path(path)
    loaded = json.loads(safe_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("d6_report_lineage_requires_manifest_object")
    return loaded


def _node_id(path: str) -> str:
    return "node:" + path


def _known_parent_types(report_type: str) -> List[str]:
    mapping = {
        "evidence_review_bundle": ["parameter_inventory", "d5_evidence_adapter", "regime_segmentation", "fill_realism_evidence"],
        "parameter_review_pack": ["parameter_inventory", "evidence_review_bundle", "guardrail_report"],
        "human_review_export": ["parameter_review_pack"],
        "lineage_report": ["manifest_report"],
    }
    return mapping.get(report_type, [])


def _nodes(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "node_id": _node_id(row["source_path"]),
            "source_path": row["source_path"],
            "report_type": row.get("report_type"),
            "detected_phase": row.get("detected_phase"),
            "reproducibility_status": row.get("reproducibility_status"),
        }
        for row in rows
    ]


def _edges(rows: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str]]:
    by_path = {row["source_path"]: row for row in rows}
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_type.setdefault(str(row.get("report_type") or ""), []).append(row)
    edges: List[Dict[str, Any]] = []
    missing: List[str] = []
    for row in rows:
        target = _node_id(row["source_path"])
        for input_path in row.get("input_paths_detected") or []:
            if input_path in by_path:
                edges.append(
                    {
                        "source_node": _node_id(input_path),
                        "target_node": target,
                        "relationship": "declared_input_path",
                        "parameter_change_allowed": False,
                    }
                )
            else:
                missing.append(input_path)
        for parent_type in _known_parent_types(str(row.get("report_type") or "")):
            for parent in by_type.get(parent_type, []):
                if parent["source_path"] == row["source_path"]:
                    continue
                edges.append(
                    {
                        "source_node": _node_id(parent["source_path"]),
                        "target_node": target,
                        "relationship": f"inferred_parent_type:{parent_type}",
                        "parameter_change_allowed": False,
                    }
                )
    dedup = []
    seen = set()
    for edge in edges:
        key = (edge["source_node"], edge["target_node"], edge["relationship"])
        if key not in seen:
            seen.add(key)
            dedup.append(edge)
    return dedup, sorted(set(missing))


def _lineage_status(rows: List[Dict[str, Any]], edges: List[Dict[str, Any]], missing: List[str], blockers: List[str]) -> str:
    if blockers:
        return "blocked"
    if not rows:
        return "insufficient_metadata"
    if missing:
        return "partial"
    if not edges and len(rows) > 1:
        return "insufficient_metadata"
    return "complete_for_supplied_reports"


def build_phase_d6_report_lineage(
    *,
    manifest_report: Optional[Dict[str, Any]] = None,
    manifest_path: str | Path | None = None,
    report_paths: Optional[Iterable[str | Path]] = None,
) -> Dict[str, Any]:
    manifest = manifest_report
    source_mode = "provided_manifest_object"
    if manifest_path is not None:
        manifest = load_manifest(manifest_path)
        source_mode = "manifest_path"
    elif manifest is None:
        manifest = build_phase_d6_report_manifest(report_paths=report_paths or [])
        source_mode = "built_from_report_paths"
    rows = list((manifest or {}).get("manifest_rows") or [])
    nodes = _nodes(rows)
    edges, missing = _edges(rows)
    source_nodes = {edge["source_node"] for edge in edges}
    target_nodes = {edge["target_node"] for edge in edges}
    blockers = list((manifest or {}).get("blockers") or [])
    return {
        "generated_at": now_iso(),
        "phase": D6_REPORT_LINEAGE_PHASE,
        "status": "d6_report_lineage_ready",
        "source_mode": source_mode,
        "source_summary": {
            "manifest_phase": (manifest or {}).get("phase"),
            "manifest_report_count": len(rows),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
        "nodes": nodes,
        "edges": edges,
        "source_reports": sorted(source_nodes),
        "derived_reports": sorted(target_nodes),
        "orphan_reports": sorted({node["node_id"] for node in nodes} - source_nodes - target_nodes),
        "missing_input_references": missing,
        "lineage_status": _lineage_status(rows, edges, missing, blockers),
        "warnings": [
            "report_lineage_descriptive_only",
            "not_report_ranking",
            "not_parameter_review",
            "not_parameter_search",
        ],
        "blockers": sorted(set(blockers)),
        **_safety_flags(),
    }


__all__ = [
    "D6_REPORT_LINEAGE_PHASE",
    "build_phase_d6_report_lineage",
    "load_manifest",
]
