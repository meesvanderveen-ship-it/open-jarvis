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

from bot.phase_d5_execution_metrics import build_phase_d5_execution_metrics_report


def _load_json(path: str | Path) -> Dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline D.5 execution metrics report. Analysis-only; no Coinbase calls.")
    parser.add_argument("--lifecycle-fixture", required=True)
    parser.add_argument("--plan-fixture", required=True)
    parser.add_argument("--market-fixture", default="")
    parser.add_argument("--fills-fixture", default="")
    parser.add_argument("--d4-decision-fixture", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    return build_phase_d5_execution_metrics_report(
        lifecycle_event=_load_json(args.lifecycle_fixture),
        plan_fields=_load_json(args.plan_fixture),
        market_refs=_load_json(args.market_fixture) if args.market_fixture else None,
        fills=_load_json(args.fills_fixture) if args.fills_fixture else None,
        d4_decision=_load_json(args.d4_decision_fixture) if args.d4_decision_fixture else None,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
