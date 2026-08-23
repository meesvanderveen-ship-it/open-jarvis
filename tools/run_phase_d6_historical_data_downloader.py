#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_historical_data_downloader import execute_coinbase_historical_download, plan_historical_download  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def _parse_epoch_or_iso(value: str) -> int:
    text = str(value).strip()
    if not text:
        raise argparse.ArgumentTypeError("timestamp_must_not_be_empty")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp_must_be_epoch_or_iso8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


def main() -> int:
    parser = argparse.ArgumentParser(description="D.6 generic historical candle downloader.")
    parser.add_argument("--source", choices=["coinbase", "binance"], required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--start", type=_parse_epoch_or_iso, required=True)
    parser.add_argument("--end", type=_parse_epoch_or_iso, required=True)
    parser.add_argument("--max-chunks", type=int, default=1)
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--resume-manifest", default="")
    parser.add_argument("--allow-merge", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--report", required=True)
    parser.add_argument("--no-binance-repair", action="store_true")
    parser.add_argument("--primary-only-normal-gate", action="store_true")
    args = parser.parse_args()
    max_requests = int(args.max_requests) if args.max_requests is not None else int(args.max_chunks)

    plan = plan_historical_download(
        source=args.source,
        product=args.product,
        symbol=args.symbol or args.product.replace("-", ""),
        timeframe=args.timeframe,
        start=args.start,
        end=args.end,
        max_chunks=args.max_chunks,
        max_requests=max_requests,
        candidate_root=args.candidate_root,
        run_id=Path(args.report).stem,
        no_binance_repair=args.no_binance_repair,
        primary_only_normal_gate=args.primary_only_normal_gate,
    )
    plan["cli_options"] = {
        "dry_run": bool(args.dry_run),
        "allow_merge": bool(args.allow_merge),
        "validate_only": bool(args.validate_only),
        "resume_manifest": args.resume_manifest,
        "max_requests": max_requests,
    }
    if args.allow_merge:
        raise SystemExit("generic_downloader_cli_refuses_merge_without_explicit_validator_flow")
    content = plan
    report_type = "historical_data_download_plan_v1"
    if not args.dry_run:
        if args.validate_only:
            raise SystemExit("validate_only_requires_separate_validator_tool")
        if args.source != "coinbase":
            raise SystemExit("generic_downloader_execution_currently_supports_coinbase_only")
        from coinbase_client import CoinbaseClient  # Imported only for explicit public-candle fetch mode.

        content = execute_coinbase_historical_download(plan=plan, client=CoinbaseClient())
        content["cli_options"] = dict(plan["cli_options"])
        report_type = "historical_data_download_result_v1"
    bundle = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=[args.resume_manifest] if args.resume_manifest else [])
    write_phase_d6_report_bundle(bundle, args.report, metadata_sidecar=True)
    md = str(Path(args.report).with_suffix(".md"))
    write_phase_d6_report_bundle(bundle, md, markdown=True)
    print(json.dumps({"status": content["status"], "report": args.report, "markdown": md, "chunk_count": content.get("chunk_count") or content.get("download_plan", {}).get("chunk_count")}, indent=2))
    return 2 if str(content.get("status", "")).endswith("_blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
