#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_live_operator_runbook_pack import build_operator_started_24h_live_test_pack  # noqa: E402
from bot.phase_d6_report_bundle_writer import (  # noqa: E402
    assert_reports_d6_output_path,
    serialize_report,
)


def _run_local(command: Sequence[str]) -> Dict[str, Any]:
    proc = subprocess.run(
        list(command),
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
    }


def _capture_state_hashes() -> Dict[str, str]:
    result = _run_local(["sha256sum", "state/open_orders.json", "state/positions.json"])
    hashes: Dict[str, str] = {}
    for line in str(result.get("stdout") or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            hashes[parts[1]] = parts[0]
    return hashes


def _capture_initial_safety() -> Dict[str, Any]:
    commands: List[Sequence[str]] = [
        ["python3", "tools/show_open_orders.py", "--open-only", "--json", "--limit", "20"],
        ["python3", "tools/show_function_preservation_audit.py", "--fail-on-review"],
        ["python3", "tools/show_phase_d3_controlled_live_exits.py", "--ticker", "BTC-USDC", "--json"],
        ["sha256sum", "state/open_orders.json", "state/positions.json"],
    ]
    results = [_run_local(command) for command in commands]
    status = "pass" if all(row["returncode"] == 0 for row in results) else "blocked"
    return {
        "status": status,
        "commands": results,
        "state_hashes": _capture_state_hashes(),
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
    }


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(safe)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a report-only operator-started 24h live-test runbook pack. No Coinbase calls."
    )
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/")
    parser.add_argument("--max-notional-usdc", default="10")
    parser.add_argument("--proven-product", default="BTC-USDC")
    parser.add_argument("--skip-local-safety", action="store_true", help="Do not run local read-only safety commands.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    initial_safety = {} if args.skip_local_safety else _capture_initial_safety()
    state_hashes = dict(initial_safety.get("state_hashes") or {}) if initial_safety else {}
    report = build_operator_started_24h_live_test_pack(
        proven_product=args.proven_product,
        max_notional_usdc=args.max_notional_usdc,
        initial_safety=initial_safety,
        state_hashes=state_hashes,
    )

    if args.json_out:
        _atomic_write(Path(args.json_out), json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n")
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), serialize_report(report, markdown=True))

    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if (initial_safety.get("status") in {None, "pass"} or args.skip_local_safety) else 2


if __name__ == "__main__":
    raise SystemExit(main())
