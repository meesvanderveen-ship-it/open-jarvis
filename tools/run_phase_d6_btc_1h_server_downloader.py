#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_btc_1h_server_downloader import (  # noqa: E402
    build_24h_readiness_v38,
    build_progress_report,
    build_quality_summary_v1,
    build_resume_status_v11,
    build_server_download_plan,
    execute_server_download,
)
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


DEFAULT_RESUME = "reports/d6/btc-1h-staged-resume-status-v10-20260601.json"


def _write_pair(report_type: str, content: Dict[str, Any], stem: str, *, source_paths: Iterable[str | Path]) -> Tuple[str, str]:
    bundle = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=source_paths)
    json_path = Path("reports/d6") / f"{stem}.json"
    md_path = Path("reports/d6") / f"{stem}.md"
    write_phase_d6_report_bundle(bundle, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, md_path, markdown=True)
    return str(json_path), str(md_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Server-safe BTC-USDC 1H research gap downloader.")
    parser.add_argument("--resume-status", default=DEFAULT_RESUME)
    parser.add_argument("--candidate-root", default="/tmp/d6_btc_1h_server_downloader_v1_20260602")
    parser.add_argument("--max-chunks", type=int, default=30)
    parser.add_argument("--phase-size", type=int, default=3)
    parser.add_argument("--checkpoint-interval-chunks", type=int, default=9)
    parser.add_argument("--cooldown-seconds", type=float, default=2.0)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--binance-reference", action="store_true")
    parser.add_argument("--skip-safety-checks", action="store_true")
    args = parser.parse_args()

    source_paths = [
        args.resume_status,
        "reports/d6/btc-1h-adaptive-staged-gap-fill-v36-v37-20260601.json",
        "reports/d6/post-btc-1h-staged-quality-summary-v36-v37-20260601.json",
        "reports/d6/24h-readiness-master-packet-v36-v37-20260601.json",
    ]
    plan = build_server_download_plan(
        resume_status_path=args.resume_status,
        candidate_root=args.candidate_root,
        max_chunks=args.max_chunks,
        phase_size=args.phase_size,
        checkpoint_interval_chunks=args.checkpoint_interval_chunks,
        cooldown_seconds=args.cooldown_seconds,
        binance_reference=args.binance_reference,
    )
    outputs = []
    outputs.extend(
        _write_pair(
            "btc_1h_server_download_plan_v1",
            plan,
            "btc-1h-server-download-plan-v1-20260602",
            source_paths=source_paths,
        )
    )
    result = None
    if args.fetch:
        from bot.coinbase_client import CoinbaseClient  # noqa: E402

        safety_hook = (lambda **_: {"status": "safety_checks_skipped_for_test", "results": []}) if args.skip_safety_checks else None
        kwargs: Dict[str, Any] = {
            "plan": plan,
            "coinbase_client": CoinbaseClient(),
            "cwd": PROJECT_ROOT,
            "merge": not args.no_merge,
            "binance_reference": args.binance_reference,
        }
        if safety_hook is not None:
            kwargs["run_safety_checks"] = safety_hook
        result = execute_server_download(**kwargs)
    progress = build_progress_report(plan=plan, result=result)
    outputs.extend(
        _write_pair(
            "btc_1h_server_download_progress_v1",
            progress,
            "btc-1h-server-download-progress-v1-20260602",
            source_paths=[*source_paths, "reports/d6/btc-1h-server-download-plan-v1-20260602.json"],
        )
    )
    if result is not None:
        resume = build_resume_status_v11(plan=plan, result=result)
        quality = build_quality_summary_v1(result=result)
        readiness = build_24h_readiness_v38(result=result, quality=quality, resume=resume)
        outputs.extend(
            _write_pair(
                "btc_1h_server_download_result_v1",
                result,
                "btc-1h-server-download-result-v1-20260602",
                source_paths=[*source_paths, "reports/d6/btc-1h-server-download-progress-v1-20260602.json"],
            )
        )
        outputs.extend(
            _write_pair(
                "btc_1h_staged_resume_status_v11",
                resume,
                "btc-1h-staged-resume-status-v11-20260602",
                source_paths=["reports/d6/btc-1h-server-download-result-v1-20260602.json"],
            )
        )
        outputs.extend(
            _write_pair(
                "post_btc_1h_server_download_quality_summary_v1",
                quality,
                "post-btc-1h-server-download-quality-summary-v1-20260602",
                source_paths=[
                    "reports/d6/btc-1h-server-download-result-v1-20260602.json",
                    "reports/d6/post-btc-1h-staged-quality-summary-v36-v37-20260601.json",
                ],
            )
        )
        outputs.extend(
            _write_pair(
                "24h_readiness_master_packet_v38_server_download",
                readiness,
                "24h-readiness-master-packet-v38-server-download-20260602",
                source_paths=[
                    "reports/d6/btc-1h-server-download-result-v1-20260602.json",
                    "reports/d6/post-btc-1h-server-download-quality-summary-v1-20260602.json",
                ],
            )
        )
    print(
        json.dumps(
            {
                "status": "btc_1h_server_downloader_finished" if result is not None else "btc_1h_server_downloader_plan_written",
                "fetch": bool(args.fetch),
                "completed_chunk_count": (result or {}).get("completed_chunk_count", 0),
                "gap_closed": (result or {}).get("gap_closed"),
                "stop_reason": (result or {}).get("stop_reason", ""),
                "outputs": outputs,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 2 if result is not None and result.get("stop_reason") else 0


if __name__ == "__main__":
    raise SystemExit(main())
