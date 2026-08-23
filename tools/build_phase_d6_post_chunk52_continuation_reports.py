#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_coinbase_candle_ingest import assert_research_path  # noqa: E402
from bot.phase_d6_dataset_quality import build_phase_d6_dataset_quality_report  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


BTC_1H_CACHE = "research_data/coinbase/candles/product=BTC-USDC/timeframe=1H/study_window=3y.json"
BTC_4H_CACHE = "research_data/coinbase/candles/product=BTC-USDC/timeframe=4H/study_window=3y.json"


def _load_json(path: str | Path) -> Any:
    safe = assert_research_path(path)
    return json.loads(safe.read_text(encoding="utf-8"))


def _content(report: Dict[str, Any]) -> Dict[str, Any]:
    return dict(report.get("content") or report)


def _rows(path: str | Path) -> List[Dict[str, Any]]:
    loaded = _load_json(path)
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _count(path: str | Path) -> int:
    return len(_rows(path))


def _starts(path: str | Path) -> List[int]:
    return sorted(int(row["start"]) for row in _rows(path) if "start" in row)


def _write_bundle(*, report_type: str, content: Dict[str, Any], output: str, sources: Iterable[str]) -> None:
    bundle = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=sources)
    write_phase_d6_report_bundle(bundle, output, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, Path(output).with_suffix(".md"), markdown=True)


def _post_chunk52_name(base: str, suffix: str) -> str:
    suffix_part = f"-{suffix}" if suffix else ""
    return f"{base}{suffix_part}-v1-20260602.json"


