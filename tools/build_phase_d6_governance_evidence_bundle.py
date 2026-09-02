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

from bot.phase_d6_governance_evidence_bundle import build_phase_d6_governance_evidence_bundle  # noqa: E402
from bot.phase_d6_report_bundle_writer import (  # noqa: E402
    build_phase_d6_report_bundle,
    serialize_report,
    write_phase_d6_report_bundle,
)


def _run(args: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=PROJECT_ROOT, text=True, capture_output=True, check=True)


#: De bestanden waarvan de hash als bewijs in de bundel komt.
_HASHED_STATE_FILES = ("state/open_orders.json", "state/positions.json")


def _state_hashes() -> Dict[str, str]:
    """SHA-256 van de statusbestanden, als bewijs dat er niets gemuteerd is.

    Werd berekend door het externe commando `sha256sum`. Dat bestaat niet op
    Windows, waardoor dit hele hulpprogramma daar altijd afbrak op een
    FileNotFoundError. Bovendien gaf `sha256sum` een foutcode zodra een van de
    twee bestanden nog niet bestond -- wat op een verse installatie normaal is,
    voordat er ooit een order geweest is. Beide gevallen leverden een kale
    traceback op in plaats van een bruikbaar rapport.

    hashlib doet exact hetzelfde, op elk platform, en een ontbrekend bestand
    wordt als zodanig gerapporteerd in plaats van als crash.
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


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def _environment_summary() -> Dict[str, object]:
    bwrap_path = shutil.which("bwrap")
    return {
        "bwrap_on_path": bool(bwrap_path),
        "bwrap_path": bwrap_path,
        "package_mutation_performed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 report-only governance/evidence bundle from approved local checks. No Coinbase calls."
    )
    parser.add_argument("--evidence-input", action="append", default=["logs/order_events.jsonl"])
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
    bundle = build_phase_d6_governance_evidence_bundle(
        open_orders_report=open_orders,
        function_audit_text=function_audit_text,
        d3_controlled_exits_report=d3_report,
        state_hashes_before=hashes_before,
        state_hashes_after=hashes_after,
        evidence_input_paths=_split_csv(args.evidence_input),
        environment_summary=_environment_summary(),
    )
    report = build_phase_d6_report_bundle(
        report_type="d6_governance_evidence_bundle",
        content=bundle,
        source_paths=_split_csv(args.evidence_input) + ["docs/CODEX_PROJECT_ROADMAP.md"],
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
