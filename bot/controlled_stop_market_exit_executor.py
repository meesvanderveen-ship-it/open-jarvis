from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


CONTROLLED_CLOSE_ACK_PREFIX = "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_"
TERMINAL_FILL_STATUSES = {"filled", "done", "completed"}
ZERO = Decimal("0")
BASE_BALANCE_TRUNCATION_TOLERANCE = Decimal("0.00000001")
BASE_BALANCE_SOURCE_COINBASE_LIVE = "coinbase_live_account"
BASE_BALANCE_SOURCE_TEST_FIXTURE = "coinbase_live_account_test_fixture"
VERIFIED_BASE_BALANCE_SOURCES = {
    BASE_BALANCE_SOURCE_COINBASE_LIVE,
    BASE_BALANCE_SOURCE_TEST_FIXTURE,
}
APPROVED_CONTROLLED_CLOSE_TICKERS = ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
EXCLUDED_CONTROLLED_CLOSE_TICKERS = ["ADA-USDC"]


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value).strip() or default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def terminal_fill_evidence_valid(evidence: Dict[str, Any]) -> bool:
    payload = evidence if isinstance(evidence, dict) else {}
    status = str(payload.get("normalized_status") or payload.get("status") or "").strip().lower()
    return bool(
        status in TERMINAL_FILL_STATUSES
        and (
            _to_decimal(payload.get("filled_base") or payload.get("filled_size"), "0") > ZERO
            or int(payload.get("fill_count") or 0) > 0
        )
    )


