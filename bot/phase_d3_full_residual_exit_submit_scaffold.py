from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from bot.coinbase_client import CoinbaseClient
from bot.order_store import OrderStore
from bot.phase_d3_controlled_live_exits import (
    D3_ACK,
    D3_PHASE,
    submit_phase_d3_controlled_exit,
)
from bot.phase_d3_full_residual_exit_prep import (
    FUTURE_RESIDUAL_EXIT_ACK,
    PHASE_D3_FULL_RESIDUAL_EXIT_PREP,
    build_phase_d3_full_residual_exit_prep_report,
)
from bot.state_store import StateStore

PHASE_D3_FULL_RESIDUAL_EXIT_SUBMIT_SCAFFOLD = "D3_full_residual_exit_submit_scaffold"
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _clone_cfg_for_process_local_submit(cfg: Any) -> Any:
    cloned = copy.copy(cfg)
    for key, value in {
        "enable_phase_d3_actual_exit_submit": True,
        "enable_live_exit_orders": True,
        "autonomous_allow_exits": True,
        "phase_c_disable_exit_limit_orders": False,
    }.items():
        try:
            setattr(cloned, key, value)
        except Exception:
            pass
    return cloned


def _position_id(position: Dict[str, Any]) -> str:
    return str(position.get("order_id") or position.get("position_id") or "").strip()


def _client_order_id(*, ticker: str, position_id: str) -> str:
    clean_ticker = _normalize_ticker(ticker).replace("-", "")
    suffix = _now_iso().replace(":", "").replace(".", "").replace("+", "")[-18:]
    pos_part = str(position_id or "pos")[-8:].replace("-", "")
    return f"phased3-{clean_ticker}-TPCLOSE-{pos_part}-{suffix}"


