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

from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402
from bot.phase_d6_v17_v18_readiness import (  # noqa: E402
    build_backlearning_scaffold_v3,
    build_btc_1h_staged_rate_limited_plan_v2,
    build_btc_4h_gap_policy_v2,
    build_master_packet_v17_v18,
    build_preflight_v7,
    build_rate_limit_policy_v2,
)


DEFAULT_4H_DIAGNOSTIC = "reports/d6/btc-4h-surgical-gap-diagnostic-v1-20260601.json"
DEFAULT_1H_POLICY = "reports/d6/btc-1h-staged-gap-policy-v1-20260601.json"
DEFAULT_QUALITY = "reports/d6/post-staged-gap-fill-dataset-quality-summary-v15-20260601.json"
DEFAULT_BACKLEARNING_V2 = "reports/d6/backlearning-scaffold-v2-20260601.json"
DEFAULT_MASTER_V16 = "reports/d6/24h-readiness-master-packet-v16-20260601.json"


def _load_report_content(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    content = loaded.get("content") if isinstance(loaded, dict) else None
    return dict(content) if isinstance(content, dict) else dict(loaded)


def _write_pair(report_type: str, content: Dict[str, Any], stem: str, *, source_paths: Iterable[str]) -> Tuple[str, str]:
    bundle = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=source_paths)
    json_path = f"reports/d6/{stem}.json"
    md_path = f"reports/d6/{stem}.md"
    write_phase_d6_report_bundle(bundle, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, md_path, markdown=True)
    return json_path, md_path


def build_reports(args: argparse.Namespace) -> Dict[str, Any]:
    source_paths = [
        args.btc_4h_diagnostic,
        args.btc_1h_policy,
        args.quality_summary,
        args.backlearning_v2,
        args.master_v16,
        "bot/phase_d6_rate_limited_public_fetch.py",
        "bot/phase_d6_v17_v18_readiness.py",
    ]
    diagnostic = _load_report_content(args.btc_4h_diagnostic)
    one_h_policy = _load_report_content(args.btc_1h_policy)
    quality = _load_report_content(args.quality_summary)

    gap_policy = build_btc_4h_gap_policy_v2(diagnostic=diagnostic)
    rate_policy = build_rate_limit_policy_v2()
    one_h_plan = build_btc_1h_staged_rate_limited_plan_v2(
        one_h_policy=one_h_policy,
        gap_policy=gap_policy,
        candidate_root=args.candidate_root,
    )
    backlearning = build_backlearning_scaffold_v3(quality_summary=quality, gap_policy=gap_policy)
    preflight = build_preflight_v7(
        quality_summary=quality,
        gap_policy=gap_policy,
        one_h_plan=one_h_plan,
        backlearning=backlearning,
    )
    master = build_master_packet_v17_v18(
        quality_summary=quality,
        gap_policy=gap_policy,
        rate_limit_policy=rate_policy,
        one_h_plan=one_h_plan,
        backlearning=backlearning,
        preflight=preflight,
    )

    outputs = []
    for report_type, content, stem in [
        ("d6_btc_4h_gap_policy_v2", gap_policy, "btc-4h-gap-policy-v2-20260601"),
        ("d6_rate_limit_public_fetch_policy_v2", rate_policy, "rate-limit-public-fetch-policy-v2-20260601"),
        ("d6_btc_1h_staged_rate_limited_plan_v2", one_h_plan, "btc-1h-staged-rate-limited-plan-v2-20260601"),
        ("d6_backlearning_scaffold_v3", backlearning, "backlearning-scaffold-v3-20260601"),
        ("d6_24h_live_test_preflight_runner_v7", preflight, "24h-live-test-preflight-runner-v7-20260601"),
        ("d6_24h_readiness_master_packet_v17_v18", master, "24h-readiness-master-packet-v17-v18-20260601"),
    ]:
        json_path, md_path = _write_pair(report_type, content, stem, source_paths=source_paths)
        outputs.append({"report_type": report_type, "json": json_path, "markdown": md_path, "status": content.get("status")})

    return {
        "status": "phase_d6_v17_v18_readiness_reports_written",
        "outputs": outputs,
        "fetch_executed": False,
        "merge_executed": False,
        "state_write_performed": False,
        "btc_4h_gap_policy_status": gap_policy.get("status"),
        "btc_1h_execution_decision": one_h_plan.get("execution_decision"),
        "quality_summary": quality.get("summary") or quality,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 v17/v18 research-only readiness reports. No Coinbase calls.")
    parser.add_argument("--btc-4h-diagnostic", default=DEFAULT_4H_DIAGNOSTIC)
    parser.add_argument("--btc-1h-policy", default=DEFAULT_1H_POLICY)
    parser.add_argument("--quality-summary", default=DEFAULT_QUALITY)
    parser.add_argument("--backlearning-v2", default=DEFAULT_BACKLEARNING_V2)
    parser.add_argument("--master-v16", default=DEFAULT_MASTER_V16)
    parser.add_argument("--candidate-root", default="/tmp/d6_btc_1h_staged_v17_v18")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_reports(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(result["status"])
        print("btc_4h_gap_policy_status:", result["btc_4h_gap_policy_status"])
        print("btc_1h_execution_decision:", result["btc_1h_execution_decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
