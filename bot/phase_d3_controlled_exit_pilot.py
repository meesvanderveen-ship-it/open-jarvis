from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import count_local_phase_c_live_entry_orders
from bot.phase_d2_position_executor import (
    D2_PLAN_STATUS_READY,
    build_phase_d2_position_executor_report,
)
from bot.phase_d3_controlled_live_exits import (
    D3_ACK,
    D3_SUBMIT_REJECTED,
    assess_phase_d3_exit_readiness,
    build_phase_d3_exit_payload,
    count_phase_d3_live_exit_orders,
    select_next_phase_d3_exit_intent,
    submit_phase_d3_controlled_exit,
)
from bot.phase_d3_reservation_governance import build_phase_d3_reservation_governance_snapshot
from bot.state_store import StateStore

CONTROLLED_EXIT_PILOT_PHASE = "D3_controlled_exit_one_shot_pilot_runner"
ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK = "I_UNDERSTAND_THIS_ARMS_ONE_BTC_USDC_TP1_REDUCE_ONLY_LIVE_SELL_ONLY"
ONE_SHOT_ACTUAL_EXIT_SUBMIT_TICKER = "BTC-USDC"
ONE_SHOT_ACTUAL_EXIT_SUBMIT_LABEL = "TP1"
ONE_SHOT_ACTUAL_EXIT_SUBMIT_SCOPE = "single_runner_process_only"
D3_CANDIDATE_FINGERPRINT_VERSION = "d3_live_rule_candidate_fingerprint_v1"
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _stable_decimal_string(value: Any, default: str = "0") -> str:
    dec = _to_decimal(value, default)
    if dec == ZERO:
        return "0"
    return format(dec.normalize(), "f")


def _build_d3_candidate_fingerprint_payload(
    *,
    ticker: str,
    selected_exit_intent: Dict[str, Any],
    reservation_governance: Dict[str, Any],
    open_d3_orders: Dict[str, Any],
    base_increment: str,
    price_increment: str,
    quote_increment: str,
    min_order_quote: str,
) -> Dict[str, Any]:
    """Hash only deterministic D.3 candidate and safety fields.

    The D.2 plan fingerprint intentionally covers the broader generated plan.
    For a one-shot live D.3 approval, time-variant plan metadata and current
    position quote-notional are too broad; the guard should bind the exact
    SELL candidate and local safety context.
    """
    return {
        "schema_version": D3_CANDIDATE_FINGERPRINT_VERSION,
        "ticker": _normalize_ticker(ticker),
        "position_id": str(selected_exit_intent.get("position_id") or ""),
        "side": str(selected_exit_intent.get("side") or "").upper(),
        "label": str(selected_exit_intent.get("label") or "").upper(),
        "execution_action": str(selected_exit_intent.get("execution_action") or "").lower(),
        "size_base": _stable_decimal_string(selected_exit_intent.get("size_base")),
        "limit_price": _stable_decimal_string(selected_exit_intent.get("limit_price")),
        "estimated_quote_value": _stable_decimal_string(selected_exit_intent.get("estimated_quote_value")),
        "post_only": bool(selected_exit_intent.get("post_only")),
        "reduce_only_local": bool(selected_exit_intent.get("reduce_only_local")),
        "available_base_after_reservations": _stable_decimal_string(
            reservation_governance.get("available_base_after_reservations")
            or selected_exit_intent.get("available_base_after_reservations")
        ),
        "reserved_base_open_exit_orders": _stable_decimal_string(
            reservation_governance.get("reserved_base_open_exit_orders")
            or selected_exit_intent.get("reserved_base_existing_exit_orders")
        ),
        "open_exit_orders_count": int(open_d3_orders.get("total_open_d3_exit_orders") or 0),
        "base_increment": _stable_decimal_string(base_increment),
        "price_increment": _stable_decimal_string(price_increment),
        "quote_increment": _stable_decimal_string(quote_increment),
        "min_order_quote": _stable_decimal_string(min_order_quote),
    }


