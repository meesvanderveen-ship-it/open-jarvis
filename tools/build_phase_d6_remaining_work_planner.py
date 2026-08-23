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

from bot.phase_d6_remaining_work_planner import (  # noqa: E402
    build_backlearning_review_package,
    build_backtest_execution_package,
    build_data_fetch_ack_package,
    build_future_24h_readiness_master_packet,
    build_multi_ticker_workflow_completion_checklist,
    build_remaining_workflow_execution_plan,
    build_remaining_workflow_todo_overview,
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
    output: str,
    markdown_output: str,
    source_paths: List[str],
    input_hashes: Dict[str, str],
) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(
        report_type=report_type,
        content=content,
        source_paths=source_paths,
        input_hashes=input_hashes,
    )
    result = write_phase_d6_report_bundle(report, output, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, markdown_output, markdown=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 remaining workflow planner packages. No live actions.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hashes = _state_hashes()
    paths = {
        "dataset": "reports/d6/multi-ticker-dataset-coverage-plan-20260601.json",
        "matrix": "reports/d6/multi-ticker-backtest-readiness-matrix-20260601.json",
        "scaffold": "reports/d6/backlearning-parameter-candidate-scaffold-20260601.json",
        "guardrails": "reports/d6/backlearning-trial-accounting-guardrails-20260601.json",
        "equivalence": "reports/d6/multi-ticker-workflow-equivalence-report-20260601.json",
        "readiness_v3": "reports/d6/24h-live-test-readiness-v3-20260601.json",
    }
    dataset = _load(paths["dataset"])
    matrix = _load(paths["matrix"])
    scaffold = _load(paths["scaffold"])
    guardrails = _load(paths["guardrails"])
    equivalence = _load(paths["equivalence"])
    readiness_v3 = _load(paths["readiness_v3"])
    overview = build_remaining_workflow_todo_overview(
        dataset_plan=dataset,
        readiness_matrix=matrix,
        scaffold=scaffold,
        guardrails=guardrails,
        workflow_equivalence=equivalence,
        readiness_v3=readiness_v3,
    )
    execution = build_remaining_workflow_execution_plan(overview=overview)
    fetch = build_data_fetch_ack_package(dataset_plan=dataset)
    backtest = build_backtest_execution_package(readiness_matrix=matrix)
    backlearning = build_backlearning_review_package(scaffold=scaffold, guardrails=guardrails)
    checklist = build_multi_ticker_workflow_completion_checklist(readiness_matrix=matrix, workflow_equivalence=equivalence)
    master = build_future_24h_readiness_master_packet(
        overview=overview,
        execution_plan=execution,
        fetch_package=fetch,
        backtest_package=backtest,
        backlearning_package=backlearning,
        checklist=checklist,
        readiness_v3=readiness_v3,
        state_hashes=hashes,
    )
    source_paths = list(paths.values()) + ["docs/CODEX_PROJECT_CONTEXT.md", "docs/CODEX_PROJECT_ROADMAP.md"]
    specs = [
        ("d6_remaining_workflow_todo_overview", overview, "remaining-workflow-todo-overview"),
        ("d6_remaining_workflow_execution_plan", execution, "remaining-workflow-execution-plan"),
        ("d6_data_fetch_ack_package", fetch, "data-fetch-ack-package"),
        ("d6_backtest_execution_package", backtest, "backtest-execution-package"),
        ("d6_backlearning_review_package", backlearning, "backlearning-review-package"),
        ("d6_multi_ticker_workflow_completion_checklist", checklist, "multi-ticker-workflow-completion-checklist"),
        ("d6_future_24h_readiness_master_packet", master, "future-24h-readiness-master-packet"),
    ]
    results = [
        _write(
            report_type=report_type,
            content=content,
            output=f"reports/d6/{name}-{args.date_stamp}.json",
            markdown_output=f"reports/d6/{name}-{args.date_stamp}.md",
            source_paths=source_paths,
            input_hashes=hashes,
        )
        for report_type, content, name in specs
    ]
    print(json.dumps({"status": "remaining_workflow_planner_reports_written", "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