def _remaining_missing(*, from_start: int, end_exclusive: int, known_gap_count: int) -> int:
    downstream = max(0, (int(end_exclusive) - int(from_start)) // 3600)
    return downstream + int(known_gap_count)


def build_reports(args: argparse.Namespace) -> Dict[str, str]:
    dry_run_report = _load_json(args.dry_run_report)
    result_report = _load_json(args.result_report)
    validation_report = _load_json(args.validation_report)
    known_gap_report = _load_json(args.known_gap_report)

    dry = _content(dry_run_report)
    result = _content(result_report)
    validation = _content(validation_report)
    known_gap = _content(known_gap_report)
    fetch_result = dict(result.get("fetch_result") or {})

    cache_after = _count(BTC_1H_CACHE)
    candidate_count = int(result.get("candidate_count") or fetch_result.get("candidate_count") or 0)
    cache_before = cache_after - candidate_count if validation.get("overlap_count") == 0 else None
    chunks = list(dry.get("chunks") or fetch_result.get("requests") or [])
    last_end = max(int(chunk["end_exclusive"]) for chunk in chunks) if chunks else int(result.get("download_plan", {}).get("start") or 0)
    plan_end = int(dry.get("end") or result.get("download_plan", {}).get("end") or last_end)
    missing_known_gap_count = len(known_gap.get("missing_coinbase_starts") or known_gap.get("policy_decision", {}).get("missing_coinbase_starts") or [1761408000, 1761411600, 1761415200, 1761418800, 1761422400])
    remaining_missing = _remaining_missing(from_start=last_end, end_exclusive=plan_end, known_gap_count=missing_known_gap_count)

    btc_1h_quality = build_phase_d6_dataset_quality_report(candles_path=BTC_1H_CACHE, as_of="2026-06-02T00:00:00Z")
    btc_4h_quality = build_phase_d6_dataset_quality_report(candles_path=BTC_4H_CACHE, as_of="2026-06-02T00:00:00Z")

    source_paths = [args.dry_run_report, args.result_report, args.validation_report, args.known_gap_report, BTC_1H_CACHE, BTC_4H_CACHE]
    candidate_validation = {
        "status": validation.get("status"),
        "expected_count": validation.get("expected_count"),
        "candidate_count": validation.get("candidate_count"),
        "missing_count": validation.get("missing_count"),
        "duplicate_count": validation.get("duplicate_count"),
        "overlap_count": validation.get("overlap_count"),
        "unexpected_count": validation.get("unexpected_count"),
        "blocks_merge": validation.get("blocks_merge"),
    }
    common = {
        "research_only": True,
        "no_live_action": True,
        "state_write_performed": False,
        "config_mutation_performed": False,
        "parameter_change_allowed": False,
        "parameter_review_approved": False,
        "optimization_performed": False,
        "learning_to_execution_enabled": False,
        "normal_backtest_release": False,
        "binance_repair_performed": False,
        "synthetic_candles_added": False,
    }

    batch_label = str(args.batch_label)
    next_batch_label = str(args.next_batch_label)
    completed_label = str(args.completed_chunk_range_label)
    output_suffix = str(args.output_suffix)
    resume = {
        **common,
        "status": f"btc_usdc_1h_staged_resume_status_post_chunk52_{batch_label}_ready",
        "completed_post_chunk52_chunks": 3,
        "completed_chunk_range_label": completed_label,
        "candidate_validation": candidate_validation,
        "cache_before_count": cache_before,
        "cache_after_count": cache_after,
        "candidate_count": candidate_count,
        "next_start": last_end,
        "planned_end_exclusive": plan_end,
        "remaining_btc_usdc_1h_missing_candles_including_known_gap": remaining_missing,
        "next_safe_command": (
            "python3 tools/run_phase_d6_historical_data_downloader.py --source coinbase --product BTC-USDC "
            f"--timeframe 1H --start {last_end} --end {plan_end} --max-chunks 3 --dry-run "
            f"--candidate-root /tmp/d6_btc_usdc_1h_post_chunk52_continuation_{next_batch_label} "
            f"--resume-manifest reports/d6/{_post_chunk52_name('btc-usdc-1h-staged-resume-status-post-chunk52', output_suffix)} "
            f"--report reports/d6/btc-usdc-1h-post-chunk52-continuation-{next_batch_label}-dry-run-v1-20260602.json "
            "--no-binance-repair --primary-only-normal-gate"
        ),
    }
    quality = {
        **common,
        "status": f"post_btc_usdc_1h_post_chunk52_quality_summary_{batch_label}_ready",
        "btc_usdc_1h_cache_before_count": cache_before,
        "btc_usdc_1h_cache_after_count": cache_after,
        "btc_usdc_1h_candidate_added_count": candidate_count,
        "btc_usdc_1h_known_gap_missing_starts": known_gap.get("missing_coinbase_starts") or [1761408000, 1761411600, 1761415200, 1761418800, 1761422400],
        "btc_usdc_1h_remaining_gap_candles_including_known_gap": remaining_missing,
        "btc_usdc_1h_quality_status": btc_1h_quality.get("status"),
        "btc_usdc_1h_quality_warnings": btc_1h_quality.get("warnings", []),
        "btc_usdc_4h_quality_status": btc_4h_quality.get("status"),
        "btc_usdc_4h_quality_warnings": btc_4h_quality.get("warnings", []),
        "dataset_quality_status": "usable_with_warnings",
        "normal_backtest_decision": "blocked",
        "exploratory_backtest_decision": "allowed_with_warnings_report_only_no_parameter_evidence",
    }
    readiness = {
        **common,
        "status": f"btc_usdc_24h_readiness_post_chunk52_{batch_label}_not_ready",
        "btc_usdc_only_24h_readiness": "not_ready",
        "completed_post_chunk52_chunks": 3,
        "candidate_validation": candidate_validation,
        "dataset_quality_status": quality["dataset_quality_status"],
        "normal_backtests": "blocked",
        "exploratory_only": "allowed_with_warnings_report_only_no_parameter_evidence",
        "btc_usdc_4h_status": btc_4h_quality.get("status"),
        "blocking_reasons": [
            "BTC-USDC 1H still contains the documented chunk52 primary-source known gap",
            "BTC-USDC 1H downstream continuation is incomplete",
            "BTC-USDC 4H remains poor/known-gap blocked for normal gates",
            "normal backtests are not released",
            "future live-test ACKs are absent",
        ],
        "exact_next_safe_step": resume["next_safe_command"],
    }

    outputs = {
        "resume": f"reports/d6/{_post_chunk52_name('btc-usdc-1h-staged-resume-status-post-chunk52', output_suffix)}",
        "quality": f"reports/d6/{_post_chunk52_name('post-btc-usdc-1h-post-chunk52-quality-summary', output_suffix)}",
        "readiness": f"reports/d6/{_post_chunk52_name('24h-readiness-master-packet-post-chunk52', output_suffix)}",
    }
    _write_bundle(report_type=f"btc_usdc_1h_staged_resume_status_post_chunk52_{batch_label}_v1", content=resume, output=outputs["resume"], sources=source_paths)
    _write_bundle(report_type=f"post_btc_usdc_1h_post_chunk52_quality_summary_{batch_label}_v1", content=quality, output=outputs["quality"], sources=source_paths)
    _write_bundle(report_type=f"24h_readiness_master_packet_post_chunk52_{batch_label}_v1", content=readiness, output=outputs["readiness"], sources=source_paths)
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build post-chunk52 continuation D.6 reports. Local reports/cache only.")
    parser.add_argument("--dry-run-report", required=True)
    parser.add_argument("--result-report", required=True)
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--known-gap-report", required=True)
    parser.add_argument("--batch-label", default="batch1")
    parser.add_argument("--next-batch-label", default="batch2")
    parser.add_argument("--completed-chunk-range-label", default="chunk53_through_chunk55")
    parser.add_argument("--output-suffix", default="", help="Filename suffix after post-chunk52; defaults to no suffix for batch1.")
    args = parser.parse_args()
    if not args.output_suffix:
        args.output_suffix = ""
    return args


def main() -> int:
    print(json.dumps(build_reports(parse_args()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
