"""ACK-gated local reconciliation for the 2026-06-19 ETH/AVAX/SOL closes.

This module deliberately has no Coinbase mutation capability.  It only reads
terminal order/fill evidence and, after a narrow acknowledgement gate, writes
the two local state documents through a recoverable transaction journal.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from bot.atomic_io import atomic_write_json
from bot.coinbase_order_snapshot import fetch_coinbase_order_snapshot_with_diagnostics
from bot.order_store import OPEN_ORDER_STATUSES


PHASE = "controlled_position_close_reconciliation_v1"
REQUIRED_ACK = "APPLY_CONTROLLED_CLOSE_RECONCILIATION_ETH_AVAX_SOL_20260619"
REQUIRED_CONFIRMATION_FLAG = "--i-understand-this-updates-local-filled-close-state"
SOURCE_REPORT_DEFAULT = Path("reports/live_runs/risk-incomplete-controlled-close-result.json")
POSITIONS_DEFAULT = Path("state/positions.json")
OPEN_ORDERS_DEFAULT = Path("state/open_orders.json")
JOURNAL_DEFAULT = Path("state/controlled_position_close_reconciliation.journal.json")
BASE_TOLERANCE = Decimal("0.00000001")
ZERO = Decimal("0")

CONTROLLED_CLOSE_TARGETS: Tuple[Dict[str, str], ...] = (
    {
        "ticker": "ETH-USDC",
        "client_order_id": "controlled-close-ETHUSDC-20260619143855",
        "exchange_order_id": "ec7c6a86-79e5-4ba3-a262-6a170e6d355c",
        "expected_base": "0.01419647",
    },
    {
        "ticker": "AVAX-USDC",
        "client_order_id": "controlled-close-AVAXUSDC-20260619143856",
        "exchange_order_id": "f8eb04d0-04d8-4772-8cf8-2679ceb1149a",
        "expected_base": "3.67647058",
    },
    {
        "ticker": "SOL-USDC",
        "client_order_id": "controlled-close-SOLUSDC-20260619143856",
        "exchange_order_id": "88969c2a-b7b9-47e0-8f61-9bd9446bf825",
        "expected_base": "0.3485292",
    },
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        text = str(value).strip()
        return Decimal(text or default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_json(path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "missing"
    except Exception as exc:
        return {}, f"invalid_json:{type(exc).__name__}"
    if not isinstance(payload, dict):
        return {}, "not_object"
    return payload, None


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _value(snapshot: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    raw = _as_dict(snapshot.get("raw_order"))
    fills_summary = _as_dict(snapshot.get("fills_summary"))
    for key in keys:
        for source in (snapshot, raw, fills_summary):
            value = source.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
    return default


def _fees(snapshot: Mapping[str, Any]) -> Tuple[str, bool]:
    raw = _as_dict(snapshot.get("raw_order"))
    commission = _as_dict(raw.get("commission_detail_total"))
    for value in (
        snapshot.get("fees"),
        snapshot.get("total_fees"),
        raw.get("total_fees"),
        raw.get("fees"),
        raw.get("fee"),
        commission.get("total_commission"),
    ):
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        return str(_to_decimal(value)), True
    return "", False


def _fill_rows(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    summary = _as_dict(snapshot.get("fills_summary"))
    fills = summary.get("fills")
    if not isinstance(fills, list):
        fills = snapshot.get("fills")
    return [dict(row) for row in fills or [] if isinstance(row, Mapping)]


def _fill_count(snapshot: Mapping[str, Any]) -> int:
    value = _value(snapshot, "fill_count", "number_of_fills", default=0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalized_fill_rows(snapshot: Mapping[str, Any]) -> List[Dict[str, str]]:
    rows = [
        {
            "base_size": str(row.get("base_size") or row.get("size") or ""),
            "quote_size": str(row.get("quote_size") or ""),
            "price": str(row.get("price") or ""),
        }
        for row in _fill_rows(snapshot)
    ]
    return sorted(rows, key=lambda row: (row["price"], row["base_size"], row["quote_size"]))


def _remaining_size(snapshot: Mapping[str, Any]) -> Decimal:
    return _to_decimal(_value(snapshot, "remaining_size", "remaining_base", "leaves_quantity", default="0"))


def _canonical_evidence(target: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    fees, fees_recorded = _fees(snapshot)
    return {
        "ticker": _normalize_ticker(target.get("ticker")),
        "client_order_id": str(target.get("client_order_id") or ""),
        "exchange_order_id": str(target.get("exchange_order_id") or ""),
        "expected_base": str(target.get("expected_base") or "0"),
        "product_id": _normalize_ticker(_value(snapshot, "ticker", "product_id", "product")),
        "side": str(_value(snapshot, "side") or "").strip().upper(),
        "raw_status": str(_value(snapshot, "raw_status", "status") or "").strip().upper(),
        "normalized_status": str(snapshot.get("normalized_status") or "").strip().lower(),
        "settled": _as_bool(_value(snapshot, "settled", default=False)),
        "remaining_size": str(_remaining_size(snapshot)),
        "filled_base": str(_to_decimal(_value(snapshot, "filled_base", "filled_size"))),
        "filled_quote": str(_to_decimal(_value(snapshot, "filled_quote", "filled_value"))),
        "avg_fill_price": str(_to_decimal(_value(snapshot, "avg_fill_price", "average_filled_price"))),
        "fees": fees,
        "fees_recorded": fees_recorded,
        "fill_count": _fill_count(snapshot),
        "fill_rows": _normalized_fill_rows(snapshot),
    }


def _audit_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep the report useful without persisting account identifiers or raw fills."""
    fees, fees_recorded = _fees(snapshot)
    return {
        "coinbase_call_attempted": bool(snapshot.get("coinbase_call_attempted")),
        "coinbase_call_succeeded": bool(snapshot.get("coinbase_call_succeeded")),
        "coinbase_snapshot_unavailable": bool(snapshot.get("coinbase_snapshot_unavailable")),
        "coinbase_error_type": str(snapshot.get("coinbase_error_type") or ""),
        "coinbase_error_stage": str(snapshot.get("coinbase_error_stage") or ""),
        "client_order_id": str(_value(snapshot, "client_order_id") or ""),
        "exchange_order_id": str(_value(snapshot, "exchange_order_id", "order_id") or ""),
        "product_id": _normalize_ticker(_value(snapshot, "ticker", "product_id", "product")),
        "side": str(_value(snapshot, "side") or "").strip().upper(),
        "raw_status": str(_value(snapshot, "raw_status", "status") or "").strip().upper(),
        "normalized_status": str(snapshot.get("normalized_status") or "").strip().lower(),
        "settled": _as_bool(_value(snapshot, "settled", default=False)),
        "remaining_size": str(_remaining_size(snapshot)),
        "filled_base": str(_to_decimal(_value(snapshot, "filled_base", "filled_size"))),
        "filled_quote": str(_to_decimal(_value(snapshot, "filled_quote", "filled_value"))),
        "avg_fill_price": str(_to_decimal(_value(snapshot, "avg_fill_price", "average_filled_price"))),
        "fees": fees,
        "fees_recorded": fees_recorded,
        "fill_count": _fill_count(snapshot),
        "fills": _normalized_fill_rows(snapshot),
        "blockers": list(snapshot.get("blockers") or []),
    }


