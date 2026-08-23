#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.atomic_io import atomic_write_json
from bot.controlled_stop_market_exit_executor import (
    BASE_BALANCE_TRUNCATION_TOLERANCE,
    BASE_BALANCE_SOURCE_COINBASE_LIVE,
    execute_controlled_close_live,
    prepare_controlled_close_execution,
)
from bot.coinbase_client import normalize_coinbase_account_balances
from bot.order_lifecycle import is_open_order_status


PHASE = "controlled_position_closes_ack_gated_v1"
EXPECTED_POSITIONS = ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
EXPECTED_EXCLUDED = ["ADA-USDC"]
REQUIRED_FLAGS = (
    "require_verified_base",
    "block_oversell",
    "block_duplicate_exit",
    "require_terminal_fill_before_state_write",
)
RESULT_ROOT = Path("reports/live_runs")
PREP_REPORT = Path("reports/audits/risk-incomplete-controlled-close-prep-latest.json")
RISK_REPORT = Path("reports/audits/position-risk-reconstruction-preview-latest.json")
OPEN_ORDERS = Path("state/open_orders.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today_token(now: datetime | None = None) -> str:
    selected = now or datetime.now(timezone.utc)
    return selected.strftime("%Y%m%d")


def expected_ack(now: datetime | None = None) -> str:
    return f"CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_{_today_token(now)}"


def _ticker_list(value: str) -> List[str]:
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value).strip() or default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _parse_decimal_required(value: Any) -> tuple[Decimal | None, bool]:
    try:
        if value is None:
            return None, False
        text = str(value).strip()
        if not text:
            return None, False
        return Decimal(text), True
    except (InvalidOperation, TypeError, ValueError):
        return None, False


def _base_balance_tolerance(position: Dict[str, Any]) -> Decimal:
    raw = _first_non_empty(
        position.get("base_balance_tolerance"),
        position.get("base_tolerance"),
        position.get("truncation_tolerance_base"),
        position.get("base_increment"),
        position.get("base_size_increment"),
    )
    parsed, valid = _parse_decimal_required(raw)
    if valid and parsed is not None and parsed > Decimal("0"):
        return parsed
    return BASE_BALANCE_TRUNCATION_TOLERANCE


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _split_ticker(ticker: str) -> tuple[str, str]:
    normalized = _normalize_ticker(ticker)
    if "-" not in normalized:
        return normalized, ""
    return tuple(normalized.split("-", 1))  # type: ignore[return-value]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is not None and str(value).strip() != "":
            return value
    return None


def _is_reports_live_runs_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        return False
    return path.parts[:2] == ("reports", "live_runs") and path.suffix == ".json"


def _positions_from_prep(selected_positions: Sequence[str]) -> List[Dict[str, Any]]:
    wanted = {str(ticker).strip().upper() for ticker in selected_positions if str(ticker).strip()}
    prep = _load_json(PREP_REPORT)
    positions = prep.get("positions") if isinstance(prep.get("positions"), list) else []
    out: List[Dict[str, Any]] = []
    for raw in positions:
        if not isinstance(raw, dict):
            continue
        ticker = str(raw.get("ticker") or "").strip().upper()
        if ticker not in wanted:
            continue
        row = dict(raw)
        row.setdefault("base_balance_verified", bool(raw.get("current_base_balance_verified")))
        row.setdefault("local_base", raw.get("position_size_base") or raw.get("bot_managed_base") or raw.get("base_size"))
        row.setdefault("available_base", raw.get("verified_available_base") or raw.get("base_balance_available") or raw.get("local_base"))
        out.append(row)
    return out


def _runtime_service_active() -> bool:
    risk = _load_json(RISK_REPORT)
    runtime = risk.get("runtime") if isinstance(risk.get("runtime"), dict) else {}
    return bool(runtime.get("service_active") or runtime.get("run_trader_loop_process_found"))


def _duplicate_exit_exists(tickers: Iterable[str]) -> bool:
    wanted = {str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()}
    state = _load_json(OPEN_ORDERS)
    orders = state.get("orders") if isinstance(state.get("orders"), dict) else {}
    for order in orders.values():
        if not isinstance(order, dict):
            continue
        ticker = str(order.get("ticker") or order.get("product_id") or "").strip().upper()
        side = str(order.get("side") or "").strip().upper()
        if ticker in wanted and side == "SELL" and is_open_order_status(order.get("status")):
            return True
    return False