def build_d3_candidate_fingerprint(
    *,
    ticker: str,
    selected_exit_intent: Dict[str, Any],
    reservation_governance: Dict[str, Any],
    open_d3_orders: Dict[str, Any],
    base_increment: str,
    price_increment: str,
    quote_increment: str,
    min_order_quote: str,
) -> Dict[str, Any]:
    payload = _build_d3_candidate_fingerprint_payload(
        ticker=ticker,
        selected_exit_intent=selected_exit_intent,
        reservation_governance=reservation_governance,
        open_d3_orders=open_d3_orders,
        base_increment=base_increment,
        price_increment=price_increment,
        quote_increment=quote_increment,
        min_order_quote=min_order_quote,
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "version": D3_CANDIDATE_FINGERPRINT_VERSION,
        "canonical": canonical,
        "payload": payload,
        "hash_fields": sorted(payload.keys()),
        "excluded_fields": [
            "blockers",
            "client_order_id",
            "exchange_rules_fetch_error",
            "generated_at",
            "intent_id",
            "plan_id",
            "position_size_quote",
            "preview_client_order_id",
            "quote_size",
            "raw_product_payload",
            "source_plan_id",
            "updated_at",
            "warnings",
        ],
        "diff_basis": "d3_live_rule_candidate_semantics_and_safety_v1",
    }


def _required_fingerprint_matches(
    *,
    required_plan_fingerprint: str,
    selected_candidate_fingerprint: str,
    selected_plan_fingerprint: str,
) -> bool:
    required = str(required_plan_fingerprint or "").strip().lower()
    if not required:
        return False
    allowed = {
        str(selected_candidate_fingerprint or "").strip().lower(),
        str(selected_plan_fingerprint or "").strip().lower(),
    }
    allowed.discard("")
    return required in allowed


def _clone_cfg_with(cfg: Any, **overrides: Any) -> Any:
    cloned = copy.copy(cfg)
    for key, value in overrides.items():
        try:
            setattr(cloned, key, value)
        except Exception:
            pass
    return cloned


def _baseline_sell_flags_safe(cfg: Any) -> bool:
    return (
        not _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False)
        and not _cfg_bool(cfg, "enable_live_exit_orders", False)
        and not _cfg_bool(cfg, "autonomous_allow_exits", False)
        and _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True)
    )


