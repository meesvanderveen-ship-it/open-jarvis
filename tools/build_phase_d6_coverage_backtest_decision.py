#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_coverage_backtest_decision import build_coverage_backtest_decision_from_paths  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def _write(
    *,
    content: Dict[str, Any],
    output: str,
    markdown_output: str,
    source_paths: List[str],
) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(
        report_type="d6_coverage_backtest_decision_v1",
        content=content,
        source_paths=source_paths,
    )
    result = write_phase_d6_report_bundle(report, output, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, markdown_output, markdown=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 coverage/backtest decision report. No live actions.")
    parser.add_argument("--coverage-report", default="reports/d6/multi-ticker-dataset-coverage-plan-refresh-v9-20260601.json")
    parser.add_argument("--quality-report", default="reports/d6/post-fetch-dataset-quality-summary-v9-20260601.json")
    parser.add_argument("--expansion-report", default="reports/d6/bounded-candle-coverage-expansion-result-v9-20260601.json")
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--output", default="reports/d6/coverage-backtest-decision-v1-20260601.json")
    parser.add_argument("--markdown-output", default="reports/d6/coverage-backtest-decision-v1-20260601.md")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_paths = [args.coverage_report, args.quality_report, args.expansion_report]
    content = build_coverage_backtest_decision_from_paths(
        coverage_report_path=args.coverage_report,
        quality_report_path=args.quality_report,
        expansion_report_path=args.expansion_report,
        as_of=args.as_of,
    )
    result = _write(
        content=content,
        output=args.output,
        markdown_output=args.markdown_output,
        source_paths=source_paths,
    )
    payload = {
        "status": "coverage_backtest_decision_written",
        "output": args.output,
        "markdown_output": args.markdown_output,
        "result": result,
        "coverage_completeness": content["coverage_completeness"],
        "backtest_decision": content["backtest_decision"],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