def _snapshot_from_legacy_spot_position(ticker: str, spot: Any) -> Dict[str, Any]:
    spot_dict = spot if isinstance(spot, dict) else {}
    product_id = _normalize_ticker(spot_dict.get("product_id") or ticker)
    expected_base, _quote = _split_ticker(product_id)
    lookup_base_asset = str(
        spot_dict.get("lookup_base_asset")
        or spot_dict.get("base_account_currency")
        or spot_dict.get("base_symbol")
        or spot_dict.get("base_asset")
        or ""
    ).strip().upper()
    available = _first_non_empty(
        spot_dict.get("available_base_balance"),
        spot_dict.get("available_base"),
    )
    _available_decimal, available_ok = _parse_decimal_required(available)
    success = bool(
        spot_dict.get("base_balance_lookup_success")
        if "base_balance_lookup_success" in spot_dict
        else product_id == _normalize_ticker(ticker) and lookup_base_asset == expected_base and available_ok
    )
    empty = bool(
        spot_dict.get("base_balance_lookup_empty")
        if "base_balance_lookup_empty" in spot_dict
        else not spot_dict or available is None or not lookup_base_asset
    )
    return {
        **spot_dict,
        "product_id": product_id,
        "base_symbol": expected_base,
        "lookup_base_asset": lookup_base_asset,
        "available_base_balance": "" if available is None else str(available).strip(),
        "base_balance_lookup_success": success,
        "base_balance_lookup_empty": empty,
        "base_balance_source": BASE_BALANCE_SOURCE_COINBASE_LIVE,
    }


def _coinbase_account_snapshots_by_ticker(
    *,
    positions: Sequence[Dict[str, Any]],
    coinbase_client: Any,
) -> Dict[str, Dict[str, Any]]:
    tickers = [
        _normalize_ticker(position.get("ticker") or position.get("product_id"))
        for position in positions
        if isinstance(position, dict) and _normalize_ticker(position.get("ticker") or position.get("product_id"))
    ]
    if coinbase_client is None:
        raise RuntimeError("coinbase_client_missing")

    if hasattr(coinbase_client, "get_accounts"):
        accounts_payload = coinbase_client.get_accounts()
        return {
            ticker: normalize_coinbase_account_balances(ticker, accounts_payload)
            for ticker in tickers
        }

    if hasattr(coinbase_client, "get_spot_position"):
        return {
            ticker: _snapshot_from_legacy_spot_position(ticker, coinbase_client.get_spot_position(ticker))
            for ticker in tickers
        }

    raise RuntimeError("coinbase_balance_lookup_method_missing")