def validate_terminal_fill_snapshot(target: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a Coinbase snapshot without mutating local or Coinbase state."""
    target = _as_dict(target)
    snapshot = _as_dict(snapshot)
    blockers: List[str] = []
    target_ticker = _normalize_ticker(target.get("ticker"))
    target_client = str(target.get("client_order_id") or "").strip()
    target_order = str(target.get("exchange_order_id") or "").strip()
    expected_base = _to_decimal(target.get("expected_base"), "0")

    if snapshot.get("coinbase_call_succeeded") is False or snapshot.get("coinbase_snapshot_unavailable") is True:
        blockers.append("coinbase_snapshot_unavailable")
    if str(_value(snapshot, "client_order_id") or "").strip() != target_client:
        blockers.append("client_order_id_mismatch")
    actual_order_id = str(_value(snapshot, "exchange_order_id", "order_id") or "").strip()
    if actual_order_id != target_order:
        blockers.append("exchange_order_id_mismatch")
    if _normalize_ticker(_value(snapshot, "ticker", "product_id", "product")) != target_ticker:
        blockers.append("product_id_mismatch")
    if str(_value(snapshot, "side") or "").strip().upper() != "SELL":
        blockers.append("side_not_sell")
    raw_status = str(_value(snapshot, "raw_status", "status") or "").strip().upper()
    if raw_status != "FILLED" or str(snapshot.get("normalized_status") or "").strip().lower() != "filled":
        blockers.append("terminal_status_not_filled")
    if not _as_bool(_value(snapshot, "settled", default=False)):
        blockers.append("order_not_settled")
    if _remaining_size(snapshot) != ZERO:
        blockers.append("remaining_size_nonzero")

    filled_base = _to_decimal(_value(snapshot, "filled_base", "filled_size"), "0")
    if expected_base <= ZERO or abs(filled_base - expected_base) > BASE_TOLERANCE:
        blockers.append("filled_base_mismatch")
    raw_order = _as_dict(snapshot.get("raw_order"))
    raw_filled_value = raw_order.get("filled_size", raw_order.get("filled_base"))
    if raw_filled_value is not None and str(raw_filled_value).strip():
        raw_filled_base = _to_decimal(raw_filled_value, "0")
        if abs(raw_filled_base - expected_base) > BASE_TOLERANCE and "filled_base_mismatch" not in blockers:
            blockers.append("filled_base_mismatch")
    fill_rows = _fill_rows(snapshot)
    fill_count = _fill_count(snapshot)
    if not fill_rows or fill_count <= 0:
        blockers.append("fill_evidence_missing")
    filled_quote = _to_decimal(_value(snapshot, "filled_quote", "filled_value"), "0")
    avg_fill_price = _to_decimal(_value(snapshot, "avg_fill_price", "average_filled_price"), "0")
    if filled_quote <= ZERO:
        blockers.append("filled_quote_missing")
    if avg_fill_price <= ZERO:
        blockers.append("avg_fill_price_missing")
    fees, fees_recorded = _fees(snapshot)
    if not fees_recorded:
        blockers.append("fees_missing")

    evidence = _canonical_evidence(target, snapshot)
    return {
        "ticker": target_ticker,
        "client_order_id": target_client,
        "exchange_order_id": target_order,
        "expected_base": str(expected_base),
        "valid": not blockers,
        "blockers": blockers,
        "evidence": evidence,
        "evidence_hash": _stable_hash(evidence),
        "filled_base": str(filled_base),
        "filled_quote": str(filled_quote),
        "avg_fill_price": str(avg_fill_price),
        "fees": fees,
        "fill_count": fill_count,
    }


def _source_order_rows(source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    execution = _as_dict(source.get("execution_result"))
    response = _as_dict(execution.get("coinbase_response"))
    rows = response.get("orders")
    return [dict(row) for row in rows or [] if isinstance(row, Mapping)]


def validate_source_report(source: Mapping[str, Any], targets: Sequence[Mapping[str, Any]]) -> List[str]:
    blockers: List[str] = []
    rows = _source_order_rows(source)
    expected_tickers = {_normalize_ticker(target.get("ticker")) for target in targets}
    for target in targets:
        target_client = str(target.get("client_order_id") or "")
        target_order = str(target.get("exchange_order_id") or "")
        target_ticker = _normalize_ticker(target.get("ticker"))
        matches = [row for row in rows if str(row.get("client_order_id") or "") == target_client]
        if len(matches) != 1:
            blockers.append(f"source_order_missing_or_duplicate:{target_ticker}")
            continue
        row = matches[0]
        nested = _as_dict(_as_dict(row.get("coinbase_response")).get("success_response"))
        source_order_id = str(row.get("order_id") or nested.get("order_id") or "")
        source_ticker = _normalize_ticker(row.get("ticker") or nested.get("product_id"))
        if source_order_id != target_order:
            blockers.append(f"source_order_id_mismatch:{target_ticker}")
        if source_ticker != target_ticker:
            blockers.append(f"source_product_id_mismatch:{target_ticker}")
        if str(nested.get("side") or row.get("side") or "").strip().upper() != "SELL":
            blockers.append(f"source_side_not_sell:{target_ticker}")
    selected = {_normalize_ticker(value) for value in source.get("positions_to_close") or []}
    if selected != expected_tickers:
        blockers.append("source_apply_scope_mismatch")
    excluded = {_normalize_ticker(value) for value in source.get("positions_excluded_from_close") or []}
    if "ADA-USDC" not in excluded or "ADA-USDC" in expected_tickers:
        blockers.append("source_ada_scope_invalid")
    return blockers


def _open_sell_conflicts(open_orders: Mapping[str, Any], tickers: Iterable[str]) -> Dict[str, List[str]]:
    wanted = {_normalize_ticker(ticker) for ticker in tickers}
    orders = open_orders.get("orders") if isinstance(open_orders.get("orders"), Mapping) else {}
    conflicts: Dict[str, List[str]] = {ticker: [] for ticker in wanted}
    for key, raw in orders.items():
        order = _as_dict(raw)
        ticker = _normalize_ticker(order.get("ticker") or order.get("product_id"))
        if ticker not in wanted:
            continue
        status = str(order.get("status") or "").strip().lower()
        side = str(order.get("side") or "").strip().upper()
        if side == "SELL" and status in OPEN_ORDER_STATUSES:
            conflicts[ticker].append(str(order.get("client_order_id") or key))
    return {ticker: values for ticker, values in conflicts.items() if values}


def _existing_reconciliation_records(open_orders: Mapping[str, Any], targets: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    orders = open_orders.get("orders") if isinstance(open_orders.get("orders"), Mapping) else {}
    result: Dict[str, Dict[str, Any]] = {}
    for target in targets:
        client_order_id = str(target.get("client_order_id") or "")
        record = _as_dict(orders.get(client_order_id))
        if record:
            result[_normalize_ticker(target.get("ticker"))] = record
    return result


def _local_state_blockers(
    *,
    positions: Mapping[str, Any],
    open_orders: Mapping[str, Any],
    validations: Sequence[Mapping[str, Any]],
) -> Tuple[List[str], bool]:
    blockers: List[str] = []
    targets = [validation.get("evidence") or {} for validation in validations]
    tickers = [_normalize_ticker(target.get("ticker")) for target in targets]
    conflicts = _open_sell_conflicts(open_orders, tickers)
    for ticker in sorted(conflicts):
        blockers.append(f"conflicting_open_sell:{ticker}")

    existing = _existing_reconciliation_records(open_orders, targets)
    all_matching = True
    for validation in validations:
        ticker = _normalize_ticker(validation.get("ticker"))
        evidence_hash = str(validation.get("evidence_hash") or "")
        position = _as_dict(positions.get(ticker))
        order = existing.get(ticker, {})
        position_hash = str(position.get("evidence_hash") or position.get("controlled_position_close_reconciliation_evidence_hash") or "")
        order_hash = str(order.get("evidence_hash") or order.get("controlled_position_close_reconciliation_evidence_hash") or "")
        position_closed = str(position.get("status") or "").strip().lower() == "closed"
        order_final = (
            str(order.get("status") or "").strip().lower() == "filled"
            and str(order.get("side") or "").strip().upper() == "SELL"
            and str(order.get("exchange_order_id") or order.get("order_id") or "").strip() == str(validation.get("exchange_order_id") or "")
        )
        matching = bool(position_closed and position_hash == evidence_hash and order_final and order_hash == evidence_hash)
        all_matching = all_matching and matching
        if matching:
            continue
        if not position:
            blockers.append(f"position_missing:{ticker}")
        elif position_closed:
            blockers.append(f"duplicate_reconciliation_evidence_hash_mismatch:{ticker}")
        elif position_hash and position_hash != evidence_hash:
            blockers.append(f"position_existing_reconciliation_evidence_hash_mismatch:{ticker}")
        if order and order_hash != evidence_hash:
            blockers.append(f"order_existing_reconciliation_evidence_hash_mismatch:{ticker}")
        elif position_closed or order:
            blockers.append(f"incomplete_prior_reconciliation_evidence:{ticker}")
    return blockers, all_matching


def _final_order_record(validation: Mapping[str, Any], *, reconciled_at: str, source_report: Path) -> Dict[str, Any]:
    evidence = _as_dict(validation.get("evidence"))
    return {
        "client_order_id": str(validation.get("client_order_id") or ""),
        "exchange_order_id": str(validation.get("exchange_order_id") or ""),
        "order_id": str(validation.get("exchange_order_id") or ""),
        "ticker": str(validation.get("ticker") or ""),
        "product_id": str(validation.get("ticker") or ""),
        "side": "SELL",
        "status": "filled",
        "phase": PHASE,
        "close_reason": "controlled_position_close_filled",
        "close_source": "controlled_position_close_reconciliation",
        "filled_base": str(validation.get("filled_base") or "0"),
        "filled_size": str(validation.get("filled_base") or "0"),
        "filled_quote": str(validation.get("filled_quote") or "0"),
        "avg_fill_price": str(validation.get("avg_fill_price") or "0"),
        "fees": str(validation.get("fees") or "0"),
        "total_fees": str(validation.get("fees") or "0"),
        "fill_count": int(validation.get("fill_count") or 0),
        "remaining_size": "0",
        "remaining_base": "0",
        "settled": True,
        "closed_at": reconciled_at,
        "finalized_at": reconciled_at,
        "reconciled_at": reconciled_at,
        "evidence_hash": str(validation.get("evidence_hash") or ""),
        "controlled_position_close_reconciliation_evidence_hash": str(validation.get("evidence_hash") or ""),
        "controlled_position_close_reconciliation_evidence": evidence,
        "source_report": str(source_report),
    }


def _closed_position(position: Mapping[str, Any], validation: Mapping[str, Any], *, reconciled_at: str) -> Dict[str, Any]:
    merged = dict(position)
    merged.update({
        "ticker": str(validation.get("ticker") or merged.get("ticker") or ""),
        "status": "closed",
        "position_size_base": "0",
        "position_size_quote": "0",
        "bot_managed_base": "0",
        "reserved_base_open_exit_orders": "0",
        "monitoring_enabled": False,
        "last_side": "SELL",
        "close_time": reconciled_at,
        "closed_at": reconciled_at,
        "close_reason": "controlled_position_close_filled",
        "close_source": "controlled_position_close_reconciliation",
        "exchange_order_id": str(validation.get("exchange_order_id") or ""),
        "client_order_id": str(validation.get("client_order_id") or ""),
        "filled_base": str(validation.get("filled_base") or "0"),
        "filled_quote": str(validation.get("filled_quote") or "0"),
        "avg_fill_price": str(validation.get("avg_fill_price") or "0"),
        "fees": str(validation.get("fees") or "0"),
        "fill_count": int(validation.get("fill_count") or 0),
        "evidence_hash": str(validation.get("evidence_hash") or ""),
        "controlled_position_close_reconciliation_evidence_hash": str(validation.get("evidence_hash") or ""),
        "controlled_position_close_reconciliation_evidence": _as_dict(validation.get("evidence")),
        "updated_at": reconciled_at,
        "last_heartbeat_status": "closed",
        "last_heartbeat_at": reconciled_at,
        "last_heartbeat_reason": "controlled_position_close_reconciliation",
    })
    return merged


def _write_recoverable_transaction(
    *,
    positions_path: Path,
    open_orders_path: Path,
    journal_path: Path,
    original_positions: Mapping[str, Any],
    original_open_orders: Mapping[str, Any],
    updated_positions: Mapping[str, Any],
    updated_open_orders: Mapping[str, Any],
) -> Dict[str, str]:
    """Atomically write each state file with a durable pre-write backup/journal."""
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    backup_dir = journal_path.parent / "backups" / f"controlled-position-close-reconciliation-{run_id}"
    positions_backup = backup_dir / "positions.before.json"
    open_orders_backup = backup_dir / "open_orders.before.json"
    atomic_write_json(positions_backup, dict(original_positions), sort_keys=True)
    atomic_write_json(open_orders_backup, dict(original_open_orders), sort_keys=True)
    journal: Dict[str, Any] = {
        "phase": PHASE,
        "transaction_id": run_id,
        "status": "prepared_recoverable",
        "created_at": _now_iso(),
        "positions_path": str(positions_path),
        "open_orders_path": str(open_orders_path),
        "positions_backup": str(positions_backup),
        "open_orders_backup": str(open_orders_backup),
        "before_hashes": {
            "positions": _stable_hash(original_positions),
            "open_orders": _stable_hash(original_open_orders),
        },
        "after_hashes": {
            "positions": _stable_hash(updated_positions),
            "open_orders": _stable_hash(updated_open_orders),
        },
        "manual_recovery": "Restore both *.before.json backups if this journal is not completed.",
    }
    atomic_write_json(journal_path, journal, sort_keys=True)
    atomic_write_json(open_orders_path, dict(updated_open_orders), sort_keys=True)
    journal["status"] = "open_orders_applied_recoverable"
    journal["open_orders_applied_at"] = _now_iso()
    atomic_write_json(journal_path, journal, sort_keys=True)
    atomic_write_json(positions_path, dict(updated_positions), sort_keys=True)
    journal["status"] = "completed"
    journal["completed_at"] = _now_iso()
    atomic_write_json(journal_path, journal, sort_keys=True)
    return {
        "journal_path": str(journal_path),
        "positions_backup": str(positions_backup),
        "open_orders_backup": str(open_orders_backup),
    }


def _journal_blocks_apply(journal_path: Path) -> Optional[str]:
    if not journal_path.exists():
        return None
    journal, error = _read_json(journal_path)
    if error:
        return "recovery_journal_unreadable"
    if str(journal.get("phase") or "") != PHASE:
        return "recovery_journal_foreign_or_invalid"
    if str(journal.get("status") or "") != "completed":
        return "recovery_journal_incomplete_manual_recovery_required"
    return None


def reconcile_controlled_position_closes(
    *,
    mode: str = "check",
    ack: str = "",
    confirmation: bool = False,
    coinbase_client: Any = None,
    source_report_path: str | Path = SOURCE_REPORT_DEFAULT,
    positions_path: str | Path = POSITIONS_DEFAULT,
    open_orders_path: str | Path = OPEN_ORDERS_DEFAULT,
    journal_path: str | Path = JOURNAL_DEFAULT,
    targets: Sequence[Mapping[str, Any]] = CONTROLLED_CLOSE_TARGETS,
) -> Dict[str, Any]:
    """Run a read-only check or an ACK-gated local reconciliation apply.

    Coinbase access is limited to ``get_order`` and ``get_recent_fills_for_order``
    through the supplied client.  No method in this module submits, cancels or
    replaces an exchange order.
    """
    selected_mode = str(mode or "check").strip().lower()
    target_rows = [_as_dict(target) for target in targets]
    source_path = Path(source_report_path)
    state_positions_path = Path(positions_path)
    state_open_orders_path = Path(open_orders_path)
    state_journal_path = Path(journal_path)
    report: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": PHASE,
        "mode": selected_mode,
        "required_ack": REQUIRED_ACK,
        "ack_matches_required": str(ack or "").strip() == REQUIRED_ACK,
        "confirmation_provided": bool(confirmation),
        "required_confirmation_flag": REQUIRED_CONFIRMATION_FLAG,
        "targets": target_rows,
        "ada_excluded": all(_normalize_ticker(target.get("ticker")) != "ADA-USDC" for target in target_rows),
        "source_report_path": str(source_path),
        "state_write_performed": False,
        "positions_mutated": False,
        "open_orders_mutated": False,
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "new_order_submit_attempted": False,
        "cancel_attempted": False,
        "replace_attempted": False,
        "blockers": [],
        "validations": [],
    }
    if selected_mode not in {"check", "apply"}:
        report["blockers"].append("invalid_mode")
        report["status"] = "controlled_close_reconciliation_blocked"
        return report
    if len(target_rows) != 3 or {_normalize_ticker(row.get("ticker")) for row in target_rows} != {"ETH-USDC", "AVAX-USDC", "SOL-USDC"}:
        report["blockers"].append("apply_scope_must_be_exactly_eth_avax_sol")
    if not report["ada_excluded"]:
        report["blockers"].append("ada_in_apply_scope")

    source, source_error = _read_json(source_path)
    report["source_report_present"] = source_error is None
    if source_error:
        report["blockers"].append(f"source_report_{source_error}")
    else:
        report["blockers"].extend(validate_source_report(source, target_rows))

    positions, positions_error = _read_json(state_positions_path)
    open_orders, orders_error = _read_json(state_open_orders_path)
    if positions_error:
        report["blockers"].append(f"positions_state_{positions_error}")
    if orders_error:
        report["blockers"].append(f"open_orders_state_{orders_error}")

    snapshots: Dict[str, Dict[str, Any]] = {}
    if coinbase_client is None:
        report["blockers"].append("coinbase_client_missing")
    else:
        for target in target_rows:
            ticker = _normalize_ticker(target.get("ticker"))
            try:
                snapshot = fetch_coinbase_order_snapshot_with_diagnostics(
                    coinbase_client=coinbase_client,
                    order_id=str(target.get("exchange_order_id") or ""),
                    local_order={
                        "client_order_id": str(target.get("client_order_id") or ""),
                        "exchange_order_id": str(target.get("exchange_order_id") or ""),
                        "ticker": ticker,
                        "product_id": ticker,
                        "side": "SELL",
                    },
                    include_fills=True,
                )
            except Exception as exc:  # defensive: diagnostics should already catch this
                snapshot = {
                    "coinbase_call_attempted": True,
                    "coinbase_call_succeeded": False,
                    "coinbase_snapshot_unavailable": True,
                    "coinbase_error_type": type(exc).__name__,
                    "coinbase_error_message": str(exc),
                }
            snapshots[ticker] = _as_dict(snapshot)

    for target in target_rows:
        ticker = _normalize_ticker(target.get("ticker"))
        validation = validate_terminal_fill_snapshot(target, snapshots.get(ticker, {}))
        report["validations"].append(validation)
        for blocker in validation["blockers"]:
            report["blockers"].append(f"{ticker}:{blocker}")

    report["all_terminal_fill_evidence_valid"] = bool(report["validations"]) and all(
        bool(row.get("valid")) for row in report["validations"]
    )
    report["snapshots"] = {ticker: _audit_snapshot(snapshot) for ticker, snapshot in snapshots.items()}
    report["eth_filled_evidence_valid"] = bool(next((row.get("valid") for row in report["validations"] if row.get("ticker") == "ETH-USDC"), False))
    report["avax_filled_evidence_valid"] = bool(next((row.get("valid") for row in report["validations"] if row.get("ticker") == "AVAX-USDC"), False))
    report["sol_filled_evidence_valid"] = bool(next((row.get("valid") for row in report["validations"] if row.get("ticker") == "SOL-USDC"), False))

    if selected_mode == "check":
        report["status"] = "controlled_close_reconciliation_check_ready" if not report["blockers"] else "controlled_close_reconciliation_check_blocked"
        report["no_state_write"] = True
        return report

    if str(ack or "").strip() != REQUIRED_ACK:
        report["blockers"].append("exact_ack_required")
    if not confirmation:
        report["blockers"].append("extra_confirmation_required")
    journal_blocker = _journal_blocks_apply(state_journal_path)
    if journal_blocker:
        report["blockers"].append(journal_blocker)
    if report["blockers"]:
        report["status"] = "controlled_close_reconciliation_apply_blocked"
        report["no_state_write"] = True
        return report

    local_blockers, already_reconciled = _local_state_blockers(
        positions=positions,
        open_orders=open_orders,
        validations=report["validations"],
    )
    report["blockers"].extend(local_blockers)
    if report["blockers"]:
        report["status"] = "controlled_close_reconciliation_apply_blocked"
        report["no_state_write"] = True
        return report
    if already_reconciled:
        report["status"] = "already_reconciled_noop"
        report["no_state_write"] = True
        report["idempotent"] = True
        return report

    reconciled_at = _now_iso()
    updated_positions = deepcopy(dict(positions))
    updated_open_orders = deepcopy(dict(open_orders))
    orders = updated_open_orders.get("orders")
    if not isinstance(orders, dict):
        report["blockers"].append("open_orders_collection_invalid")
        report["status"] = "controlled_close_reconciliation_apply_blocked"
        report["no_state_write"] = True
        return report
    for validation in report["validations"]:
        ticker = str(validation["ticker"])
        updated_positions[ticker] = _closed_position(_as_dict(positions.get(ticker)), validation, reconciled_at=reconciled_at)
        orders[str(validation["client_order_id"])] = _final_order_record(
            validation,
            reconciled_at=reconciled_at,
            source_report=source_path,
        )
    updated_open_orders["orders"] = orders
    try:
        transaction = _write_recoverable_transaction(
            positions_path=state_positions_path,
            open_orders_path=state_open_orders_path,
            journal_path=state_journal_path,
            original_positions=positions,
            original_open_orders=open_orders,
            updated_positions=updated_positions,
            updated_open_orders=updated_open_orders,
        )
    except Exception as exc:
        report["status"] = "controlled_close_reconciliation_apply_failed_recovery_required"
        report["blockers"].append(f"local_transaction_failed:{type(exc).__name__}")
        report["no_state_write"] = False
        report["recovery_journal_path"] = str(state_journal_path)
        return report
    report.update({
        "status": "controlled_close_reconciliation_apply_performed",
        "state_write_performed": True,
        "positions_mutated": True,
        "open_orders_mutated": True,
        "no_state_write": False,
        "transaction": transaction,
        "idempotent": True,
    })
    return report


__all__ = [
    "BASE_TOLERANCE",
    "CONTROLLED_CLOSE_TARGETS",
    "JOURNAL_DEFAULT",
    "PHASE",
    "REQUIRED_ACK",
    "REQUIRED_CONFIRMATION_FLAG",
    "reconcile_controlled_position_closes",
    "validate_source_report",
    "validate_terminal_fill_snapshot",
]