def prepare_controlled_close_execution(
    *,
    ack: str,
    required_ack: str,
    positions_to_close: Iterable[str],
    command_tickers: Iterable[str],
    mock_mode: bool = False,
    terminal_fill_evidence: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Pure controlled-close execution gate used by offline tests.

    It never calls Coinbase and never writes state. In ``mock_mode`` an exact
    ACK only marks that a controlled close *would* be submitted by a dedicated
    executor; this module does not submit it.
    """
    close_set = [str(t).strip().upper() for t in positions_to_close if str(t).strip()]
    command_set = [str(t).strip().upper() for t in command_tickers if str(t).strip()]
    provided = str(ack or "").strip()
    required = str(required_ack or "").strip()
    blockers: List[str] = []
    if not required.startswith(CONTROLLED_CLOSE_ACK_PREFIX):
        blockers.append("required_ack_shape_invalid")
    if provided != required:
        blockers.append("exact_ack_required")
    missing = [ticker for ticker in close_set if ticker not in command_set]
    extra = [ticker for ticker in command_set if ticker not in close_set]
    if missing:
        blockers.append("command_missing_close_tickers")
    if extra:
        blockers.append("command_contains_unapproved_tickers")
    would_submit = bool(mock_mode and not blockers)
    fill_valid = terminal_fill_evidence_valid(terminal_fill_evidence or {})
    return {
        "status": "controlled_close_would_submit_mocked" if would_submit else "controlled_close_blocked_or_preview",
        "ack_required": required,
        "ack_matches_required": provided == required,
        "mock_mode": bool(mock_mode),
        "positions_to_close": close_set,
        "command_tickers": command_set,
        "would_submit_controlled_close": would_submit,
        "live_submit_attempted": False,
        "live_order_submitted": False,
        "coinbase_call_attempted": False,
        "balance_lookup_coinbase_call_attempted": False,
        "order_submit_coinbase_call_attempted": False,
        "state_write_performed": False,
        "terminal_fill_evidence_valid": fill_valid,
        "state_apply_allowed": bool(fill_valid and would_submit),
        "state_write_only_after_terminal_fill": True,
        "blockers": blockers,
    }


def _normalize_tickers(values: Iterable[str]) -> List[str]:
    return [str(ticker).strip().upper() for ticker in values if str(ticker).strip()]


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _split_ticker(ticker: str) -> Tuple[str, str]:
    normalized = _normalize_ticker(ticker)
    if "-" not in normalized:
        return normalized, ""
    base, quote = normalized.split("-", 1)
    return base, quote


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is not None and str(value).strip() != "":
            return value
    return None


def _parse_decimal_required(value: Any) -> Tuple[Optional[Decimal], bool]:
    try:
        if value is None:
            return None, False
        text = str(value).strip()
        if not text:
            return None, False
        return Decimal(text), True
    except (InvalidOperation, TypeError, ValueError):
        return None, False


def _required_value_missing(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "ok", "success", "succeeded"}


def _lookup_evidence(position: Dict[str, Any]) -> Dict[str, Any]:
    nested = position.get("coinbase_base_balance_lookup") if isinstance(position.get("coinbase_base_balance_lookup"), dict) else {}
    source = str(
        position.get("base_balance_source")
        or nested.get("source")
        or nested.get("base_balance_source")
        or ""
    ).strip()
    attempted = _truthy(
        position.get("base_balance_lookup_attempted")
        if "base_balance_lookup_attempted" in position
        else nested.get("lookup_attempted")
    ) or _truthy(nested.get("base_balance_lookup_attempted"))
    succeeded = _truthy(
        position.get("base_balance_lookup_success")
        if "base_balance_lookup_success" in position
        else nested.get("lookup_succeeded")
    ) or _truthy(nested.get("base_balance_lookup_success"))
    empty = _truthy(
        position.get("base_balance_lookup_empty")
        if "base_balance_lookup_empty" in position
        else nested.get("lookup_empty")
    )
    fixture_verified = _truthy(
        position.get("base_balance_test_fixture_verified")
        if "base_balance_test_fixture_verified" in position
        else nested.get("test_fixture_verified")
    ) or _truthy(nested.get("base_balance_test_fixture_verified"))
    product_id = _normalize_ticker(
        position.get("base_balance_lookup_product_id")
        or nested.get("product_id")
        or nested.get("product")
        or nested.get("ticker")
        or ""
    )
    base_asset = str(
        position.get("base_balance_lookup_base_asset")
        or position.get("lookup_base_asset")
        or nested.get("lookup_base_asset")
        or nested.get("base_symbol")
        or nested.get("base_asset")
        or ""
    ).strip().upper()
    return {
        "source": source,
        "attempted": attempted,
        "succeeded": succeeded,
        "empty": empty,
        "fixture_verified": fixture_verified,
        "product_id": product_id,
        "base_asset": base_asset,
    }


def _source_is_proven(evidence: Dict[str, Any]) -> bool:
    source = str(evidence.get("source") or "")
    if source == BASE_BALANCE_SOURCE_COINBASE_LIVE:
        return True
    if source == BASE_BALANCE_SOURCE_TEST_FIXTURE and bool(evidence.get("fixture_verified")):
        return True
    return False


def _base_balance_tolerance(position: Dict[str, Any]) -> Decimal:
    raw_tolerance = _first_non_empty(
        position.get("base_balance_tolerance"),
        position.get("base_tolerance"),
        position.get("truncation_tolerance_base"),
        position.get("base_increment"),
        position.get("base_size_increment"),
    )
    tolerance, ok = _parse_decimal_required(raw_tolerance)
    if ok and tolerance is not None and tolerance > ZERO:
        return tolerance
    return BASE_BALANCE_TRUNCATION_TOLERANCE


def _balance_lookup_coinbase_call_attempted(positions: Iterable[Dict[str, Any]]) -> bool:
    for raw in positions or []:
        position = raw if isinstance(raw, dict) else {}
        evidence = _lookup_evidence(position)
        if evidence["attempted"] and str(evidence.get("source") or "") == BASE_BALANCE_SOURCE_COINBASE_LIVE:
            return True
    return False


def _base_preflight(
    positions: Iterable[Dict[str, Any]],
    *,
    service_active: bool = False,
    duplicate_exit_exists: bool = False,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    blockers: List[str] = []
    for raw in positions or []:
        position = raw if isinstance(raw, dict) else {}
        ticker = _normalize_ticker(position.get("ticker") or position.get("product_id"))
        expected_base, expected_quote = _split_ticker(ticker)
        local_value = _first_non_empty(
            position.get("close_base"),
            position.get("local_base"),
            position.get("position_size_base"),
            position.get("bot_managed_base"),
        )
        available_value = _first_non_empty(
            position.get("available_base"),
            position.get("verified_available_base"),
            position.get("available_base_balance"),
        )
        local_base, local_ok = _parse_decimal_required(local_value)
        available_base, available_ok = _parse_decimal_required(available_value)
        local_missing = _required_value_missing(local_value)
        available_missing = _required_value_missing(available_value)
        evidence = _lookup_evidence(position)
        row_blockers: List[str] = []

        if not evidence["attempted"]:
            row_blockers.append("coinbase_base_lookup_missing")
        if evidence["attempted"] and not evidence["succeeded"]:
            row_blockers.append("coinbase_base_lookup_failed")
        if evidence["empty"]:
            row_blockers.extend(["coinbase_base_lookup_failed", "coinbase_base_lookup_empty"])
        if not _source_is_proven(evidence):
            row_blockers.append("coinbase_base_lookup_unverified_source")

        lookup_product = str(evidence.get("product_id") or "")
        lookup_base_asset = str(evidence.get("base_asset") or "")
        product_matches = bool(lookup_product and lookup_product == ticker)
        base_matches = bool(lookup_base_asset and lookup_base_asset == expected_base)
        if not product_matches or not base_matches:
            row_blockers.append("base_asset_mismatch")

        if available_missing:
            row_blockers.append("available_base_missing")
        elif not available_ok:
            row_blockers.append("available_base_unparseable")
        if local_missing:
            row_blockers.append("local_base_missing")
        elif not local_ok:
            row_blockers.append("local_base_unparseable")

        tolerance = _base_balance_tolerance(position)
        would_oversell = True
        if local_ok and available_ok and local_base is not None and available_base is not None:
            would_oversell = bool(local_base <= ZERO or available_base <= ZERO or available_base + tolerance < local_base)
            if available_base + tolerance < local_base:
                row_blockers.append("available_base_below_local_base")
            if local_base <= ZERO:
                row_blockers.append("local_base_nonpositive")
            if available_base <= ZERO:
                row_blockers.append("available_base_nonpositive")

        if duplicate_exit_exists:
            row_blockers.append("duplicate_exit_exists")
        if service_active:
            row_blockers.append("service_active")
        if ticker in EXCLUDED_CONTROLLED_CLOSE_TICKERS:
            row_blockers.append("excluded_position_present_in_close_batch")

        verified = bool(not row_blockers and not would_oversell)
        if not verified:
            blockers.append(f"{ticker}:base_balance_not_verified")
        if would_oversell:
            blockers.append(f"{ticker}:close_size_exceeds_available_base")
        blockers.extend(row_blockers)
        rows.append(
            {
                "ticker": ticker,
                "product_id": ticker,
                "base_asset": expected_base,
                "quote_asset": expected_quote,
                "base_balance_verified": verified,
                "base_balance_source": evidence["source"],
                "base_balance_lookup_attempted": bool(evidence["attempted"]),
                "base_balance_lookup_success": bool(evidence["succeeded"] and not evidence["empty"]),
                "base_balance_lookup_product_id": lookup_product,
                "base_balance_lookup_base_asset": lookup_base_asset,
                "lookup_base_asset": lookup_base_asset,
                "product_id_match": bool(product_matches),
                "base_asset_match": bool(product_matches and base_matches),
                "local_base": str(local_base) if local_base is not None else str(local_value or ""),
                "available_base": str(available_base) if available_base is not None else str(available_value or ""),
                "base_balance_tolerance": str(tolerance),
                "would_oversell": would_oversell,
                "blockers": list(dict.fromkeys(row_blockers)),
            }
        )
    blockers = list(dict.fromkeys(blockers))
    return {
        "rows": rows,
        "base_balances_verified": bool(rows and all(row["base_balance_verified"] for row in rows)),
        "oversell_safe": bool(rows and not any(row["would_oversell"] for row in rows)),
        "base_balance_lookup_attempted": bool(rows and all(row["base_balance_lookup_attempted"] for row in rows)),
        "base_balance_lookup_success": bool(rows and all(row["base_balance_lookup_success"] for row in rows)),
        "blockers": blockers,
    }


def execute_controlled_close_live(
    *,
    ack: str,
    required_ack: str,
    command_tickers: Iterable[str],
    excluded_tickers: Iterable[str],
    positions: Iterable[Dict[str, Any]],
    mode: str = "preview",
    live_confirmation: bool = False,
    service_active: bool = False,
    duplicate_exit_exists: bool = False,
    require_verified_base: bool = True,
    block_oversell: bool = True,
    block_duplicate_exit: bool = True,
    require_terminal_fill_before_state_write: bool = True,
    terminal_fill_evidence: Dict[str, Any] | None = None,
    coinbase_submitter: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    state_apply_callback: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Pure controlled-close executor core.

    The function is intentionally dependency-injected. Production code must pass
    a Coinbase submitter to execute live; tests pass a fake submitter. No state
    write is allowed until terminal fill evidence is present.
    """
    selected_mode = str(mode or "preview").strip().lower()
    tickers = _normalize_tickers(command_tickers)
    excluded = _normalize_tickers(excluded_tickers)
    position_rows = list(positions or [])
    balance_lookup_coinbase_call_attempted = _balance_lookup_coinbase_call_attempted(position_rows)
    blockers: List[str] = []

    if selected_mode not in {"preview", "validate", "execute-live"}:
        blockers.append("invalid_mode")
    if tickers != APPROVED_CONTROLLED_CLOSE_TICKERS:
        blockers.append("positions_must_be_exact_eth_avax_sol")
    if excluded != EXCLUDED_CONTROLLED_CLOSE_TICKERS:
        blockers.append("ada_must_be_explicitly_excluded")
    if any(ticker in tickers for ticker in EXCLUDED_CONTROLLED_CLOSE_TICKERS):
        blockers.append("excluded_position_present_in_close_batch")

    gate = prepare_controlled_close_execution(
        ack=ack,
        required_ack=required_ack,
        positions_to_close=APPROVED_CONTROLLED_CLOSE_TICKERS,
        command_tickers=tickers,
        mock_mode=selected_mode == "validate",
        terminal_fill_evidence=terminal_fill_evidence or {},
    )
    blockers.extend(gate.get("blockers") or [])

    if selected_mode != "execute-live":
        return {
            "status": "ack_gated_preview_ready" if not blockers else "ack_gated_preview_blocked",
            "mode": selected_mode,
            "ack_required": required_ack,
            "ack_matches_required": str(ack or "").strip() == str(required_ack or "").strip(),
            "positions_to_close": tickers,
            "positions_excluded_from_close": excluded,
            "ada_excluded": "ADA-USDC" in excluded and "ADA-USDC" not in tickers,
            "execution_gate": gate,
            "would_submit_controlled_close": bool(gate.get("would_submit_controlled_close")),
            "live_submit_attempted": False,
            "live_order_submitted": False,
            "coinbase_call_attempted": False,
            "balance_lookup_coinbase_call_attempted": False,
            "order_submit_coinbase_call_attempted": False,
            "state_write_performed": False,
            "state_apply_allowed": False,
            "blockers": list(dict.fromkeys(blockers)),
            "will_not_run_now": True,
        }

    if not live_confirmation:
        blockers.append("blocked_missing_live_execute_confirmation")
    if service_active:
        blockers.extend(["service_active_blocks_execute_live", "service_active"])
    base = _base_preflight(position_rows, service_active=service_active, duplicate_exit_exists=duplicate_exit_exists)
    if require_verified_base and not base["base_balances_verified"]:
        blockers.append("base_balance_verification_missing")
    if block_oversell and not base["oversell_safe"]:
        blockers.append("oversell_risk_detected")
    if block_duplicate_exit and duplicate_exit_exists:
        blockers.extend(["duplicate_open_exit_detected", "duplicate_exit_exists"])
    if coinbase_submitter is None:
        blockers.append("coinbase_submitter_missing")

    blockers.extend(base["blockers"])
    blockers = list(dict.fromkeys(blockers))
    if blockers:
        status = "blocked_missing_live_execute_confirmation" if "blocked_missing_live_execute_confirmation" in blockers else "execute_live_blocked"
        return {
            "status": status,
            "mode": selected_mode,
            "ack_required": required_ack,
            "ack_matches_required": str(ack or "").strip() == str(required_ack or "").strip(),
            "positions_to_close": tickers,
            "positions_excluded_from_close": excluded,
            "ada_excluded": "ADA-USDC" in excluded and "ADA-USDC" not in tickers,
            "execution_gate": gate,
            "base_preflight": base,
            "duplicate_exit_exists": bool(duplicate_exit_exists),
            "service_active": bool(service_active),
            "live_submit_attempted": False,
            "live_order_submitted": False,
            "coinbase_call_attempted": bool(balance_lookup_coinbase_call_attempted),
            "balance_lookup_coinbase_call_attempted": bool(balance_lookup_coinbase_call_attempted),
            "order_submit_coinbase_call_attempted": False,
            "state_write_performed": False,
            "state_apply_allowed": False,
            "blockers": blockers,
        }

    submit_payload = {
        "positions_to_close": tickers,
        "positions": position_rows,
        "order_type": "controlled_close_live_sell",
        "market_order_allowed": False,
    }
    response = coinbase_submitter(submit_payload)
    response_dict = response if isinstance(response, dict) else {}
    submitted = bool(response_dict.get("submitted") or response_dict.get("live_order_submitted") or response_dict.get("order_id"))
    fill_valid = terminal_fill_evidence_valid(terminal_fill_evidence or {})
    if not submitted:
        return {
            "status": "execute_live_submit_rejected",
            "mode": selected_mode,
            "positions_to_close": tickers,
            "positions_excluded_from_close": excluded,
            "ada_excluded": True,
            "base_preflight": base,
            "live_submit_attempted": True,
            "live_order_submitted": False,
            "coinbase_call_attempted": True,
            "balance_lookup_coinbase_call_attempted": bool(balance_lookup_coinbase_call_attempted),
            "order_submit_coinbase_call_attempted": True,
            "coinbase_response": response_dict,
            "state_write_performed": False,
            "state_apply_allowed": False,
            "blockers": ["coinbase_submit_rejected_or_missing_order_id"],
        }

    if require_terminal_fill_before_state_write and not fill_valid:
        return {
            "status": "submitted_pending_terminal_fill",
            "mode": selected_mode,
            "positions_to_close": tickers,
            "positions_excluded_from_close": excluded,
            "ada_excluded": True,
            "base_preflight": base,
            "live_submit_attempted": True,
            "live_order_submitted": True,
            "coinbase_call_attempted": True,
            "balance_lookup_coinbase_call_attempted": bool(balance_lookup_coinbase_call_attempted),
            "order_submit_coinbase_call_attempted": True,
            "coinbase_response": response_dict,
            "terminal_fill_evidence_valid": False,
            "state_write_performed": False,
            "state_apply_allowed": False,
            "next_operator_action": "run reconcile/check tool",
            "blockers": ["terminal_fill_evidence_required_before_state_write"],
        }

    apply_result = state_apply_callback({"positions_to_close": tickers, "terminal_fill_evidence": terminal_fill_evidence or {}}) if state_apply_callback else {}
    return {
        "status": "submitted_terminal_fill_applied",
        "mode": selected_mode,
        "positions_to_close": tickers,
        "positions_excluded_from_close": excluded,
        "ada_excluded": True,
        "base_preflight": base,
        "live_submit_attempted": True,
        "live_order_submitted": True,
        "coinbase_call_attempted": True,
        "balance_lookup_coinbase_call_attempted": bool(balance_lookup_coinbase_call_attempted),
        "order_submit_coinbase_call_attempted": True,
        "coinbase_response": response_dict,
        "terminal_fill_evidence_valid": True,
        "state_write_performed": bool(apply_result.get("state_write_performed", state_apply_callback is not None)),
        "state_apply_result": apply_result,
        "state_apply_allowed": True,
        "blockers": [],
    }


__all__ = [
    "APPROVED_CONTROLLED_CLOSE_TICKERS",
    "BASE_BALANCE_SOURCE_COINBASE_LIVE",
    "BASE_BALANCE_SOURCE_TEST_FIXTURE",
    "EXCLUDED_CONTROLLED_CLOSE_TICKERS",
    "execute_controlled_close_live",
    "prepare_controlled_close_execution",
    "terminal_fill_evidence_valid",
]
