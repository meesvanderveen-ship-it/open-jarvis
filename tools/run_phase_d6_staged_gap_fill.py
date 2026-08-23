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

from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402
from bot.phase_d6_staged_gap_fill import (  # noqa: E402
    build_backtest_readiness_v15,
    build_master_packet_v15,
    build_preflight_v5,
    build_quality_summary_v15,
    build_staged_gap_fill_plan,
    execute_staged_gap_fill,
)


def _split_csv(values: List[str] | None) -> List[str]:
    out: List[str] = []
    for value in values or []:
        out.extend(part.strip() for part in str(value).split(",") if part.strip())
    return out


def _load_command_plan(path: str) -> Dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    content = loaded.get("content") if isinstance(loaded, dict) else None
    return dict(content) if isinstance(content, dict) else dict(loaded)


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
    staged_plan: Dict[str, Any],
    staged_result: Dict[str, Any] | None,
    source_paths: List[str],
    as_of: str,
) -> List[Dict[str, Any]]:
    quality = build_quality_summary_v15(as_of=as_of)
    backtest = build_backtest_readiness_v15(quality_summary=quality, staged_result=staged_result)
    preflight = build_preflight_v5(quality_summary=quality, staged_plan=staged_plan, staged_result=staged_result)
    master = build_master_packet_v15(
        staged_plan=staged_plan,
        staged_result=staged_result,
        quality_summary=quality,
        backtest_readiness=backtest,
        preflight_v5=preflight,
    )
    specs = [
        ("d6_staged_btc_1h_gap_fill_plan_v1", staged_plan, "staged-btc-1h-gap-fill-plan-v1"),
        ("d6_post_staged_gap_fill_dataset_quality_summary_v15", quality, "post-staged-gap-fill-dataset-quality-summary-v15"),
        ("d6_exploratory_only_backtest_readiness_refresh_v15", backtest, "exploratory-only-backtest-readiness-refresh-v15"),
        ("d6_24h_live_test_preflight_runner_v5", preflight, "24h-live-test-preflight-runner-v5"),
        ("d6_24h_readiness_master_packet_v15", master, "24h-readiness-master-packet-v15"),
    ]
    if staged_result:
        specs.insert(1, ("d6_staged_btc_1h_gap_fill_result_v1", staged_result, "staged-btc-1h-gap-fill-result-v1"))
    return [
        _write(report_type=report_type, content=content, stem=stem, date_stamp=date_stamp, source_paths=source_paths)
        for report_type, content, stem in specs
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run staged BTC-USDC D.6 gap-fill with exact candidate validation.")
    parser.add_argument("--gap-plan", default="reports/d6/gap-fill-command-plan-v1-20260601.json")
    parser.add_argument("--candidate-root", default="/tmp/d6_staged_btc_1h_gap_fill_20260601_v15")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--tickers", action="append", default=["BTC-USDC"])
    parser.add_argument("--timeframes", action="append", default=["1D,4H,1H"])
    parser.add_argument("--subrun-max-chunks", type=int, default=10)
    parser.add_argument("--execution-max-chunks", type=int, default=25)
    parser.add_argument("--subrun-id", action="append", default=[])
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
    command_plan = _load_command_plan(args.gap_plan)
    staged_plan = build_staged_gap_fill_plan(
        command_plan=command_plan,
        candidate_root=args.candidate_root,
        tickers=_split_csv(args.tickers),
        timeframes=_split_csv(args.timeframes),
        subrun_max_chunks=args.subrun_max_chunks,
        execution_max_chunks=args.execution_max_chunks,
    )
    staged_result: Dict[str, Any] | None = None
    if args.fetch:
        from coinbase_client import CoinbaseClient  # Imported only for explicit research fetch mode.

        staged_result = execute_staged_gap_fill(
            plan=staged_plan,
            client=CoinbaseClient(),
            subrun_ids=_split_csv(args.subrun_id) or None,
            merge=not args.no_merge,
        )
    report: Dict[str, Any] = {"staged_plan": staged_plan, "staged_result": staged_result}
    if args.write_reports:
        source_paths = ["bot/config.py", args.gap_plan, *_candle_paths()]
        report["write_results"] = _write_reports(
            date_stamp=args.date_stamp,
            staged_plan=staged_plan,
            staged_result=staged_result,
            source_paths=source_paths,
            as_of=args.as_of,
        )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if not staged_result or staged_result.get("status") == "staged_gap_fill_result_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
