#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d5_learning_log import (
    build_phase_d5_learning_event,
    build_phase_d5_learning_log_report,
    events_to_jsonl,
)


def _load_json(path: str | Path) -> Dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline D.5 structured learning-log exporter. Report-only; no Coinbase calls.")
    parser.add_argument("--lifecycle-fixture", action="append", default=[])
    parser.add_argument("--d5-metrics-fixture", action="append", default=[])
    parser.add_argument("--d45-fixture", action="append", default=[])
    parser.add_argument("--historical-fixture", action="append", default=[])
    parser.add_argument("--d4-decision-fixture", action="append", default=[])
    parser.add_argument("--event-type", default="execution_observation")
    parser.add_argument("--operator-decision", default="")
    parser.add_argument("--final-outcome", default="")
    parser.add_argument("--source", default="fixture_export")
    parser.add_argument("--window-start", default="")
    parser.add_argument("--window-end", default="")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def _fixture_at(paths: List[str], index: int) -> Dict[str, Any]:
    return _load_json(paths[index]) if index < len(paths) else {}


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    count = max(
        1,
        len(args.lifecycle_fixture),
        len(args.d5_metrics_fixture),
        len(args.d45_fixture),
        len(args.historical_fixture),
        len(args.d4_decision_fixture),
    )
    events = [
        build_phase_d5_learning_event(
            event_type=args.event_type,
            lifecycle_event=_fixture_at(args.lifecycle_fixture, index),
            d5_metrics_report=_fixture_at(args.d5_metrics_fixture, index),
            d45_report=_fixture_at(args.d45_fixture, index),
            historical_report=_fixture_at(args.historical_fixture, index),
            d4_decision_report=_fixture_at(args.d4_decision_fixture, index),
            operator_decision=args.operator_decision,
            final_outcome=args.final_outcome,
            source=args.source,
            now=datetime.now(timezone.utc),
        )
        for index in range(count)
    ]
    return build_phase_d5_learning_log_report(
        events=events,
        window_start=args.window_start,
        window_end=args.window_end,
        source=args.source,
        now=datetime.now(timezone.utc),
    )


def main() -> int:
    args = parse_args()
    report = build_report(args)
    text = (
        events_to_jsonl(report["events"])
        if args.jsonl
        else json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    )
    if args.output:
        Path(args.output).write_text(text + ("\n" if text else ""), encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

