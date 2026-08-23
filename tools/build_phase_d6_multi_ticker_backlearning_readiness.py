#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_multi_ticker_backlearning_readiness import (  # noqa: E402
    build_24h_live_test_readiness_v3,
    build_backlearning_parameter_candidate_scaffold,
    build_backlearning_trial_accounting_guardrails,
    build_future_multi_ticker_fetch_plan_v2,
    build_multi_ticker_backtest_readiness_matrix,
    build_multi_ticker_dataset_coverage_plan,
    build_multi_ticker_workflow_equivalence_report,
    discover_cached_candle_files,
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


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def _write_bundle(
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
    parser = argparse.ArgumentParser(
        description="Build report-only multi-ticker D.6 backlearning readiness artifacts. No Coinbase/OpenAI calls and no fetch."
    )
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--candles", action="append", default=[])
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hashes_before = _state_hashes()
    config_text = Path("bot/config.py").read_text(encoding="utf-8")
    candles = _split_csv(args.candles) or discover_cached_candle_files()
    source_paths = [
        "bot/config.py",
        args.order_events,
        "reports/d6/workflow-ticker-coverage-audit-20260601.json",
        "reports/d6/24h-readiness-bundle-20260601.json",
        *candles,
    ]

    dataset_plan = build_multi_ticker_dataset_coverage_plan(
        config_text=config_text,
        candle_paths=candles,
        order_events_path=args.order_events,
        as_of=args.as_of,
    )
    readiness_matrix = build_multi_ticker_backtest_readiness_matrix(
        config_text=config_text,
        candle_paths=candles,
        order_events_path=args.order_events,
        as_of=args.as_of,
    )
    guardrails = build_backlearning_trial_accounting_guardrails(readiness_matrix=readiness_matrix)
    scaffold = build_backlearning_parameter_candidate_scaffold(
        readiness_matrix=readiness_matrix,
        guardrails=guardrails,
    )
    equivalence = build_multi_ticker_workflow_equivalence_report(
        readiness_matrix=readiness_matrix,
        order_events_path=args.order_events,
    )
    fetch_plan = build_future_multi_ticker_fetch_plan_v2(
        dataset_coverage_plan=dataset_plan,
        as_of=args.as_of,
    )
    readiness_v3 = build_24h_live_test_readiness_v3(
        readiness_matrix=readiness_matrix,
        backlearning_scaffold=scaffold,
        workflow_equivalence=equivalence,
    )

    artifacts = [
        (
            "d6_multi_ticker_dataset_coverage_plan",
            dataset_plan,
            f"reports/d6/multi-ticker-dataset-coverage-plan-{args.date_stamp}.json",
            f"reports/d6/multi-ticker-dataset-coverage-plan-{args.date_stamp}.md",
        ),
        (
            "d6_multi_ticker_backtest_readiness_matrix",
            readiness_matrix,
            f"reports/d6/multi-ticker-backtest-readiness-matrix-{args.date_stamp}.json",
            f"reports/d6/multi-ticker-backtest-readiness-matrix-{args.date_stamp}.md",
        ),
        (
            "d6_backlearning_parameter_candidate_scaffold",
            scaffold,
            f"reports/d6/backlearning-parameter-candidate-scaffold-{args.date_stamp}.json",
            f"reports/d6/backlearning-parameter-candidate-scaffold-{args.date_stamp}.md",
        ),
        (
            "d6_backlearning_trial_accounting_guardrails",
            guardrails,
            f"reports/d6/backlearning-trial-accounting-guardrails-{args.date_stamp}.json",
            f"reports/d6/backlearning-trial-accounting-guardrails-{args.date_stamp}.md",
        ),
        (
            "d6_multi_ticker_workflow_equivalence_report",
            equivalence,
            f"reports/d6/multi-ticker-workflow-equivalence-report-{args.date_stamp}.json",
            f"reports/d6/multi-ticker-workflow-equivalence-report-{args.date_stamp}.md",
        ),
        (
            "d6_future_multi_ticker_fetch_plan_v2",
            fetch_plan,
            f"reports/d6/future-multi-ticker-fetch-plan-v2-{args.date_stamp}.json",
            f"reports/d6/future-multi-ticker-fetch-plan-v2-{args.date_stamp}.md",
        ),
        (
            "d6_24h_live_test_readiness_v3",
            readiness_v3,
            f"reports/d6/24h-live-test-readiness-v3-{args.date_stamp}.json",
            f"reports/d6/24h-live-test-readiness-v3-{args.date_stamp}.md",
        ),
    ]
    results = [
        _write_bundle(
            report_type=report_type,
            content=content,
            output=output,
            markdown_output=markdown_output,
            source_paths=source_paths,
            input_hashes=hashes_before,
        )
        for report_type, content, output, markdown_output in artifacts
    ]
    payload = {"status": "multi_ticker_backlearning_readiness_artifacts_written", "results": results}
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
