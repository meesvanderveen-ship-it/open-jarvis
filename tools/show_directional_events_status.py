#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.adaptive_policy_lab import DIRECTIONAL_ERROR_LABELS, DIRECTIONAL_EVENT_LABELS
from bot.atomic_io import atomic_write_json
from bot.parameter_candidate_analysis import ANALYSIS_JSON_PATH
from bot.reflection_persistence import PARAMETER_PRESSURE_LEDGER_PATH, REFLECTION_LEDGER_PATH, load_reflection_events, read_jsonl_ledger


JSON_PATH = Path("reports/audits/directional-events-pipeline-audit-latest.json")
MD_PATH = Path("reports/audits/directional-events-pipeline-audit-latest.md")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _analysis_regime_counts(analysis: Dict[str, Any]) -> Dict[str, Any]:
    rows = analysis.get("parameter_analysis") if isinstance(analysis.get("parameter_analysis"), list) else []
    first = next((row for row in rows if isinstance(row, dict)), {})
    evidence = first.get("evidence") if isinstance(first.get("evidence"), dict) else {}
    counts = evidence.get("regime_counts") or evidence.get("counts_by_regime") or {}
    return counts if isinstance(counts, dict) else {}


def build_report(*, root: Path = Path(".")) -> Dict[str, Any]:
    reflections, reflection_corrupt = load_reflection_events(root)
    pressure, pressure_corrupt = read_jsonl_ledger(root / PARAMETER_PRESSURE_LEDGER_PATH)
    analysis = _load_json(root / ANALYSIS_JSON_PATH)
    validated = [row for row in reflections if row.get("validated_conclusion") is True]
    labels = Counter(str(row.get("label") or "") for row in validated)
    by_regime: Dict[str, Dict[str, int]] = defaultdict(lambda: {"validated_conclusions": 0, "directional_events": 0, "directional_error_labels": 0})
    for row in validated:
        regime = str(row.get("adaptive_market_regime") or row.get("market_regime") or "unknown")
        by_regime[regime]["validated_conclusions"] += 1
        label = str(row.get("label") or "")
        if label in DIRECTIONAL_EVENT_LABELS:
            by_regime[regime]["directional_events"] += 1
        if label in DIRECTIONAL_ERROR_LABELS:
            by_regime[regime]["directional_error_labels"] += 1
    analysis_counts = _analysis_regime_counts(analysis)
    analysis_has_directional_events = any(
        isinstance(values, dict) and int(values.get("directional_events") or 0) > 0
        for values in analysis_counts.values()
    )
    if not analysis:
        diagnosis = "candidate_analysis_missing"
    elif not analysis_counts:
        diagnosis = "missing_mapping_in_candidate_analysis"
    elif not analysis_has_directional_events and sum(labels[label] for label in DIRECTIONAL_EVENT_LABELS) > 0:
        diagnosis = "candidate_analysis_directional_events_zero_despite_validated_labels"
    else:
        diagnosis = "mapped"
    return {
        "phase": "directional_events_pipeline_audit_v1",
        "read_only": True,
        "can_authorize_execution": False,
        "can_mutate_parameters": False,
        "what_counts_as_directional_event": sorted(DIRECTIONAL_EVENT_LABELS),
        "directional_error_labels": sorted(DIRECTIONAL_ERROR_LABELS),
        "difference_directional_error_labels_vs_directional_events": "directional_error_labels are adverse or too-strict labels; directional_events also include counter-directional validated labels such as correct_avoid and false_signal_avoided.",
        "where_written": {
            "candidate_analysis_total": str(root / ANALYSIS_JSON_PATH),
            "governor_expected_fields": [
                "parameter_analysis[].evidence.total_directional_events",
                "parameter_analysis[].evidence.regime_counts[regime].directional_events",
            ],
        },
        "files_with_directional_evidence": {
            "reflection_ledger": str(root / REFLECTION_LEDGER_PATH),
            "parameter_pressure_ledger": str(root / PARAMETER_PRESSURE_LEDGER_PATH),
            "candidate_analysis": str(root / ANALYSIS_JSON_PATH),
        },
        "reflection_corrupt_lines": reflection_corrupt,
        "pressure_corrupt_lines": pressure_corrupt,
        "validated_conclusions": len(validated),
        "label_counts": dict(labels),
        "total_directional_events_from_validated_conclusions": sum(labels[label] for label in DIRECTIONAL_EVENT_LABELS),
        "total_directional_error_labels_from_validated_conclusions": sum(labels[label] for label in DIRECTIONAL_ERROR_LABELS),
        "per_regime_directional_evidence_counts": dict(sorted(by_regime.items())),
        "candidate_analysis_regime_counts": analysis_counts,
        "why_governor_sees_directional_events_zero": "The governor reads candidate/analysis regime_counts.directional_events; if those fields are absent it falls back to zero or even distribution from total_directional_events.",
        "pipeline_diagnosis": diagnosis,
        "missing_writer_mapping_or_filter": diagnosis,
        "provenance": "Counts are derived only from validated reflection conclusions and their labels; no synthetic events are created.",
    }


def render_markdown(report: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Directional Events Pipeline Audit",
            "",
            f"Diagnosis: `{report.get('pipeline_diagnosis')}`",
            f"Validated conclusions: {report.get('validated_conclusions')}",
            f"Directional events: {report.get('total_directional_events_from_validated_conclusions')}",
            f"Directional error labels: {report.get('total_directional_error_labels_from_validated_conclusions')}",
            "",
            "## Per Regime",
            json.dumps(report.get("per_regime_directional_evidence_counts") or {}, indent=2, sort_keys=True),
            "",
            "## Provenance",
            str(report.get("provenance")),
        ]
    ) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Show read-only directional events pipeline audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    report = build_report(root=root)
    atomic_write_json(root / JSON_PATH, report)
    (root / MD_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / MD_PATH).write_text(render_markdown(report), encoding="utf-8")
    if args.markdown:
        print(render_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
