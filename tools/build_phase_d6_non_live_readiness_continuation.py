#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_non_live_readiness_continuation import (  # noqa: E402
    build_backlearning_evidence_aggregator,
    build_gap_closure_tracker,
    build_master_readiness_refresh_v2,
    build_next_ack_decision_packet,
    validate_prefetch_plan,
)
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def _run(args: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=PROJECT_ROOT, text=True, capture_output=True, check=True)


def _state_hashes() -> Dict[str, str]:
    result = _run(["sha256sum", "state/open_orders.json", "state/positions.json"])
    hashes: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            hashes[parts[1]] = parts[0]
    return hashes


def _load(path: str) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write(
    *,
    report_type: str,
    content: Dict[str, Any],
    output_stem: str,
    date_stamp: str,
    source_paths: List[str],
    input_hashes: Dict[str, str],
) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(
        report_type=report_type,
        content=content,
        source_paths=source_paths,
        input_hashes=input_hashes,
    )
    json_path = f"reports/d6/{output_stem}-{date_stamp}.json"
    md_path = f"reports/d6/{output_stem}-{date_stamp}.md"
    result = write_phase_d6_report_bundle(report, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, md_path, markdown=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 non-live readiness continuation reports. No fetch/live actions.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = {
        "dataset_plan": "reports/d6/multi-ticker-dataset-coverage-plan-20260601.json",
        "readiness_matrix": "reports/d6/multi-ticker-backtest-readiness-matrix-20260601.json",
        "backlearning_review": "reports/d6/backlearning-review-package-20260601.json",
        "guardrails": "reports/d6/backlearning-trial-accounting-guardrails-20260601.json",
        "workflow_equivalence": "reports/d6/multi-ticker-workflow-equivalence-report-20260601.json",
        "fetch_plan": "reports/d6/future-multi-ticker-fetch-plan-v2-20260601.json",
        "checklist": "reports/d6/multi-ticker-workflow-completion-checklist-20260601.json",
        "remaining_overview": "reports/d6/remaining-workflow-todo-overview-20260601.json",
    }
    loaded = {name: _load(path) for name, path in paths.items()}
    state_hashes = _state_hashes()
    prefetch = validate_prefetch_plan(fetch_plan=loaded["fetch_plan"], dataset_plan=loaded["dataset_plan"])
    evidence = build_backlearning_evidence_aggregator(
        dataset_plan=loaded["dataset_plan"],
        readiness_matrix=loaded["readiness_matrix"],
        backlearning_review=loaded["backlearning_review"],
        guardrails=loaded["guardrails"],
        workflow_equivalence=loaded["workflow_equivalence"],
    )
    gap = build_gap_closure_tracker(
        checklist=loaded["checklist"],
        readiness_matrix=loaded["readiness_matrix"],
        workflow_equivalence=loaded["workflow_equivalence"],
    )
    ack = build_next_ack_decision_packet()
    master = build_master_readiness_refresh_v2(
        prefetch_validation=prefetch,
        evidence_aggregator=evidence,
        gap_tracker=gap,
        ack_packet=ack,
        remaining_overview=loaded["remaining_overview"],
        state_hashes=state_hashes,
    )
    source_paths = list(paths.values()) + ["docs/CODEX_PROJECT_CONTEXT.md", "docs/CODEX_PROJECT_ROADMAP.md"]
    specs = [
        ("d6_prefetch_validation_report", prefetch, "prefetch-validation-report"),
        ("d6_backlearning_evidence_aggregator", evidence, "backlearning-evidence-aggregator"),
        ("d6_multi_ticker_gap_closure_tracker", gap, "multi-ticker-gap-closure-tracker"),
        ("d6_next_ack_decision_packet", ack, "next-ack-decision-packet"),
        ("d6_master_readiness_refresh_v2", master, "master-readiness-refresh-v2"),
    ]
    results = [
        _write(
            report_type=report_type,
            content=content,
            output_stem=stem,
            date_stamp=args.date_stamp,
            source_paths=source_paths,
            input_hashes=state_hashes,
        )
        for report_type, content, stem in specs
    ]
    payload = {"status": "d6_non_live_readiness_continuation_reports_written", "results": results}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
