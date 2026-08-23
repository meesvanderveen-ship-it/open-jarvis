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

from bot.phase_d6_btc_gap_fill_runner import (  # noqa: E402
    build_backtest_readiness_v14,
    build_btc_gap_fill_runner_plan,
    build_candidate_validator_summary,
    build_master_packet_v14,
    build_preflight_v4,
    build_quality_summary_v14,
    execute_btc_gap_fill_runner,
    load_gap_fill_command_plan,
)
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def _split_csv(values: List[str] | None) -> List[str]:
    out: List[str] = []
    for value in values or []:
        out.extend(part.strip() for part in str(value).split(",") if part.strip())
    return out


def _candle_paths() -> List[str]:
    root = PROJECT_ROOT / "research_data/coinbase/candles"
    return sorted(str(path.relative_to(PROJECT_ROOT)) for path in root.glob("product=*/timeframe=*/study_window=3y.json"))


def _write(*, report_type: str, content: Dict[str, Any], stem: str, date_stamp: str, source_paths: List[str]) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=source_paths)
    json_path = f"reports/d6/{stem}-{date_stamp}.json"
    md_path = f"reports/d6/{stem}-{date_stamp}.md"
    result = write_phase_d6_report_bundle(report, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, md_path, markdown=True)
    return result


def _write_reports(
    *,
    date_stamp: str,
    runner_plan: Dict[str, Any],
    runner_result: Dict[str, Any] | None,
    source_paths: List[str],
    as_of: str,
) -> List[Dict[str, Any]]:
    validator = build_candidate_validator_summary(runner_result=runner_result, runner_plan=runner_plan)
    quality = build_quality_summary_v14(as_of=as_of)
    backtest = build_backtest_readiness_v14(quality_summary=quality, runner_result=runner_result)
    preflight = build_preflight_v4(quality_summary=quality, runner_result=runner_result)
    master = build_master_packet_v14(
        validator_summary=validator,
        runner_plan=runner_plan,
        runner_result=runner_result,
        quality_summary=quality,
        backtest_readiness=backtest,
        preflight_v4=preflight,
    )
    specs = [
        ("d6_candidate_coverage_validator_v1", validator, "candidate-coverage-validator-v1"),
        ("d6_btc_gap_fill_runner_v1", runner_plan, "btc-gap-fill-runner-v1"),
        ("d6_post_btc_gap_fill_dataset_quality_summary_v14", quality, "post-btc-gap-fill-dataset-quality-summary-v14"),
        ("d6_exploratory_only_backtest_readiness_refresh_v14", backtest, "exploratory-only-backtest-readiness-refresh-v14"),
        ("d6_24h_live_test_preflight_runner_v4", preflight, "24h-live-test-preflight-runner-v4"),
        ("d6_24h_readiness_master_packet_v14", master, "24h-readiness-master-packet-v14"),
    ]
    if runner_result:
        specs.insert(2, ("d6_btc_gap_fill_result_v1", runner_result, "btc-gap-fill-result-v1"))
    return [
        _write(report_type=report_type, content=content, stem=stem, date_stamp=date_stamp, source_paths=source_paths)
        for report_type, content, stem in specs
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC-USDC D.6 smallest-first gap-fill runner.")
    parser.add_argument("--gap-plan", default="reports/d6/gap-fill-command-plan-v1-20260601.json")
    parser.add_argument("--candidate-root", default="/tmp/d6_btc_gap_fill_20260601_v14")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--timeframes", action="append", default=["1D,4H"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--write-reports", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fetch and args.dry_run:
        raise SystemExit("--fetch and --dry-run are mutually exclusive")
    command_plan = load_gap_fill_command_plan(args.gap_plan)
    runner_plan = build_btc_gap_fill_runner_plan(
        command_plan=command_plan,
        candidate_root=args.candidate_root,
        timeframes=_split_csv(args.timeframes),
    )
    runner_result: Dict[str, Any] | None = None
    if args.fetch:
        from coinbase_client import CoinbaseClient  # Imported only for explicit research fetch mode.

        runner_result = execute_btc_gap_fill_runner(
            runner_plan=runner_plan,
            client=CoinbaseClient(),
            merge=not args.no_merge,
        )
    report: Dict[str, Any] = {"runner_plan": runner_plan, "runner_result": runner_result}
    if args.write_reports:
        source_paths = ["bot/config.py", args.gap_plan, *_candle_paths()]
        report["write_results"] = _write_reports(
            date_stamp=args.date_stamp,
            runner_plan=runner_plan,
            runner_result=runner_result,
            source_paths=source_paths,
            as_of=args.as_of,
        )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if not runner_result or runner_result.get("status") == "btc_gap_fill_result_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
