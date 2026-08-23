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

from bot.phase_d45_operator_decision_report import build_phase_d45_operator_decision_report


def _load_json(path: str | Path) -> Dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline D.4/D.5 operator decision report. Report-only; no Coinbase calls.")
    parser.add_argument("--lifecycle-fixture", required=True)
    parser.add_argument("--d4-preview-fixture", default="")
    parser.add_argument("--d4-planner-fixture", default="")
    parser.add_argument("--d5-metrics-fixture", default="")
    parser.add_argument("--operator-mode", default="decision_only", choices=["wait_only", "decision_only", "future_reprice_consideration"])
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    return build_phase_d45_operator_decision_report(
        lifecycle_event=_load_json(args.lifecycle_fixture),
        d4_preview_report=_load_json(args.d4_preview_fixture) if args.d4_preview_fixture else None,
        d4_planner_report=_load_json(args.d4_planner_fixture) if args.d4_planner_fixture else None,
        d5_metrics_report=_load_json(args.d5_metrics_fixture) if args.d5_metrics_fixture else None,
        operator_mode=args.operator_mode,
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
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