def _verified_positions_from_coinbase(*, positions: Sequence[Dict[str, Any]], coinbase_client: Any) -> List[Dict[str, Any]]:
    verified: List[Dict[str, Any]] = []
    snapshots: Dict[str, Dict[str, Any]] = {}
    lookup_error: BaseException | None = None
    lookup_attempted = False
    try:
        lookup_attempted = coinbase_client is not None
        snapshots = _coinbase_account_snapshots_by_ticker(positions=positions, coinbase_client=coinbase_client)
    except Exception as exc:
        lookup_error = exc

    for raw in positions:
        position = dict(raw)
        ticker = str(position.get("ticker") or "").strip().upper()
        expected_base, _quote = _split_ticker(ticker)
        lookup = {
            "lookup_attempted": bool(lookup_attempted),
            "lookup_succeeded": False,
            "lookup_empty": True,
            "source": BASE_BALANCE_SOURCE_COINBASE_LIVE,
        }
        position["legacy_available_base"] = position.get("available_base")
        position["base_balance_source"] = BASE_BALANCE_SOURCE_COINBASE_LIVE
        position["base_balance_lookup_attempted"] = bool(lookup_attempted)
        position["base_balance_lookup_success"] = False
        position["base_balance_lookup_empty"] = True
        position["base_balance_verified"] = False
        if lookup_error is not None:
            position["available_base"] = ""
            position["base_balance_lookup_product_id"] = ticker
            position["base_balance_lookup_base_asset"] = ""
            position["lookup_base_asset"] = ""
            lookup = {
                "lookup_attempted": bool(lookup_attempted),
                "lookup_succeeded": False,
                "lookup_empty": True,
                "source": BASE_BALANCE_SOURCE_COINBASE_LIVE,
                "product_id": ticker,
                "base_symbol": "",
                "lookup_base_asset": "",
                "error_type": type(lookup_error).__name__,
                "error": str(lookup_error),
            }
        elif ticker:
            spot_dict = snapshots.get(ticker, {})
            available = str(_first_non_empty(spot_dict.get("available_base_balance"), spot_dict.get("available_base")) or "").strip()
            lookup_product_id = _normalize_ticker(spot_dict.get("product_id") or ticker)
            lookup_base_asset = str(
                spot_dict.get("lookup_base_asset")
                or spot_dict.get("base_account_currency")
                or ""
            ).strip().upper()
            if not lookup_base_asset and bool(spot_dict.get("base_balance_lookup_success")):
                lookup_base_asset = str(spot_dict.get("base_symbol") or spot_dict.get("base_asset") or "").strip().upper()

            available_decimal, available_ok = _parse_decimal_required(available)
            local_decimal, local_ok = _parse_decimal_required(position.get("local_base"))
            tolerance = _base_balance_tolerance(position)
            lookup_success = bool(
                spot_dict.get("base_balance_lookup_success")
                and lookup_product_id == ticker
                and lookup_base_asset == expected_base
                and available_ok
            )
            lookup_empty = bool(spot_dict.get("base_balance_lookup_empty") or not spot_dict)

            position["available_base"] = available
            position["base_balance_lookup_attempted"] = True
            position["base_balance_lookup_success"] = lookup_success
            position["base_balance_lookup_empty"] = lookup_empty
            position["base_balance_lookup_product_id"] = lookup_product_id
            position["base_balance_lookup_base_asset"] = lookup_base_asset
            position["lookup_base_asset"] = lookup_base_asset
            position["base_balance_tolerance"] = str(tolerance)
            position["base_balance_verified"] = bool(
                lookup_success
                and local_ok
                and available_ok
                and available_decimal is not None
                and local_decimal is not None
                and available_decimal + tolerance >= local_decimal
            )
            lookup = {
                "lookup_attempted": True,
                "lookup_succeeded": lookup_success,
                "lookup_empty": lookup_empty,
                "source": BASE_BALANCE_SOURCE_COINBASE_LIVE,
                "product_id": lookup_product_id,
                "base_symbol": lookup_base_asset,
                "lookup_base_asset": lookup_base_asset,
                "spot_position": spot_dict,
            }
        position["coinbase_base_balance_lookup"] = lookup
        verified.append(position)
    return verified


def _build_coinbase_client() -> Any:
    from bot.coinbase_client import CoinbaseClient

    return CoinbaseClient()


def _load_project_dotenv_for_coinbase_auth() -> bool:
    """Load the established project dotenv context without modifying the .env file."""
    try:
        import bot.config  # noqa: F401 - import invokes bot.config's project-root dotenv loader

        return True
    except Exception:
        return False


def _live_market_submitter(*, coinbase_client: Any):
    def submit(payload: Dict[str, Any]) -> Dict[str, Any]:
        orders: List[Dict[str, Any]] = []
        for position in payload.get("positions") or []:
            if not isinstance(position, dict):
                continue
            ticker = str(position.get("ticker") or "").strip().upper()
            base = _to_decimal(position.get("local_base"), "0")
            client_order_id = f"controlled-close-{ticker.replace('-', '')}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            response = coinbase_client.place_market_order(
                ticker=ticker,
                side="SELL",
                size=base,
                client_order_id=client_order_id,
            )
            response_dict = response if isinstance(response, dict) else {}
            order_id = str(
                response_dict.get("order_id")
                or response_dict.get("id")
                or (response_dict.get("success_response") or {}).get("order_id")
                or ""
            ).strip()
            orders.append(
                {
                    "ticker": ticker,
                    "client_order_id": client_order_id,
                    "order_id": order_id,
                    "submitted": bool(order_id or response_dict.get("success", False)),
                    "coinbase_response": response_dict,
                }
            )
        return {"submitted": bool(orders and all(order["submitted"] for order in orders)), "orders": orders}

    return submit


