#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.phase_c_live_guard import LIVE_ENTRY_GUARD_VERSION, LIVE_ENTRY_REQUIRED_GATES
from bot.product_rules import PRODUCT_RULE_NORMALIZER_VERSION


EXPECTED = {
    "live_entry_guard_version": "wait-preview-block-v1",
    "product_rule_normalizer_version": "product-rules-v1",
    "approved_profile_effective_default_quote": "50.00",
    "live_entry_required_gates": [
        "fresh_approve_trade",
        "buy",
        "valid_trade_plan",
        "product_rules",
        "precision_normalized",
    ],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def approved_profile_default_quote(root: Path) -> str:
    profile = _load_json(root / "state/approved_parameter_profile.json")
    params = profile.get("parameters") if isinstance(profile.get("parameters"), dict) else {}
    return str(params.get("DEFAULT_QUOTE_SIZE_USDC") or "")


def latest_runtime_version_log(root: Path) -> Dict[str, Any]:
    rows = _load_jsonl(root / "logs/runtime_guard_version.jsonl")
    if rows:
        return rows[-1]
    return {}


def _versions_match(row: Dict[str, Any], default_quote: str) -> bool:
    if not row:
        return False
    gates = row.get("live_entry_required_gates") or str(row.get("LIVE_ENTRY_REQUIRED_GATES") or "").split(",")
    gates = [str(g).strip() for g in gates if str(g).strip()]
    return bool(
        row.get("live_entry_guard_version") == EXPECTED["live_entry_guard_version"]
        and row.get("product_rule_normalizer_version") == EXPECTED["product_rule_normalizer_version"]
        and str(row.get("approved_profile_effective_default_quote") or "") == default_quote == EXPECTED["approved_profile_effective_default_quote"]
        and gates == EXPECTED["live_entry_required_gates"]
    )


def build_runtime_guard_version_report(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    default_quote = approved_profile_default_quote(project_root)
    latest_log = latest_runtime_version_log(project_root)
    code_versions_ok = (
        LIVE_ENTRY_GUARD_VERSION == EXPECTED["live_entry_guard_version"]
        and PRODUCT_RULE_NORMALIZER_VERSION == EXPECTED["product_rule_normalizer_version"]
        and list(LIVE_ENTRY_REQUIRED_GATES) == EXPECTED["live_entry_required_gates"]
        and default_quote == EXPECTED["approved_profile_effective_default_quote"]
    )
    latest_seen = _versions_match(latest_log, default_quote)
    return {
        "generated_at": now_iso(),
        "phase": "runtime_guard_version_readiness_v1",
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "live_entry_guard_version": LIVE_ENTRY_GUARD_VERSION,
        "product_rule_normalizer_version": PRODUCT_RULE_NORMALIZER_VERSION,
        "approved_profile_effective_default_quote": default_quote,
        "live_entry_required_gates": list(LIVE_ENTRY_REQUIRED_GATES),
        "expected_versions": EXPECTED,
        "code_versions_match_expected": code_versions_ok,
        "latest_journal_versions_seen": latest_seen,
        "safe_runtime_loaded": bool(code_versions_ok and latest_seen),
        "runtime_proof_prepared": bool(code_versions_ok),
        "latest_runtime_guard_version_log": latest_log,
        "restart_required_to_observe_runtime_log": not latest_seen,
        "safety_policy": {
            "does_not_start_service": True,
            "does_not_restart_service": True,
            "does_not_call_coinbase": True,
            "future_runtime_must_log_versions_after_restart": True,
        },
    }


def write_reports(report: Dict[str, Any], *, root: str | Path = ".") -> None:
    project_root = Path(root)
    out_json = project_root / "reports/audits/runtime-guard-version-readiness-latest.json"
    out_md = project_root / "reports/audits/runtime-guard-version-readiness-latest.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Runtime Guard Version Readiness",
        "",
        f"- live_entry_guard_version: {report.get('live_entry_guard_version')}",
        f"- product_rule_normalizer_version: {report.get('product_rule_normalizer_version')}",
        f"- approved_profile_effective_default_quote: {report.get('approved_profile_effective_default_quote')}",
        f"- code_versions_match_expected: {report.get('code_versions_match_expected')}",
        f"- latest_journal_versions_seen: {report.get('latest_journal_versions_seen')}",
        f"- safe_runtime_loaded: {report.get('safe_runtime_loaded')}",
        f"- runtime_proof_prepared: {report.get('runtime_proof_prepared')}",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show runtime live-entry guard version readiness.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_runtime_guard_version_report(root=args.root)
    if not args.no_write:
        write_reports(report, root=args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "live_entry_guard_version={live} product_rule_normalizer_version={product} "
            "runtime_proof_prepared={prepared} safe_runtime_loaded={safe}".format(
                live=report["live_entry_guard_version"],
                product=report["product_rule_normalizer_version"],
                prepared=report["runtime_proof_prepared"],
                safe=report["safe_runtime_loaded"],
            )
        )
    return 0 if report["runtime_proof_prepared"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_runtime_guard_version_report", "write_reports", "main", "parse_args"]
