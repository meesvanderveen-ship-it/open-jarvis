from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PHASE_STATE_HYGIENE_CLEANUP_PREVIEW = "state_hygiene_cleanup_preview_v1"
STATE_HYGIENE_CLEANUP_APPLY_ACK = (
    "I_UNDERSTAND_AND_APPROVE_STATE_HYGIENE_RESERVED_BASE_CLEANUP_APPLY"
)
ZERO = Decimal("0")
OPEN_ORDER_STATUSES = {
    "planned",
    "pending",
    "submitted",
    "open",
    "active",
    "new",
    "queued",
    "partially_filled",
    "partial",
    "cancel_pending",
    "replace_pending",
}
D3_EXIT_PHASE = "D3_controlled_live_reduce_only_exits"
RESERVATION_FIELD = "reserved_base_open_exit_orders"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        return Decimal(text if text else default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _decimal_text(value: Decimal) -> str:
    if value == ZERO:
        return "0"
    return format(value.normalize(), "f")


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def load_json_file(path: str | Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def orders_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = payload.get("orders", payload)
    if isinstance(raw, dict):
        return [dict(order) for order in raw.values() if isinstance(order, dict)]
    if isinstance(raw, list):
        return [dict(order) for order in raw if isinstance(order, dict)]
    return []


def positions_from_payload(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = payload.get("positions", payload)
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for key, position in raw.items():
            if not isinstance(position, dict):
                continue
            ticker = _normalize_ticker(position.get("ticker") or key)
            if ticker:
                out[ticker] = dict(position)
    elif isinstance(raw, list):
        for position in raw:
            if not isinstance(position, dict):
                continue
            ticker = _normalize_ticker(position.get("ticker"))
            if ticker:
                out[ticker] = dict(position)
    return out


def _is_open_order(order: Dict[str, Any]) -> bool:
    return str(order.get("status") or "").strip().lower() in OPEN_ORDER_STATUSES


def _is_d3_exit_order(order: Dict[str, Any]) -> bool:
    if str(order.get("side") or "").strip().upper() != "SELL":
        return False
    phase = str(order.get("phase") or "").strip()
    cid = str(order.get("client_order_id") or "").strip().lower()
    mode = str(order.get("mode") or order.get("source_mode") or "").strip().lower()
    return (
        phase == D3_EXIT_PHASE
        or cid.startswith("phased3-")
        or cid.startswith("phased4-")
        or "d3" in mode
    )


def _linked_position_id(position: Dict[str, Any]) -> str:
    for key in (
        "recovery_linked_position_id",
        "linked_position_id",
        "position_id",
        "id",
        "phase_c43_position_id",
    ):
        value = str(position.get(key) or "").strip()
        if value:
            return value
    return ""


def _order_matches_position(order: Dict[str, Any], *, ticker: str, position: Dict[str, Any]) -> bool:
    if _normalize_ticker(order.get("ticker") or order.get("product_id")) != ticker:
        return False
    linked = str(order.get("linked_position_id") or "").strip()
    position_id = _linked_position_id(position)
    if linked and position_id:
        return linked == position_id
    return True


def open_d3_exit_orders_for_position(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    position: Dict[str, Any],
) -> List[Dict[str, Any]]:
    selected = _normalize_ticker(ticker)
    out: List[Dict[str, Any]] = []
    for order in orders:
        if not _is_open_order(order):
            continue
        if not _is_d3_exit_order(order):
            continue
        if not _order_matches_position(order, ticker=selected, position=position):
            continue
        out.append(dict(order))
    return out


def _reserved_from_open_d3_orders(orders: Iterable[Dict[str, Any]]) -> Decimal:
    total = ZERO
    for order in orders:
        total += max(ZERO, _to_decimal(order.get("remaining_size") or order.get("size_base"), "0"))
    return total


def _position_status(position: Dict[str, Any]) -> str:
    return str(position.get("status") or "").strip().lower()


def _manageable_base(position: Dict[str, Any]) -> Decimal:
    for key in ("bot_managed_base", "position_size_base", "base_size", "filled_size_base"):
        value = _to_decimal(position.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _summary_order(order: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "client_order_id": str(order.get("client_order_id") or ""),
        "exchange_order_id": str(order.get("exchange_order_id") or order.get("order_id") or ""),
        "ticker": _normalize_ticker(order.get("ticker") or order.get("product_id")),
        "side": str(order.get("side") or ""),
        "status": str(order.get("status") or ""),
        "phase": str(order.get("phase") or ""),
        "remaining_size": str(order.get("remaining_size") or order.get("size_base") or "0"),
        "linked_position_id": str(order.get("linked_position_id") or ""),
    }


def _classify_position(
    *,
    ticker: str,
    position: Dict[str, Any],
    derived_reserved: Decimal,
    open_d3_count: int,
) -> Dict[str, Any]:
    current_reserved = _to_decimal(position.get(RESERVATION_FIELD), "0")
    status = _position_status(position)
    manageable_base = _manageable_base(position)
    mismatch = current_reserved != derived_reserved
    blockers: List[str] = []
    warnings: List[str] = []
    reason = "reservation_field_matches_derived_governance"
    safe_to_apply_later = False
    proposed_after = current_reserved

    if current_reserved < ZERO or manageable_base < ZERO:
        blockers.append("negative_position_or_reservation_value")
    if open_d3_count > 0 and mismatch:
        blockers.append("open_d3_exit_reservation_mismatch_requires_lifecycle_review")
    if open_d3_count > 1:
        blockers.append("multiple_open_d3_exits_require_lifecycle_review")
    if status in {"open", "active"} and mismatch:
        blockers.append("open_position_reservation_mismatch_requires_lifecycle_review")
    if status not in {"", "closed", "open", "active"}:
        warnings.append("unrecognized_position_status_review_before_cleanup")

    if mismatch and not blockers:
        if open_d3_count == 0 and current_reserved > ZERO and derived_reserved == ZERO and status == "closed" and manageable_base == ZERO:
            reason = "stale_denormalized_reservation_on_closed_position_no_open_d3_exit"
            warnings.append("stale_denormalized_reservation_cleanup_preview_only")
            safe_to_apply_later = True
            proposed_after = ZERO
        elif open_d3_count == 0 and current_reserved == ZERO and derived_reserved > ZERO:
            blockers.append("derived_open_d3_reservation_missing_from_position")
            reason = "derived_open_d3_reservation_missing_from_position"
        else:
            blockers.append("reservation_mismatch_unsafe_or_unknown")
            reason = "reservation_mismatch_unsafe_or_unknown"
    elif mismatch:
        reason = "reservation_mismatch_requires_review"

    return {
        "ticker": ticker,
        "field_path": f"positions.{ticker}.{RESERVATION_FIELD}",
        "position_status": status,
        "position_size_base": str(position.get("position_size_base") or "0"),
        "bot_managed_base": str(position.get("bot_managed_base") or "0"),
        "local_denormalized_value": _decimal_text(current_reserved),
        "derived_expected_value": _decimal_text(derived_reserved),
        "mismatch": bool(mismatch),
        "reason": reason,
        "proposed_before": _decimal_text(current_reserved),
        "proposed_after": _decimal_text(proposed_after),
        "proposed_diff": {
            "field_path": f"positions.{ticker}.{RESERVATION_FIELD}",
            "before": _decimal_text(current_reserved),
            "after": _decimal_text(proposed_after),
        },
        "safe_to_apply_later": bool(safe_to_apply_later),
        "apply_now": False,
        "required_future_ack": STATE_HYGIENE_CLEANUP_APPLY_ACK,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
    }


def build_state_hygiene_cleanup_preview(
    *,
    orders_payload: Dict[str, Any],
    positions_payload: Dict[str, Any],
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    orders = orders_from_payload(orders_payload)
    positions = positions_from_payload(positions_payload)
    open_orders = [order for order in orders if _is_open_order(order)]
    all_open_d3 = [order for order in open_orders if _is_d3_exit_order(order)]

    previews: List[Dict[str, Any]] = []
    governance: List[Dict[str, Any]] = []
    for ticker in sorted(positions):
        position = positions[ticker]
        if RESERVATION_FIELD not in position and ticker != "BTC-USDC":
            continue
        matching_open_d3 = open_d3_exit_orders_for_position(orders, ticker=ticker, position=position)
        derived_reserved = _reserved_from_open_d3_orders(matching_open_d3)
        current_reserved = _to_decimal(position.get(RESERVATION_FIELD), "0")
        classified = _classify_position(
            ticker=ticker,
            position=position,
            derived_reserved=derived_reserved,
            open_d3_count=len(matching_open_d3),
        )
        governance.append(
            {
                "ticker": ticker,
                "derived_reserved_base_from_open_d3_exit_orders": _decimal_text(derived_reserved),
                "derived_open_d3_exit_count": len(matching_open_d3),
                "local_denormalized_reserved_base": _decimal_text(current_reserved),
                "mismatch": bool(current_reserved != derived_reserved),
                "matching_open_d3_exit_orders": [_summary_order(order) for order in matching_open_d3],
            }
        )
        if classified["mismatch"]:
            previews.append(classified)

    blockers = sorted({blocker for preview in previews for blocker in preview.get("blockers", [])})
    warnings = sorted({warning for preview in previews for warning in preview.get("warnings", [])})
    safe_preview_count = sum(1 for preview in previews if preview.get("safe_to_apply_later"))

    if blockers:
        status = "STOP_NOW"
        conclusion = "cleanup_preview_blocked_review_required"
    elif previews:
        status = "WATCH"
        conclusion = "stale_denormalized_state_cleanup_preview_available_no_apply"
    else:
        status = "OK"
        conclusion = "state_hygiene_reservation_fields_match_derived_governance"

    btc_position = positions.get("BTC-USDC", {})
    report = {
        "phase": PHASE_STATE_HYGIENE_CLEANUP_PREVIEW,
        "generated_at": generated_at or _now_iso(),
        "report_mode": "read_only_state_hygiene_cleanup_preview",
        "no_coinbase_call": True,
        "no_http_replication_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "apply_now": False,
        "cleanup_apply_performed": False,
        "required_future_ack": STATE_HYGIENE_CLEANUP_APPLY_ACK,
        "status": status,
        "conclusion": conclusion,
        "current_local_state_summary": {
            "open_orders": len(open_orders),
            "open_d3_exit": len(all_open_d3),
            "position_count": len(positions),
            "btc_usdc_position": {
                "status": str(btc_position.get("status") or ""),
                "position_size_base": str(btc_position.get("position_size_base") or "0"),
                "bot_managed_base": str(btc_position.get("bot_managed_base") or "0"),
                "reserved_base_open_exit_orders": str(btc_position.get(RESERVATION_FIELD) or "0"),
                "last_d3_reconcile_status": str(btc_position.get("last_d3_reconcile_status") or ""),
                "last_d3_exit_lifecycle_applied_status": str(
                    btc_position.get("last_d3_exit_lifecycle_applied_status") or ""
                ),
            },
        },
        "derived_reservation_governance": governance,
        "cleanup_preview": previews,
        "cleanup_preview_count": len(previews),
        "safe_cleanup_preview_count": safe_preview_count,
        "blockers": blockers,
        "warnings": warnings,
        "ack_boundary": {
            "future_apply_requires_exact_ack": STATE_HYGIENE_CLEANUP_APPLY_ACK,
            "apply_now": False,
            "no_apply_performed": True,
            "operator_note": (
                "This report is a preview only. Any local state repair must be requested in a future "
                "prompt with the exact ACK and fresh hashes."
            ),
        },
        "readiness_flags": {
            "master_ready_for_operator_preflight": status != "STOP_NOW",
            "master_ready_for_operator_live_start": False,
            "master_live_exit_ready": False,
            "follower_ready_for_paper_lifecycle_test": True,
            "follower_ready_for_live": False,
            "follower_sell_ready": False,
            "lifecycle_parity_ready": False,
            "all_ticker_ready": False,
            "learning_to_execution_ready": False,
            "state_hygiene_cleanup_preview_ready": True,
            "state_hygiene_apply_ready": False,
        },
    }
    return _json_safe(report)


def build_state_hygiene_cleanup_preview_from_files(
    *,
    orders_file: str | Path,
    positions_file: str | Path,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    orders_path = Path(orders_file)
    positions_path = Path(positions_file)
    orders_payload = load_json_file(orders_path)
    positions_payload = load_json_file(positions_path)
    report = build_state_hygiene_cleanup_preview(
        orders_payload=orders_payload,
        positions_payload=positions_payload,
        generated_at=generated_at,
    )
    report["state_hashes"] = {
        str(orders_path): sha256_file(orders_path),
        str(positions_path): sha256_file(positions_path),
    }
    report["orders_file"] = str(orders_path)
    report["positions_file"] = str(positions_path)
    return report


def render_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("current_local_state_summary") or {}
    btc = summary.get("btc_usdc_position") or {}
    flags = report.get("readiness_flags") or {}
    lines = [
        "# State Hygiene Cleanup Preview",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- conclusion: `{report.get('conclusion')}`",
        f"- no_coinbase_call: `{report.get('no_coinbase_call')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- apply_now: `{report.get('apply_now')}`",
        f"- safety_classification: `{report.get('status')}`",
        "",
        "## Current Local State",
        "",
        f"- open_orders: `{summary.get('open_orders')}`",
        f"- open_d3_exit: `{summary.get('open_d3_exit')}`",
        f"- position_count: `{summary.get('position_count')}`",
        f"- BTC-USDC status: `{btc.get('status')}`",
        f"- BTC-USDC position_size_base: `{btc.get('position_size_base')}`",
        f"- BTC-USDC bot_managed_base: `{btc.get('bot_managed_base')}`",
        f"- BTC-USDC reserved_base_open_exit_orders: `{btc.get('reserved_base_open_exit_orders')}`",
        "",
        "## Derived Reservation Governance",
        "",
    ]
    governance = report.get("derived_reservation_governance") or []
    if not governance:
        lines.append("- No reservation governance rows found.")
    for row in governance:
        lines.extend(
            [
                f"- ticker: `{row.get('ticker')}`",
                f"  - derived_reserved_base_from_open_d3_exit_orders: `{row.get('derived_reserved_base_from_open_d3_exit_orders')}`",
                f"  - derived_open_d3_exit_count: `{row.get('derived_open_d3_exit_count')}`",
                f"  - local_denormalized_reserved_base: `{row.get('local_denormalized_reserved_base')}`",
                f"  - mismatch: `{row.get('mismatch')}`",
            ]
        )
    lines.extend(
        [
            "",
        "## Cleanup Preview",
        "",
        ]
    )
    previews = report.get("cleanup_preview") or []
    if not previews:
        lines.append("- No reservation cleanup diff is proposed.")
    for preview in previews:
        lines.extend(
            [
                f"- field_path: `{preview.get('field_path')}`",
                f"  - before: `{preview.get('proposed_before')}`",
                f"  - proposed_after: `{preview.get('proposed_after')}`",
                f"  - proposed_diff: `{preview.get('proposed_diff')}`",
                f"  - reason: `{preview.get('reason')}`",
                f"  - safe_to_apply_later: `{preview.get('safe_to_apply_later')}`",
                f"  - apply_now: `{preview.get('apply_now')}`",
                f"  - blockers: `{', '.join(preview.get('blockers') or [])}`",
                f"  - warnings: `{', '.join(preview.get('warnings') or [])}`",
            ]
        )
    lines.extend(
        [
            "",
            "## ACK Boundary",
            "",
            f"- future apply ACK: `{report.get('required_future_ack')}`",
            "- No cleanup apply was performed.",
            "- Any future state repair requires a separate exact operator ACK and fresh state hashes.",
            "",
            "## Readiness Flags",
            "",
        ]
    )
    for key in (
        "master_ready_for_operator_preflight",
        "master_ready_for_operator_live_start",
        "master_live_exit_ready",
        "follower_ready_for_paper_lifecycle_test",
        "follower_ready_for_live",
        "follower_sell_ready",
        "lifecycle_parity_ready",
        "all_ticker_ready",
        "learning_to_execution_ready",
        "state_hygiene_cleanup_preview_ready",
        "state_hygiene_apply_ready",
    ):
        lines.append(f"- {key}: `{flags.get(key)}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_STATE_HYGIENE_CLEANUP_PREVIEW",
    "STATE_HYGIENE_CLEANUP_APPLY_ACK",
    "build_state_hygiene_cleanup_preview",
    "build_state_hygiene_cleanup_preview_from_files",
    "render_markdown",
]
