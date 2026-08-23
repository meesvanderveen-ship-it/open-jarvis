#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.amount_cap_guard import evaluate_amount_cap_guard


BTC_RULES = {
    "product_id": "BTC-USDC",
    "price_increment": "0.01",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "quote_min_size": "1.00",
}
ADA_RULES = {
    "product_id": "ADA-USDC",
    "price_increment": "0.0001",
    "base_increment": "0.00000001",
    "quote_increment": "0.0001",
    "quote_min_size": "1.00",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _cfg_from_profile(root: Path) -> SimpleNamespace:
    profile = _load_json(root / "state/approved_parameter_profile.json")
    params = profile.get("parameters") if isinstance(profile.get("parameters"), dict) else {}
    return SimpleNamespace(
        default_quote_size_usdc=str(params.get("DEFAULT_QUOTE_SIZE_USDC") or "50.00"),
        phase_c_max_order_quote=str(params.get("PHASE_C_MAX_ORDER_QUOTE") or "100.00"),
        autonomous_max_order_quote=str(params.get("AUTONOMOUS_MAX_ORDER_QUOTE") or "100.00"),
        max_notional_usd=str(params.get("MAX_NOTIONAL_USD") or "100.00"),
    )


def build_amount_cap_compliance_report(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    cfg = _cfg_from_profile(project_root)
    existing = _load_json(project_root / "reports/audits/amount-cap-compliance-audit-latest.json")
    quote_50_btc = evaluate_amount_cap_guard(
        cfg=cfg,
        ticker="BTC-USDC",
        requested_quote="50.00",
        limit_price="65000.00",
        product_rules=BTC_RULES,
    )
    quote_20_ada = evaluate_amount_cap_guard(
        cfg=cfg,
        ticker="ADA-USDC",
        requested_quote="20.00",
        limit_price="0.1645",
        product_rules=ADA_RULES,
    )
    quote_100_01 = evaluate_amount_cap_guard(
        cfg=cfg,
        ticker="BTC-USDC",
        requested_quote="100.01",
        limit_price="65000.00",
        product_rules=BTC_RULES,
    )
    violations = []
    if not quote_50_btc["accepted"]:
        violations.append("quote_50_btc_unexpectedly_blocked")
    if quote_50_btc["normalized_base_size"] == "50.00":
        violations.append("quote_50_btc_became_base_50")
    if not quote_20_ada["accepted"]:
        violations.append("quote_20_ada_unexpectedly_blocked")
    if not quote_100_01["blockers"]:
        violations.append("quote_above_100_not_blocked")
    inherited_violations = existing.get("violations") if isinstance(existing.get("violations"), list) else []
    return {
        "generated_at": now_iso(),
        "phase": "amount_cap_compliance_v2",
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "configured": {
            "approved_profile_default_quote": str(getattr(cfg, "default_quote_size_usdc")),
            "default_quote": str(getattr(cfg, "default_quote_size_usdc")),
            "max_entry_quote": str(getattr(cfg, "phase_c_max_order_quote")),
            "autonomous_max_order_quote": str(getattr(cfg, "autonomous_max_order_quote")),
            "max_notional": str(getattr(cfg, "max_notional_usd")),
        },
        "observed_max_requested_quote": existing.get("observed_max_requested_quote"),
        "observed_max_filled_quote": existing.get("observed_max_filled_quote"),
        "observed_max_base_size": existing.get("observed_max_base_size"),
        "checks": {
            "quote_50_btc": quote_50_btc,
            "quote_20_ada": quote_20_ada,
            "quote_100_01": quote_100_01,
        },
        "violations": [*inherited_violations, *violations],
        "conclusion": "confirmed_violation" if inherited_violations or violations else "no_confirmed_amount_cap_violation",
        "safety_policy": {
            "quote_caps_are_authoritative": True,
            "base_size_can_exceed_quote_numerically_for_low_price_assets": True,
            "base_size_must_not_equal_quote_for_high_price_assets": True,
        },
    }


def write_report(report: Dict[str, Any], *, root: str | Path = ".") -> None:
    project_root = Path(root)
    out_json = project_root / "reports/audits/amount-cap-compliance-audit-latest.json"
    out_md = project_root / "reports/audits/amount-cap-compliance-audit-latest.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Amount Cap Compliance Audit",
        "",
        f"- conclusion: {report.get('conclusion')}",
        f"- approved_profile_default_quote: {(report.get('configured') or {}).get('approved_profile_default_quote')}",
        f"- max_entry_quote: {(report.get('configured') or {}).get('max_entry_quote')}",
        f"- violations: {len(report.get('violations') or [])}",
        f"- quote_50_btc_base: {((report.get('checks') or {}).get('quote_50_btc') or {}).get('normalized_base_size')}",
        f"- quote_20_ada_base: {((report.get('checks') or {}).get('quote_20_ada') or {}).get('normalized_base_size')}",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only amount/cap compliance.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_amount_cap_compliance_report(root=args.root)
    if args.write:
        write_report(report, root=args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"conclusion={report['conclusion']} violations={len(report['violations'])}")
    return 0 if not report["violations"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_amount_cap_compliance_report", "write_report", "main", "parse_args"]
