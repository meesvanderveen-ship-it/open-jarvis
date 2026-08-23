#!/usr/bin/env python3
"""Preview or ACK-gated local completion of reconstructed protective risk."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.atomic_io import process_lock, runtime_mutation_lock_path
from bot.state_store import StateStore


PHASE = "reconstructed_position_risk_completion_v1"
RISK_REPORT = Path("reports/audits/position-risk-reconstruction-preview-latest.json")
RUNTIME_ACK_ENV = "RECONSTRUCTED_POSITION_RISK_COMPLETION_ACK"
ZERO = Decimal("0")


def _load_json(root: Path, relative: Path) -> Dict[str, Any]:
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _position_id(position: Dict[str, Any]) -> str:
    for key in ("position_id", "order_id", "source_order_id", "client_order_id"):
        value = str(position.get(key) or "").strip()
        if value:
            return value
    return ""


def _report_position(report: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    for row in report.get("positions") or []:
        if isinstance(row, dict) and str(row.get("ticker") or "").strip().upper() == ticker:
            return dict(row)
    return {}


def _evidence(report_position: Dict[str, Any]) -> Dict[str, str]:
    exposure = report_position.get("exposure") if isinstance(report_position.get("exposure"), dict) else {}
    risk = report_position.get("risk_reconstruction_preview") if isinstance(report_position.get("risk_reconstruction_preview"), dict) else {}
    return {
        "ticker": str(report_position.get("ticker") or "").strip().upper(),
        "position_id": str(report_position.get("position_id") or "").strip(),
        "base_size": str(exposure.get("base_size_local") or report_position.get("base_filled") or ""),
        "entry_price": str(exposure.get("avg_entry_price") or report_position.get("avg_entry_price") or ""),
        "current_price": str(exposure.get("current_price") or ""),
        "market_evidence_timestamp": str(exposure.get("market_evidence_timestamp") or risk.get("market_evidence_timestamp") or ""),
        "current_price_vs_stop": str(risk.get("current_price_vs_stop") or "").strip().lower(),
        "stop_price": str(risk.get("proposed_stop_price") or ""),
        "invalidation_price": str(
            risk.get("proposed_invalidation_price")
            or risk.get("proposed_invalidation")
            or risk.get("proposed_stop_price")
            or ""
        ),
    }


def _evidence_hash(evidence: Dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _with_ephemeral_market_evidence(
    evidence: Dict[str, str],
    *,
    market_price: str = "",
    market_evidence_timestamp: str = "",
) -> tuple[Dict[str, str], list[str]]:
    """Apply a caller-supplied, non-persistent market-evidence pair to a preview."""
    price_text = str(market_price or "").strip()
    timestamp_text = str(market_evidence_timestamp or "").strip()
    if not price_text and not timestamp_text:
        return evidence, []
    if not price_text or not timestamp_text:
        return evidence, ["market_evidence_override_pair_required"]

    price = _decimal(price_text)
    if price <= ZERO:
        return evidence, ["market_evidence_override_price_invalid"]

    effective = dict(evidence)
    effective["current_price"] = price_text
    effective["market_evidence_timestamp"] = timestamp_text
    stop = _decimal(effective.get("stop_price"))
    effective["current_price_vs_stop"] = "breached" if stop > ZERO and price <= stop else "above_stop"
    return effective, []


def _fresh_timestamp(value: str, *, now: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return False
        age_seconds = Decimal(str((now - parsed.astimezone(timezone.utc)).total_seconds()))
        return Decimal("0") <= age_seconds <= Decimal("900")
    except Exception:
        return False


def _state_store(root: Path) -> StateStore:
    store = StateStore()
    store.positions_file = root / "state/positions.json"
    store.cooldowns_file = root / "state/cooldowns.json"
    store.daily_file = root / "state/daily_pnl.json"
    return store


def build_risk_completion_report(
    *,
    ticker: str,
    root: Path = PROJECT_ROOT,
    apply: bool = False,
    caller_ack: str = "",
    expected_evidence_hash: str = "",
    market_price: str = "",
    market_evidence_timestamp: str = "",
    now: datetime | None = None,
) -> Dict[str, Any]:
    root = Path(root)
    selected = str(ticker or "").strip().upper()
    now = now or datetime.now(timezone.utc)
    report_position = _report_position(_load_json(root, RISK_REPORT), selected)
    evidence = _evidence(report_position)
    evidence, market_evidence_blockers = _with_ephemeral_market_evidence(
        evidence,
        market_price=market_price,
        market_evidence_timestamp=market_evidence_timestamp,
    )
    evidence_hash = _evidence_hash(evidence) if report_position else ""
    positions = _state_store(root)
    current = positions.get_position(selected) or {}
    runtime_ack = str(os.getenv(RUNTIME_ACK_ENV) or "")
    blockers: list[str] = list(market_evidence_blockers)

    if not selected:
        blockers.append("ticker_required")
    if not report_position:
        blockers.append("reconstruction_evidence_missing")
    if not current:
        blockers.append("position_not_currently_open")
    elif str(current.get("status") or "").strip().lower() not in {"open", "active"}:
        blockers.append("position_not_currently_open")
    if report_position and str(evidence.get("position_id") or "") != _position_id(current):
        blockers.append("position_id_mismatch")
    if report_position and _decimal(evidence.get("base_size")) != _decimal(current.get("position_size_base") or current.get("bot_managed_base")):
        blockers.append("position_base_mismatch")
    if report_position and _decimal(evidence.get("entry_price")) != _decimal(current.get("entry_price")):
        blockers.append("position_entry_price_mismatch")
    stop = _decimal(evidence.get("stop_price"))
    invalidation = _decimal(evidence.get("invalidation_price"))
    entry = _decimal(evidence.get("entry_price"))
    price = _decimal(evidence.get("current_price"))
    if report_position and (stop <= ZERO or invalidation <= ZERO or entry <= ZERO or stop >= entry or invalidation >= entry):
        blockers.append("reconstructed_protective_risk_invalid")
    breached = bool(evidence.get("current_price_vs_stop") == "breached" or (price > ZERO and stop > ZERO and price <= stop))
    if breached:
        blockers.append("controlled_close_route_required_stop_breached")
    if report_position and not _fresh_timestamp(evidence.get("market_evidence_timestamp", ""), now=now):
        blockers.append("market_evidence_missing_or_stale")
    if apply and not runtime_ack:
        blockers.append("runtime_ack_missing")
    if apply and str(caller_ack or "") != runtime_ack:
        blockers.append("caller_ack_missing_or_mismatch")
    if apply and str(expected_evidence_hash or "") != evidence_hash:
        blockers.append("expected_evidence_hash_mismatch")

    updates = {
        "stop_price": str(stop),
        "invalidation_price": str(invalidation),
        "protective_stop_status": "protective_stop_state_complete",
        "position_risk_incomplete": False,
        "risk_completion_evidence_hash": evidence_hash,
        "risk_completion_evidence_source": str(RISK_REPORT),
        "risk_completion_market_evidence_price": str(evidence.get("current_price") or ""),
        "risk_completion_market_evidence_timestamp": str(evidence.get("market_evidence_timestamp") or ""),
        "risk_completion_applied_at": now.isoformat(),
    }
    already_applied = bool(
        current
        and str(current.get("risk_completion_evidence_hash") or "") == evidence_hash
        and str(current.get("protective_stop_status") or "") == "protective_stop_state_complete"
        and not bool(current.get("position_risk_incomplete"))
    )
    result: Dict[str, Any] = {
        "phase": PHASE,
        "ticker": selected,
        "apply_requested": bool(apply),
        "evidence_hash": evidence_hash,
        "evidence": evidence,
        "proposed_position_updates": updates if report_position else {},
        "blockers": sorted(set(blockers)),
        "state_write_performed": False,
        "coinbase_call_attempted": False,
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "read_only": not bool(apply),
        "ephemeral_market_evidence_used": bool(str(market_price or "").strip()),
    }
    if blockers:
        result["status"] = "risk_completion_apply_blocked" if apply else "risk_completion_preview_blocked"
        return result
    if already_applied:
        result["status"] = "risk_completion_apply_idempotent_noop"
        result["read_only"] = True
        return result
    if not apply:
        result["status"] = "risk_completion_preview_ready"
        return result

    lock_owner = SimpleNamespace(path=root / "state/open_orders.json")
    with process_lock(runtime_mutation_lock_path(order_store=lock_owner)) as lock_info:
        updated = positions.upsert_position(
            selected,
            updates,
            caller_reason="reconstructed_position_risk_completion",
            evidence_status="reconstructed_protective_risk_complete",
        )
    result.update({
        "status": "risk_completion_apply_completed",
        "state_write_performed": True,
        "read_only": False,
        "mutation_lock": {"acquired": True, "reentrant": bool(lock_info.get("reentrant"))},
        "applied_position": updated,
    })
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or apply one reconstructed position risk completion.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ack", default="")
    parser.add_argument("--expected-evidence-hash", default="")
    parser.add_argument("--market-price", default="")
    parser.add_argument("--market-evidence-timestamp", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_risk_completion_report(
        ticker=args.ticker,
        apply=args.apply,
        caller_ack=args.ack,
        expected_evidence_hash=args.expected_evidence_hash,
        market_price=args.market_price,
        market_evidence_timestamp=args.market_evidence_timestamp,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
