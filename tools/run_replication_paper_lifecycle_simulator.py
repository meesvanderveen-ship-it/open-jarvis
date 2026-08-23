#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402
from bot.phase_replication_paper_lifecycle_simulator import (  # noqa: E402
    demo_fixture_events,
    render_paper_lifecycle_markdown,
    run_paper_lifecycle_simulation,
)


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def _load_events(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("events"), list):
        rows = payload["events"]
    else:
        raise ValueError("fixture JSON must be a list of events or an object with an events list")
    events: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("fixture events must be JSON objects")
        events.append(row)
    return events


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local paper-only replication lifecycle simulator. No replication enabling, Coinbase calls or state writes."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="Run built-in demo lifecycle fixture sequence.")
    source.add_argument("--fixture-json", default="", help="Path to fixture JSON list or object with events list.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown instead of JSON.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    events = demo_fixture_events() if args.demo else _load_events(Path(args.fixture_json))
    report = run_paper_lifecycle_simulation(events)
    if args.json_out:
        _atomic_write(
            Path(args.json_out),
            (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8"),
        )
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), (render_paper_lifecycle_markdown(report) + "\n").encode("utf-8"))
    if args.markdown:
        print(render_paper_lifecycle_markdown(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
