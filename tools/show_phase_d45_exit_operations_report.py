#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d45_exit_operations_report import build_phase_d45_exit_operations_report


def _load_json(path: str | Path) -> Dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report-only D.45 exit operations hardening report. No Coinbase calls, no state writes."
    )
    parser.add_argument("--local-d45-fixture", required=True)
    parser.add_argument("--lifecycle-poll-fixture", default="")
    parser.add_argument("--d5-metrics-fixture", default="")
    parser.add_argument("--market-mid", default="")
    parser.add_argument("--explicit-operator-request", action="store_true")
    parser.add_argument("--lifecycle-evidence-hint", action="store_true")
    parser.add_argument("--enough-time-elapsed", action="store_true")
    parser.add_argument("--updated-lifecycle-check-useful", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    local_report = _load_json(args.local_d45_fixture)
    return build_phase_d45_exit_operations_report(
        local_report=local_report,
        lifecycle_poll_report=_load_json(args.lifecycle_poll_fixture) if args.lifecycle_poll_fixture else None,
        d5_metrics_report=_load_json(args.d5_metrics_fixture) if args.d5_metrics_fixture else None,
        market_mid=args.market_mid,
        explicit_operator_request=bool(args.explicit_operator_request),
        lifecycle_evidence_hint=bool(args.lifecycle_evidence_hint),
        enough_time_elapsed=bool(args.enough_time_elapsed),
        updated_lifecycle_check_useful=bool(args.updated_lifecycle_check_useful),
        now=datetime.now(timezone.utc),
    )


def main() -> int:
    args = parse_args()
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 2 if report.get("recommended_operator_action") == "blocked_p0_review_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
