#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_live_test_readiness import build_phase_d6_live_test_readiness_report  # noqa: E402
from bot.phase_d6_report_bundle_writer import (  # noqa: E402
    build_phase_d6_report_bundle,
    write_phase_d6_report_bundle,
)


def _run(args: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=PROJECT_ROOT, text=True, capture_output=True, check=True)


#: De bestanden waarvan de hash als bewijs in het rapport komt.
_HASHED_STATE_FILES = ("state/open_orders.json", "state/positions.json")


def _state_hashes() -> Dict[str, str]:
    """SHA-256 van de statusbestanden, als bewijs dat er niets gemuteerd is.

    Werd berekend met het externe commando `sha256sum`. Dat bestaat niet op
    Windows, waardoor dit rapport daar altijd afbrak op een FileNotFoundError,
    en het gaf een foutcode zodra een van beide bestanden nog niet bestond --
    wat op een verse installatie normaal is. hashlib doet hetzelfde op elk
    platform en rapporteert een ontbrekend bestand in plaats van te crashen.
    """
    hashes: Dict[str, str] = {}
    for relative in _HASHED_STATE_FILES:
        path = PROJECT_ROOT / relative
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            digest = "file_absent"
        except OSError as exc:
            digest = f"unreadable:{type(exc).__name__}"
        hashes[relative] = digest
    return hashes


def _environment_summary() -> Dict[str, object]:
    bwrap_path = shutil.which("bwrap")
    return {
        "bwrap_on_path": bool(bwrap_path),
        "bwrap_path": bwrap_path,
        "system_package_mutation_performed": False,
    }


def _load_optional_json(path: str) -> Dict[str, object]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 report-only future live-test readiness report from approved local checks. No Coinbase calls."
    )
    parser.add_argument("--governance-bundle", default="", help="Optional reports/d6 governance bundle JSON")
    parser.add_argument("--readiness-regression-status", default="", help="Optional latest selected readiness regression status")
    parser.add_argument("--readiness-regression-tests-passed", type=int, default=0)
    parser.add_argument("--readiness-regression-command", default="")
    parser.add_argument("--output", default="", help="Optional JSON output path under reports/d6/")
    parser.add_argument("--markdown-output", default="", help="Optional Markdown output path under reports/d6/")
    parser.add_argument("--metadata-sidecar", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hashes_before = _state_hashes()
    open_orders = json.loads(
        _run([sys.executable, "tools/show_open_orders.py", "--open-only", "--json", "--limit", "20"]).stdout
    )
    function_audit_text = _run([sys.executable, "tools/show_function_preservation_audit.py", "--fail-on-review"]).stdout
    d3_report = json.loads(
        _run([sys.executable, "tools/show_phase_d3_controlled_live_exits.py", "--ticker", "BTC-USDC", "--json"]).stdout
    )
    hashes_after = _state_hashes()
    source_paths = ["docs/CODEX_PROJECT_ROADMAP.md", "docs/CODEX_PROJECT_CONTEXT.md", "logs/order_events.jsonl"]
    governance_bundle = _load_optional_json(args.governance_bundle)
    if args.governance_bundle:
        source_paths.append(args.governance_bundle)
    readiness = build_phase_d6_live_test_readiness_report(
        open_orders_report=open_orders,
        function_audit_text=function_audit_text,
        d3_controlled_exits_report=d3_report,
        state_hashes_before=hashes_before,
        state_hashes_after=hashes_after,
        governance_bundle_report=governance_bundle,
        environment_summary=_environment_summary(),
        regression_summary={
            "status": args.readiness_regression_status,
            "tests_passed": args.readiness_regression_tests_passed,
            "command": args.readiness_regression_command,
        }
        if args.readiness_regression_status
        else {},
    )
    report = build_phase_d6_report_bundle(
        report_type="d6_live_test_readiness",
        content=readiness,
        source_paths=source_paths,
        input_hashes=hashes_before,
    )
    if args.output:
        result = write_phase_d6_report_bundle(
            report,
            args.output,
            metadata_sidecar=args.metadata_sidecar,
        )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    if args.markdown_output:
        write_phase_d6_report_bundle(
            report,
            args.markdown_output,
            markdown=True,
            metadata_sidecar=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