def build_controlled_exit_pilot_report(
    *,
    cfg: Any,
    ticker: str,
    submit_live: bool = False,
    use_live_exchange_rules_preview: bool = False,
    one_shot_actual_exit_submit: bool = False,
    one_shot_arm_ack: str = "",
    d3_human_ack: str = "",
    require_position_id: str = "",
    require_plan_id: str = "",
    require_plan_fingerprint: str = "",
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    position: Optional[Dict[str, Any]] = None,
    plan: Optional[Dict[str, Any]] = None,
    exchange_rules: Optional[Dict[str, Any]] = None,
    exchange_rules_context: str = "default_preview_fallback",
    exchange_rules_fetch_error: Optional[Dict[str, Any]] = None,
    audit_path: str | Path = "logs/phase_d3_controlled_live_exits.jsonl",
) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    orders = order_store or OrderStore()
    state = state_store or StateStore()
    pos = dict(position) if isinstance(position, dict) else state.get_position(ticker)

    d2_report = build_phase_d2_position_executor_report(
        cfg=cfg,
        ticker=ticker,
        state_store=state,
        position=pos,
        exchange_rules=exchange_rules,
        persist_plan=False,
    )
    d2_plan = dict(plan) if isinstance(plan, dict) else (
        dict(d2_report["plan"]) if isinstance(d2_report.get("plan"), dict) else None
    )
    reservation_governance = build_phase_d3_reservation_governance_snapshot(
        ticker=ticker,
        position=pos,
        order_store=orders,
        plan=d2_plan,
        exchange_rules=exchange_rules,
    )

    selected_exit_intent: Dict[str, Any] = {}
    preview_readiness: Dict[str, Any] = {}
    preview_payload: Dict[str, Any] = {}
    submit_result: Optional[Dict[str, Any]] = None
    if pos and d2_plan and str(d2_plan.get("status") or "") == D2_PLAN_STATUS_READY:
        selected_exit_intent = select_next_phase_d3_exit_intent(
            cfg=cfg,
            plan=d2_plan,
            position=pos,
            order_store=orders,
            exchange_rules=exchange_rules,
        )
        preview_readiness = assess_phase_d3_exit_readiness(
            cfg=cfg,
            position=pos,
            plan=d2_plan,
            exit_intent=selected_exit_intent,
            order_store=orders,
            human_ack="",
            submit_live=False,
        )
        preview_payload = build_phase_d3_exit_payload(cfg=cfg, exit_intent=selected_exit_intent)

    c43_open_count = int(count_local_phase_c_live_entry_orders(orders).get("total_open_live_entry_orders") or 0)
    open_d3_orders = count_phase_d3_live_exit_orders(orders)
    required_position_id = str(require_position_id or "").strip()
    required_plan_id = str(require_plan_id or "").strip()
    required_plan_fingerprint = str(require_plan_fingerprint or "").strip().lower()
    selected_label = str(selected_exit_intent.get("label") or "").strip().upper()
    selected_action = str(selected_exit_intent.get("execution_action") or "").strip().lower()
    selected_position_id = str(selected_exit_intent.get("position_id") or (pos or {}).get("order_id") or "").strip()
    selected_plan_id = str((d2_plan or {}).get("plan_id") or "")
    selected_plan_fingerprint = str((d2_plan or {}).get("plan_fingerprint") or "").strip().lower()
    selected_sell_base = _to_decimal(selected_exit_intent.get("size_base"), "0")
    available_base = _to_decimal(reservation_governance.get("available_base_after_reservations"), "0")
    exchange_rules_map = exchange_rules if isinstance(exchange_rules, dict) else {}
    base_increment = str((d2_plan or {}).get("coinbase_min_size_fallback", {}).get("base_increment") or exchange_rules_map.get("base_increment") or exchange_rules_map.get("base_increment_size") or "0")
    price_increment = str((d2_plan or {}).get("coinbase_min_size_fallback", {}).get("price_increment") or exchange_rules_map.get("price_increment") or exchange_rules_map.get("price_increment_size") or exchange_rules_map.get("quote_increment") or exchange_rules_map.get("quote_increment_size") or "0")
    quote_increment = str(exchange_rules_map.get("quote_increment") or exchange_rules_map.get("quote_increment_size") or "0")
    min_order_quote = str((d2_plan or {}).get("coinbase_min_size_fallback", {}).get("min_order_quote") or exchange_rules_map.get("quote_min_size") or exchange_rules_map.get("min_market_funds") or exchange_rules_map.get("min_order_quote") or "0")
    candidate_fingerprint_report = build_d3_candidate_fingerprint(
        ticker=ticker,
        selected_exit_intent=selected_exit_intent,
        reservation_governance=reservation_governance,
        open_d3_orders=open_d3_orders,
        base_increment=base_increment,
        price_increment=price_increment,
        quote_increment=quote_increment,
        min_order_quote=min_order_quote,
    )
    selected_candidate_fingerprint = str(candidate_fingerprint_report.get("fingerprint") or "").strip().lower()

    blockers: list[str] = []
    warnings: list[str] = []
    one_shot_blockers: list[str] = []
    one_shot_armed_process_local = False
    cfg_for_run = cfg

    def require(condition: bool, bad: str) -> None:
        if not condition:
            blockers.append(bad)

    require(bool(pos), "d3_pilot_position_missing")
    require(bool(d2_plan), "d3_pilot_d2_plan_missing")
    require(str((d2_plan or {}).get("status") or "") == D2_PLAN_STATUS_READY, "d3_pilot_d2_plan_not_ready")
    require(bool(selected_exit_intent), "d3_pilot_exit_intent_missing")
    require(bool(preview_readiness.get("ready")), "d3_pilot_preview_readiness_not_green")
    require(ticker == ONE_SHOT_ACTUAL_EXIT_SUBMIT_TICKER, "d3_pilot_ticker_not_btc_usdc")
    require(selected_label == ONE_SHOT_ACTUAL_EXIT_SUBMIT_LABEL, "d3_pilot_selected_exit_not_tp1")
    require(selected_action == "place_limit_sell", "d3_pilot_selected_execution_action_not_place_limit_sell")
    require(bool(required_position_id), "d3_pilot_required_position_id_missing")
    require(selected_position_id == required_position_id, "d3_pilot_position_id_mismatch")
    require(bool(reservation_governance.get("future_controlled_sell_pilot_coherent")), "d3_pilot_reservation_governance_not_coherent")
    require(available_base >= selected_sell_base > ZERO, "d3_pilot_sell_base_exceeds_available_reservations")
    require(_to_decimal(reservation_governance.get("reserved_base_open_exit_orders"), "0") == ZERO, "d3_pilot_existing_reserved_base_nonzero")
    require(not bool(reservation_governance.get("duplicate_labels_detected")), "d3_pilot_duplicate_labels_detected")
    require(not bool(reservation_governance.get("duplicate_actions_detected")), "d3_pilot_duplicate_actions_detected")
    require(bool(reservation_governance.get("min_size_ready")), "d3_pilot_min_size_not_ready")
    require(int(open_d3_orders.get("total_open_d3_exit_orders") or 0) == 0, "d3_pilot_open_d3_exit_order_exists")
    require(c43_open_count == 0, "d3_pilot_open_c43_buy_order_exists")
    require(not _cfg_bool(cfg, "replication_enabled", False), "d3_pilot_replication_enabled")
    require(_baseline_sell_flags_safe(cfg), "d3_pilot_baseline_live_sell_flags_not_safe_false")
    require(_cfg_bool(cfg, "enable_phase_d3_controlled_live_exits", True), "d3_pilot_phase_d3_controlled_live_exits_disabled")
    if use_live_exchange_rules_preview:
        require(bool(exchange_rules_map), "d3_pilot_live_exchange_rules_context_missing")
        if exchange_rules_fetch_error:
            warnings.append(f"d3_pilot_live_exchange_rules_fetch_error:{str((exchange_rules_fetch_error or {}).get('error_type') or 'unknown')}")

    if submit_live and one_shot_actual_exit_submit:
        if str(one_shot_arm_ack or "").strip() != ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK:
            one_shot_blockers.append("one_shot_actual_exit_submit_ack_missing_or_wrong")
        if not _baseline_sell_flags_safe(cfg):
            one_shot_blockers.append("one_shot_actual_exit_submit_requires_safe_false_baseline_flags")
        if not one_shot_blockers:
            cfg_for_run = _clone_cfg_with(
                cfg,
                enable_phase_d3_actual_exit_submit=True,
                enable_live_exit_orders=True,
                autonomous_allow_exits=True,
                phase_c_disable_exit_limit_orders=False,
            )
            one_shot_armed_process_local = True
    elif submit_live:
        one_shot_blockers.append("one_shot_actual_exit_submit_required_for_live_pilot")

    blockers.extend(one_shot_blockers)
    if submit_live:
        require(one_shot_armed_process_local, "d3_pilot_one_shot_process_local_arming_not_active")
        require(str(d3_human_ack or "").strip() == D3_ACK, "d3_pilot_human_ack_missing_or_invalid")
        require(coinbase_client is not None, "d3_pilot_coinbase_client_missing_for_live_submit")
        require(bool(required_plan_fingerprint), "d3_pilot_required_plan_fingerprint_missing")
        require(
            _required_fingerprint_matches(
                required_plan_fingerprint=required_plan_fingerprint,
                selected_candidate_fingerprint=selected_candidate_fingerprint,
                selected_plan_fingerprint=selected_plan_fingerprint,
            ),
            "d3_pilot_plan_fingerprint_mismatch",
        )
    else:
        warnings.append("preview_only_submit_live_false")
        if use_live_exchange_rules_preview and required_plan_fingerprint:
            require(
                _required_fingerprint_matches(
                    required_plan_fingerprint=required_plan_fingerprint,
                    selected_candidate_fingerprint=selected_candidate_fingerprint,
                    selected_plan_fingerprint=selected_plan_fingerprint,
                ),
                "d3_pilot_plan_fingerprint_mismatch",
            )
    if required_plan_id and selected_plan_id != required_plan_id:
        warnings.append("d3_pilot_plan_id_trace_mismatch")

    if pos and d2_plan and selected_exit_intent and not blockers:
        submit_result = submit_phase_d3_controlled_exit(
            cfg=cfg_for_run,
            position=pos,
            plan=d2_plan,
            exit_intent=selected_exit_intent,
            order_store=orders,
            coinbase_client=coinbase_client if submit_live else None,
            human_ack=d3_human_ack if submit_live else "",
            submit_live=bool(submit_live),
            audit_path=Path(audit_path),
        )
    elif pos and d2_plan and selected_exit_intent and not submit_live:
        submit_result = submit_phase_d3_controlled_exit(
            cfg=cfg,
            position=pos,
            plan=d2_plan,
            exit_intent=selected_exit_intent,
            order_store=orders,
            coinbase_client=None,
            human_ack="",
            submit_live=False,
            audit_path=Path(audit_path),
        )

    status = "d3_controlled_exit_pilot_preview_review"
    if submit_result and submit_result.get("live_order_submitted"):
        status = "d3_controlled_exit_pilot_live_order_submitted"
    elif submit_result and str(submit_result.get("status") or "") == D3_SUBMIT_REJECTED:
        status = "d3_controlled_exit_pilot_live_order_rejected"
    elif submit_live and blockers:
        status = "d3_controlled_exit_pilot_blocked"
    elif submit_live:
        status = "d3_controlled_exit_pilot_submit_requested_no_order_submitted"
    elif submit_result and submit_result.get("status"):
        status = str(submit_result.get("status"))
    elif not pos:
        status = "d3_no_manageable_open_position"
    elif not d2_plan or str((d2_plan or {}).get("status") or "") != D2_PLAN_STATUS_READY:
        status = "d3_no_ready_position_executor_plan"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": CONTROLLED_EXIT_PILOT_PHASE,
        "status": status,
        "ticker": ticker,
        "submit_live": bool(submit_live),
        "use_live_exchange_rules_preview": bool(use_live_exchange_rules_preview),
        "exchange_rules_context": exchange_rules_context,
        "exchange_rules_fetch_error": exchange_rules_fetch_error,
        "base_increment": base_increment,
        "price_increment": price_increment,
        "quote_increment": quote_increment,
        "min_order_quote": min_order_quote,
        "required_position_id": required_position_id,
        "required_plan_id": required_plan_id,
        "required_plan_fingerprint": required_plan_fingerprint,
        "selected_exit_label": selected_label,
        "selected_sell_base": str(selected_sell_base),
        "selected_raw_limit_price": str(selected_exit_intent.get("raw_limit_price") or "0"),
        "selected_limit_price": str(selected_exit_intent.get("limit_price") or "0"),
        "price_precision_context": str(selected_exit_intent.get("price_precision_context") or ""),
        "selected_plan_id": selected_plan_id,
        "selected_plan_fingerprint": selected_plan_fingerprint,
        "selected_candidate_fingerprint": selected_candidate_fingerprint,
        "selected_candidate_fingerprint_version": candidate_fingerprint_report.get("version"),
        "fingerprint_input_canonical": candidate_fingerprint_report.get("canonical"),
        "fingerprint_input_hash_fields": candidate_fingerprint_report.get("hash_fields"),
        "fingerprint_input_diff_basis": candidate_fingerprint_report.get("diff_basis"),
        "fingerprint_excluded_fields": candidate_fingerprint_report.get("excluded_fields"),
        "fingerprint_policy": {
            "selected_candidate_fingerprint_is_submit_guard": True,
            "legacy_d2_plan_fingerprint_accepted_for_compatibility": True,
            "semantic_change": False,
            "rounding_change": False,
            "nonsemantic_metadata_change": selected_candidate_fingerprint != selected_plan_fingerprint,
            "fingerprint_policy_too_broad": selected_candidate_fingerprint != selected_plan_fingerprint,
            "broad_plan_fingerprint_notes": [
                "selected_plan_fingerprint is the legacy D.2 plan fingerprint",
                "selected_candidate_fingerprint excludes mutable plan metadata and position quote-notional",
            ],
        },
        "one_shot_actual_exit_submit_requested": bool(one_shot_actual_exit_submit),
        "one_shot_actual_exit_submit_armed_process_local": one_shot_armed_process_local,
        "one_shot_actual_exit_submit_env_mutation": False,
        "one_shot_actual_exit_submit_scope": ONE_SHOT_ACTUAL_EXIT_SUBMIT_SCOPE,
        "one_shot_actual_exit_submit_blockers": sorted(set(one_shot_blockers)),
        "baseline_safety_flags": {
            "replication_enabled": _cfg_bool(cfg, "replication_enabled", False),
            "enable_phase_d3_actual_exit_submit": _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False),
            "enable_live_exit_orders": _cfg_bool(cfg, "enable_live_exit_orders", False),
            "autonomous_allow_exits": _cfg_bool(cfg, "autonomous_allow_exits", False),
            "phase_c_disable_exit_limit_orders": _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True),
        },
        "position_present": bool(pos),
        "position_id": selected_position_id or str((pos or {}).get("order_id") or ""),
        "d2_report": d2_report,
        "reservation_governance": reservation_governance,
        "open_d3_exit_orders": open_d3_orders,
        "open_c43_entry_orders_count": c43_open_count,
        "selected_exit_intent": selected_exit_intent,
        "readiness": preview_readiness,
        "payload": preview_payload,
        "submit_result": submit_result,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "ack_tokens": {
            "one_shot_arm_ack_required": ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
            "d3_human_ack_required": D3_ACK,
        },
        "live_submission_attempted": bool((submit_result or {}).get("live_submission_attempted")),
        "live_order_submitted": bool((submit_result or {}).get("live_order_submitted")),
        "safety_policy": {
            "uses_existing_d3_submitter_only": True,
            "one_tp1_sell_only": True,
            "does_not_modify_env": True,
            "does_not_modify_global_cfg": True,
            "does_not_submit_when_preview_only": True,
            "does_not_bypass_central_live_exit_gate": True,
            "does_not_submit_runner_or_trailing_exit": True,
            "requires_zero_open_d3_exit_orders_before_submit": True,
        },
    })


__all__ = [
    "CONTROLLED_EXIT_PILOT_PHASE",
    "ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK",
    "ONE_SHOT_ACTUAL_EXIT_SUBMIT_SCOPE",
    "D3_CANDIDATE_FINGERPRINT_VERSION",
    "build_d3_candidate_fingerprint",
    "build_controlled_exit_pilot_report",
]