def build_execution_preview_report(
    *,
    ack: str,
    positions: Sequence[str],
    exclude: Sequence[str],
    require_verified_base: bool,
    block_oversell: bool,
    block_duplicate_exit: bool,
    require_terminal_fill_before_state_write: bool,
    json_out: str,
    mode: str = "preview",
    live_confirmation: bool = False,
    service_active: bool | None = None,
    duplicate_exit_exists: bool | None = None,
    position_rows: Sequence[Dict[str, Any]] | None = None,
    terminal_fill_evidence: Dict[str, Any] | None = None,
    coinbase_submitter: Any = None,
    state_apply_callback: Any = None,
    now: datetime | None = None,
) -> Dict[str, Any]:
    selected_mode = str(mode or "preview").strip().lower()
    required_ack = expected_ack(now)
    selected_positions = [str(item).strip().upper() for item in positions if str(item).strip()]
    excluded = [str(item).strip().upper() for item in exclude if str(item).strip()]
    blockers: List[str] = []

    if str(ack or "").strip() != required_ack:
        blockers.append("exact_ack_required")
    if selected_positions != EXPECTED_POSITIONS:
        blockers.append("positions_must_be_exact_eth_avax_sol")
    if excluded != EXPECTED_EXCLUDED:
        blockers.append("ada_must_be_explicitly_excluded")
    if any(ticker in selected_positions for ticker in EXPECTED_EXCLUDED):
        blockers.append("excluded_position_present_in_close_batch")
    if not require_verified_base:
        blockers.append("require_verified_base_flag_missing")
    if not block_oversell:
        blockers.append("block_oversell_flag_missing")
    if not block_duplicate_exit:
        blockers.append("block_duplicate_exit_flag_missing")
    if not require_terminal_fill_before_state_write:
        blockers.append("terminal_fill_state_write_gate_missing")
    if not _is_reports_live_runs_path(json_out):
        blockers.append("json_out_must_be_under_reports_live_runs")

    execution_gate = prepare_controlled_close_execution(
        ack=str(ack or "").strip(),
        required_ack=required_ack,
        positions_to_close=EXPECTED_POSITIONS,
        command_tickers=selected_positions,
        mock_mode=selected_mode == "validate",
        terminal_fill_evidence=terminal_fill_evidence or {},
    )
    execution_result = execute_controlled_close_live(
        ack=str(ack or "").strip(),
        required_ack=required_ack,
        command_tickers=selected_positions,
        excluded_tickers=excluded,
        positions=position_rows if position_rows is not None else _positions_from_prep(selected_positions),
        mode=selected_mode,
        live_confirmation=live_confirmation,
        service_active=_runtime_service_active() if service_active is None else service_active,
        duplicate_exit_exists=_duplicate_exit_exists(selected_positions) if duplicate_exit_exists is None else duplicate_exit_exists,
        require_verified_base=require_verified_base,
        block_oversell=block_oversell,
        block_duplicate_exit=block_duplicate_exit,
        require_terminal_fill_before_state_write=require_terminal_fill_before_state_write,
        terminal_fill_evidence=terminal_fill_evidence or {},
        coinbase_submitter=coinbase_submitter,
        state_apply_callback=state_apply_callback,
    )
    blockers.extend(execution_result.get("blockers") or [])
    status = str(execution_result.get("status") or "")
    if selected_mode in {"preview", "validate"}:
        status = "ack_gated_preview_ready" if not blockers else "ack_gated_preview_blocked"

    return {
        "phase": PHASE,
        "generated_at": _now_iso(),
        "mode": selected_mode,
        "status": status,
        "ack_required": required_ack,
        "ack_matches_required": str(ack or "").strip() == required_ack,
        "positions_to_close": selected_positions,
        "positions_excluded_from_close": excluded,
        "ada_excluded": "ADA-USDC" in excluded and "ADA-USDC" not in selected_positions,
        "ada_action": "manual_hold_review_or_risk_completion_after_ack",
        "require_verified_base": bool(require_verified_base),
        "oversell_blocked": bool(block_oversell),
        "duplicate_exit_blocked": bool(block_duplicate_exit),
        "state_write_only_after_terminal_fill": bool(require_terminal_fill_before_state_write),
        "json_out": str(json_out or ""),
        "execution_gate": execution_gate,
        "execution_result": execution_result,
        "blockers": blockers,
        "read_only": selected_mode != "execute-live",
        "will_not_run_now": selected_mode != "execute-live",
        "coinbase_call_attempted": bool(
            execution_result.get("coinbase_call_attempted")
            or execution_result.get("balance_lookup_coinbase_call_attempted")
            or execution_result.get("order_submit_coinbase_call_attempted")
        ),
        "balance_lookup_coinbase_call_attempted": bool(execution_result.get("balance_lookup_coinbase_call_attempted")),
        "order_submit_coinbase_call_attempted": bool(execution_result.get("order_submit_coinbase_call_attempted")),
        "live_submit_attempted": bool(execution_result.get("live_submit_attempted")),
        "live_order_submitted": bool(execution_result.get("live_order_submitted")),
        "state_write_performed": bool(execution_result.get("state_write_performed")),
        "open_orders_mutated": False,
        "positions_mutated": bool(execution_result.get("state_write_performed")),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ACK-gated controlled close command envelope for ETH/AVAX/SOL.")
    parser.add_argument("--mode", choices=["preview", "validate", "execute-live"], default="preview")
    parser.add_argument("--ack", required=True)
    parser.add_argument("--positions", required=True)
    parser.add_argument("--exclude", required=True)
    parser.add_argument("--require-verified-base", action="store_true")
    parser.add_argument("--block-oversell", action="store_true")
    parser.add_argument("--block-duplicate-exit", action="store_true")
    parser.add_argument("--require-terminal-fill-before-state-write", action="store_true")
    parser.add_argument("--i-understand-this-submits-live-sells", action="store_true")
    parser.add_argument("--json-out", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_positions = _ticker_list(args.positions)
    position_rows = _positions_from_prep(selected_positions)
    coinbase_submitter = None
    if args.mode == "execute-live" and args.i_understand_this_submits_live_sells:
        try:
            _load_project_dotenv_for_coinbase_auth()
            client = _build_coinbase_client()
            position_rows = _verified_positions_from_coinbase(positions=position_rows, coinbase_client=client)
            coinbase_submitter = _live_market_submitter(coinbase_client=client)
        except Exception as exc:
            position_rows = [
                {
                    **row,
                    "base_balance_verified": False,
                    "base_balance_source": BASE_BALANCE_SOURCE_COINBASE_LIVE,
                    "base_balance_lookup_attempted": False,
                    "base_balance_lookup_success": False,
                    "base_balance_lookup_empty": True,
                    "base_balance_lookup_product_id": str(row.get("ticker") or row.get("product_id") or "").strip().upper(),
                    "base_balance_lookup_base_asset": "",
                    "lookup_base_asset": "",
                    "available_base": "",
                    "coinbase_client_error_type": type(exc).__name__,
                    "coinbase_client_error": str(exc),
                    "coinbase_base_balance_lookup": {
                        "lookup_attempted": False,
                        "lookup_succeeded": False,
                        "lookup_empty": True,
                        "source": BASE_BALANCE_SOURCE_COINBASE_LIVE,
                        "product_id": str(row.get("ticker") or row.get("product_id") or "").strip().upper(),
                        "base_symbol": "",
                        "lookup_base_asset": "",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                }
                for row in position_rows
            ]
    report = build_execution_preview_report(
        ack=args.ack,
        positions=selected_positions,
        exclude=_ticker_list(args.exclude),
        require_verified_base=args.require_verified_base,
        block_oversell=args.block_oversell,
        block_duplicate_exit=args.block_duplicate_exit,
        require_terminal_fill_before_state_write=args.require_terminal_fill_before_state_write,
        json_out=args.json_out,
        mode=args.mode,
        live_confirmation=args.i_understand_this_submits_live_sells,
        position_rows=position_rows,
        coinbase_submitter=coinbase_submitter,
    )
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out, report, sort_keys=True)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