def _build_plan_and_intent_from_prep(prep: Dict[str, Any], *, position: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    ticker = _normalize_ticker(prep.get("ticker") or position.get("ticker"))
    position_id = _position_id(position)
    rounded_sell_base = str(prep.get("rounded_sell_base") or "0")
    limit_price = str(prep.get("limit_price") or "0")
    estimated_quote = str(prep.get("estimated_quote_value") or "0")
    plan = {
        "status": "position_executor_plan_ready_no_live_exit_submit",
        "ticker": ticker,
        "position_id": position_id,
        "plan_id": "full_residual_submit_scaffold_plan",
    }
    intent = {
        "generated_at": _now_iso(),
        "phase": D3_PHASE,
        "intent_id": "full_residual_exit_submit_candidate",
        "client_order_id": _client_order_id(ticker=ticker, position_id=position_id),
        "ticker": ticker,
        "position_id": position_id,
        "side": "SELL",
        "execution_action": "place_limit_sell",
        "label": "TP_CLOSE",
        "size_base": rounded_sell_base,
        "raw_limit_price": limit_price,
        "limit_price": limit_price,
        "estimated_quote_value": estimated_quote,
        "price_increment_used": str((prep.get("product_rules") or {}).get("price_increment") or "0"),
        "price_precision_context": "full_residual_submit_scaffold",
        "requested_base_before_clamp": str(prep.get("raw_full_residual_base") or "0"),
        "position_base": str(prep.get("raw_full_residual_base") or "0"),
        "reserved_base_existing_exit_orders": str((prep.get("local_governance") or {}).get("reserved_base_open_exit_orders") or "0"),
        "available_base_after_reservations": str((prep.get("local_governance") or {}).get("available_base_after_reservations") or "0"),
        "reduce_only_local": True,
        "post_only": True,
        "blockers": [],
        "warnings": [],
        "source_plan_id": "full_residual_submit_scaffold_plan",
        "source_plan_status": "position_executor_plan_ready_no_live_exit_submit",
    }
    return plan, intent


def build_phase_d3_full_residual_exit_submit_scaffold_report(
    *,
    cfg: Any,
    ticker: str,
    limit_price: Any,
    state_store: Optional[StateStore] = None,
    order_store: Optional[OrderStore] = None,
    base_increment: Any = "0.00000001",
    base_min_size: Any = "0.00000001",
    quote_min_size: Any = "1",
    price_increment: Any = "0.01",
    live_base_available: Any = None,
    submit_live: bool = False,
    residual_submit_ack: str = "",
    d3_human_ack: str = "",
    confirm_route: str = "",
    confirm_label: str = "",
    coinbase_client: Any = None,
) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    state = state_store or StateStore()
    orders = order_store or OrderStore()
    position = state.get_position(ticker) or {}
    prep = build_phase_d3_full_residual_exit_prep_report(
        cfg=cfg,
        ticker=ticker,
        limit_price=limit_price,
        state_store=state,
        order_store=orders,
        base_increment=base_increment,
        base_min_size=base_min_size,
        quote_min_size=quote_min_size,
        price_increment=price_increment,
        live_base_available=live_base_available,
        route_label="TP_CLOSE",
    )
    safety_blockers: list[str] = []
    warnings: list[str] = []
    prep_blockers = list(prep.get("blockers") or [])
    if prep_blockers:
        safety_blockers.extend(f"prep:{item}" for item in prep_blockers)
    if prep.get("phase") != PHASE_D3_FULL_RESIDUAL_EXIT_PREP:
        safety_blockers.append("prep_phase_unexpected")
    if prep.get("route") != "single_full_residual_exit":
        safety_blockers.append("route_not_single_full_residual_exit")
    if prep.get("route_label") != "TP_CLOSE":
        safety_blockers.append("route_label_not_tp_close")
    if str(prep.get("route_label") or "").upper() == "TP1":
        safety_blockers.append("stale_tp1_label_rejected")
    if str(confirm_label or "").strip().upper() == "TP1":
        safety_blockers.append("stale_tp1_label_rejected")
    if str(confirm_route or "").strip() and str(confirm_route).strip() != "single_full_residual_exit":
        safety_blockers.append("operator_confirm_route_mismatch")
    if str(confirm_label or "").strip() and str(confirm_label).strip().upper() != "TP_CLOSE":
        safety_blockers.append("operator_confirm_label_mismatch")
    if not (prep.get("min_size_checks") or {}).get("base_above_min"):
        safety_blockers.append("base_min_size_check_failed")
    if not (prep.get("min_size_checks") or {}).get("quote_above_min"):
        safety_blockers.append("quote_min_size_check_failed")
    if (prep.get("min_size_checks") or {}).get("rounding_zeroed_size"):
        safety_blockers.append("rounding_zeroed_sell_base")
    if not prep.get("live_base_sufficient"):
        safety_blockers.append("live_base_not_sufficient")
    local_governance = prep.get("local_governance") or {}
    open_d3_count = int(((local_governance.get("open_d3_exit_orders") or {}).get("total_open_d3_exit_orders") or 0))
    if open_d3_count != 0:
        safety_blockers.append("open_d3_exit_order_exists")
    if local_governance.get("duplicate_exit_order_for_position_action"):
        safety_blockers.append("duplicate_exit_order_for_position_action")
    if _to_decimal(local_governance.get("reserved_base_open_exit_orders"), "0") != ZERO:
        safety_blockers.append("reserved_base_open_exit_orders_nonzero")
    readiness = prep.get("readiness") or {}
    if not readiness.get("ready"):
        safety_blockers.append("d3_readiness_not_ready")
    if readiness.get("submit_armed"):
        safety_blockers.append("submit_armed_during_scaffold_review")
    if _to_decimal(prep.get("rounded_sell_base"), "0") > _to_decimal(local_governance.get("available_base_after_reservations"), "0"):
        safety_blockers.append("rounded_sell_base_exceeds_available_after_reservations")

    live_gate_blockers: list[str] = []
    if not submit_live:
        live_gate_blockers.append("submit_live_flag_missing")
    if str(residual_submit_ack or "").strip() != FUTURE_RESIDUAL_EXIT_ACK:
        live_gate_blockers.append("residual_submit_ack_missing_or_invalid")
    if str(d3_human_ack or "").strip() != D3_ACK:
        live_gate_blockers.append("d3_human_ack_missing_or_invalid")
    if not str(confirm_route or "").strip():
        live_gate_blockers.append("operator_confirm_route_missing")
    if not str(confirm_label or "").strip():
        live_gate_blockers.append("operator_confirm_label_missing")

    baseline_flags_safe = (
        not _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False)
        and not _cfg_bool(cfg, "enable_live_exit_orders", False)
        and not _cfg_bool(cfg, "autonomous_allow_exits", False)
        and _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True)
    )
    if not baseline_flags_safe:
        safety_blockers.append("baseline_live_sell_flags_not_safe_false")

    ready_for_operator_live_ack = not safety_blockers
    live_submit_allowed = bool(submit_live and not safety_blockers and not live_gate_blockers)
    submit_result: Optional[Dict[str, Any]] = None
    coinbase_write_performed = False
    live_order_action_performed = False
    state_write_performed = False

    future_command_template = (
        "python3 tools/run_phase_d3_full_residual_exit_submit_scaffold.py "
        "--ticker BTC-USDC --limit-price <fresh_limit_price> "
        "--base-increment <fresh_base_increment> --base-min-size <fresh_base_min_size> "
        "--quote-min-size <fresh_quote_min_size> --price-increment <fresh_price_increment> "
        "--live-base-available <fresh_live_base_available> "
        "--confirm-route single_full_residual_exit --confirm-label TP_CLOSE "
        "--submit-live "
        f"--residual-submit-ack {FUTURE_RESIDUAL_EXIT_ACK} "
        f"--d3-human-ack {D3_ACK} --json"
    )

    if live_submit_allowed:
        plan, intent = _build_plan_and_intent_from_prep(prep, position=position)
        cfg_for_submit = _clone_cfg_for_process_local_submit(cfg)
        client = coinbase_client if coinbase_client is not None else CoinbaseClient()
        submit_result = submit_phase_d3_controlled_exit(
            cfg=cfg_for_submit,
            position=position,
            plan=plan,
            exit_intent=intent,
            order_store=orders,
            coinbase_client=client,
            human_ack=d3_human_ack,
            submit_live=True,
        )
        live_order_action_performed = bool(submit_result.get("live_submission_attempted"))
        coinbase_write_performed = bool(submit_result.get("live_submission_attempted"))
        state_write_performed = bool(submit_result.get("local_order_record"))
    else:
        if submit_live:
            warnings.append("submit_live_requested_but_blocked_before_coinbase_client")
        else:
            warnings.append("dry_run_only_no_submit_live_flag")

    status = (
        "d3_full_residual_exit_live_submit_completed"
        if submit_result and submit_result.get("live_order_submitted")
        else "d3_full_residual_exit_submit_scaffold_ready_for_ack"
        if ready_for_operator_live_ack
        else "d3_full_residual_exit_submit_scaffold_blocked"
    )
    if submit_live and live_gate_blockers:
        status = "d3_full_residual_exit_submit_scaffold_live_gate_blocked"

    return _json_safe({
        "phase": PHASE_D3_FULL_RESIDUAL_EXIT_SUBMIT_SCAFFOLD,
        "generated_at": _now_iso(),
        "ticker": ticker,
        "status": status,
        "selected_route": "single_full_residual_exit",
        "candidate_label": "TP_CLOSE",
        "submit_live_requested": bool(submit_live),
        "ready_for_operator_live_ack": bool(ready_for_operator_live_ack),
        "live_submit_allowed": bool(live_submit_allowed),
        "prep_report": prep,
        "safety_blockers": sorted(set(safety_blockers)),
        "live_gate_blockers": sorted(set(live_gate_blockers)),
        "warnings": sorted(set(warnings + list(prep.get("warnings") or []))),
        "future_ack_requirements": {
            "residual_submit_ack_required": FUTURE_RESIDUAL_EXIT_ACK,
            "d3_human_ack_required": D3_ACK,
            "submit_live_flag_required": True,
            "confirm_route_required": "single_full_residual_exit",
            "confirm_label_required": "TP_CLOSE",
        },
        "future_live_command_template_not_run": future_command_template,
        "submit_result": submit_result,
        "state_write_performed": bool(state_write_performed),
        "coinbase_call_performed": bool(live_order_action_performed),
        "coinbase_write_performed": bool(coinbase_write_performed),
        "live_order_action_performed": bool(live_order_action_performed),
        "safety_policy": {
            "dry_run_default": True,
            "requires_explicit_submit_live": True,
            "requires_residual_submit_ack": True,
            "requires_d3_human_ack": True,
            "rejects_stale_tp1_label": True,
            "does_not_submit_without_all_gates": True,
            "does_not_mutate_state_without_all_gates": True,
            "does_not_call_coinbase_without_all_gates": True,
        },
    })


__all__ = [
    "PHASE_D3_FULL_RESIDUAL_EXIT_SUBMIT_SCAFFOLD",
    "build_phase_d3_full_residual_exit_submit_scaffold_report",
]
