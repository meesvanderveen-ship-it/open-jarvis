from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


OPEN_ENTRY_STATUSES = {"planned", "pending", "submitted", "open", "active", "partially_filled", "cancel_pending", "replace_pending"}
FILLED_STATUSES = {"filled", "done", "completed"}
FINAL_STATUSES = {"filled", "done", "completed", "cancelled", "canceled", "expired", "failed", "rejected", "invalidated"}
D3_PHASE = "D3_controlled_live_reduce_only_exits"
LIVE_CANCEL_ACK = "I_APPROVE_PENDING_ENTRY_LIVE_CANCEL"
ZERO = Decimal("0")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _to_decimal(value: Any, default: Optional[str] = None) -> Optional[Decimal]:
    if value in (None, ""):
        value = default
    if value in (None, ""):
        return None
    try:
        out = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if out.is_nan() or out.is_infinite():
        return None
    return out


def _first_decimal(*values: Any) -> Optional[Decimal]:
    for value in values:
        dec = _to_decimal(value)
        if dec is not None and dec > ZERO:
            return dec
    return None


def _fmt(value: Optional[Decimal]) -> str:
    return "" if value is None else format(value.normalize(), "f")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_bool(env: Optional[Dict[str, str]], key: str, default: bool = False) -> bool:
    return _bool((env or {}).get(key), default)


def _env_dec(env: Optional[Dict[str, str]], key: str, default: str) -> Decimal:
    return _to_decimal((env or {}).get(key), default) or Decimal(default)


def _env_int(env: Optional[Dict[str, str]], key: str, default: int) -> int:
    try:
        return int(str((env or {}).get(key, default)).strip())
    except Exception:
        return default


def is_pending_entry_order(order: Dict[str, Any]) -> bool:
    if not isinstance(order, dict):
        return False
    if str(order.get("side") or "").upper() != "BUY":
        return False
    if str(order.get("phase") or "") == D3_PHASE:
        return False
    status = str(order.get("status") or "").lower()
    if status not in OPEN_ENTRY_STATUSES:
        return False
    action = str(order.get("execution_action") or "").lower()
    return action in {"", "place_limit_buy"} or bool(order.get("opened_via_phase_c43")) or str(order.get("source_mode") or "").lower() in {"autonomous_small_live", "orderbook_entry_preview"}


def _ticker(order: Dict[str, Any]) -> str:
    return str(order.get("ticker") or order.get("product_id") or "").upper()


def _order_age_minutes(order: Dict[str, Any], now: Optional[datetime]) -> Optional[Decimal]:
    created = parse_time(order.get("created_at") or order.get("submitted_at") or order.get("updated_at"))
    if created is None:
        return None
    current = now or datetime.now(timezone.utc)
    return Decimal(str(max(0.0, (current - created).total_seconds() / 60.0)))


def _market_values(current_market: Dict[str, Any]) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    market = _as_dict(current_market.get("market")) or current_market
    orderbook = _as_dict(current_market.get("orderbook_context"))
    mid = _first_decimal(current_market.get("mid_price"), market.get("mid_price"), orderbook.get("mid_price"), market.get("current_price"), market.get("last_price"))
    bid = _first_decimal(current_market.get("best_bid"), market.get("best_bid"), orderbook.get("best_bid"))
    ask = _first_decimal(current_market.get("best_ask"), market.get("best_ask"), orderbook.get("best_ask"))
    spread = _first_decimal(current_market.get("spread_pct"), market.get("spread_pct"), orderbook.get("bid_ask_spread_pct"))
    if spread is None and mid and bid and ask and mid > ZERO:
        spread = (ask - bid) / mid
    liquidity = _first_decimal(current_market.get("liquidity_score"), market.get("liquidity_score"), orderbook.get("liquidity_score"), orderbook.get("bid_depth_top5"))
    return mid, bid, ask, spread, liquidity


def _snapshots(order: Dict[str, Any], original_trade_plan: Optional[Dict[str, Any]], original_judge: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    plan = _as_dict(original_trade_plan) or _as_dict(order.get("trade_plan_snapshot")) or _as_dict(order.get("trade_plan"))
    judge = _as_dict(original_judge) or _as_dict(order.get("judge_snapshot")) or _as_dict(order.get("judge"))
    risk = _as_dict(order.get("risk_snapshot"))
    if not plan:
        plan = _as_dict(risk.get("trade_plan"))
    if not judge:
        judge = _as_dict(risk.get("judge"))
    return plan, judge


def _order_levels(order: Dict[str, Any], plan: Dict[str, Any], judge: Dict[str, Any]) -> Dict[str, Optional[Decimal]]:
    return {
        "entry": _first_decimal(order.get("limit_price"), order.get("entry_level"), plan.get("preferred_limit_price"), judge.get("preferred_limit_price"), plan.get("entry_zone_low"), plan.get("entry_zone_high")),
        "invalidation": _first_decimal(order.get("invalidation_level"), plan.get("invalidation_price"), plan.get("stop_loss_price"), plan.get("stop_loss"), judge.get("invalidation_price"), judge.get("cancel_if_price_below")),
        "do_not_chase": _first_decimal(order.get("do_not_chase_above"), plan.get("do_not_chase_above"), judge.get("do_not_chase_above"), judge.get("cancel_if_price_above")),
        "target": _first_decimal(plan.get("target_price_1"), plan.get("take_profit_1"), judge.get("target_price_1"), plan.get("target_price_2"), plan.get("take_profit_2"), judge.get("target_price_2")),
    }


def _same_ticker_position_exists(open_positions: Sequence[Dict[str, Any]], ticker: str) -> bool:
    ticker = str(ticker or "").upper()
    for pos in open_positions:
        if not isinstance(pos, dict):
            continue
        if str(pos.get("ticker") or pos.get("product_id") or "").upper() != ticker:
            continue
        status = str(pos.get("status") or "open").lower()
        base = _first_decimal(pos.get("position_size_base"), pos.get("size_base"), pos.get("base_size"), pos.get("bot_managed_base"))
        if status in {"open", "active"} and base is not None and base > ZERO:
            return True
    return False


def _current_judge_invalidates(current_analysis: Dict[str, Any]) -> Tuple[bool, str]:
    if not current_analysis:
        return False, ""
    judge = _as_dict(current_analysis.get("judge"))
    plan = _as_dict(current_analysis.get("trade_plan"))
    if not judge and not plan:
        return False, ""
    decision = str(judge.get("decision") or "").lower()
    action = str(plan.get("plan_action") or "").lower()
    text = " ".join(str(x) for x in _as_list(judge.get("judge_reasons")) + _as_list(judge.get("reasons")) + _as_list(plan.get("hard_blockers")) + _as_list(plan.get("planner_blockers")) + [judge.get("trigger_wait_reason"), plan.get("no_plan_reason")] if x).lower()
    if action == "no_plan" and decision in {"wait", "reject", "no_trade", ""}:
        return True, "current_judge_no_setup_or_no_plan"
    if "bad_market" in text or "market_not_tradeable" in text or "spread_too_wide" in text:
        return True, "current_judge_bad_market"
    if "higher timeframe invalid" in text or "higher-timeframe invalid" in text or "bearish higher timeframe" in text:
        return True, "current_judge_higher_timeframe_invalidated"
    return False, ""


def _higher_tf_invalidated(current_analysis: Dict[str, Any], current_market: Dict[str, Any]) -> bool:
    text = json.dumps(current_analysis, sort_keys=True, default=str).lower() + " " + json.dumps(current_market, sort_keys=True, default=str).lower()
    tokens = (
        "higher_timeframe_invalidated",
        "higher timeframe invalidated",
        "higher-timeframe invalidated",
        "bearish higher timeframe structure",
        "daily regime conflicts",
        "4h/1d bearish",
    )
    return any(token in text for token in tokens)


def _evidence_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_pending_entry_lifecycle(
    *,
    order: Dict[str, Any],
    current_market: Optional[Dict[str, Any]] = None,
    current_analysis: Optional[Dict[str, Any]] = None,
    original_trade_plan: Optional[Dict[str, Any]] = None,
    original_judge: Optional[Dict[str, Any]] = None,
    open_positions: Optional[Sequence[Dict[str, Any]]] = None,
    exchange_order_status: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    env: Optional[Dict[str, str]] = None,
    open_entry_orders_count: int = 1,
    max_open_entry_orders: int = 4,
) -> Dict[str, Any]:
    current_market = current_market or {}
    current_analysis = current_analysis or {}
    plan, judge = _snapshots(order, original_trade_plan, original_judge)
    ticker = _ticker(order)
    blockers: List[str] = []
    evidence: Dict[str, Any] = {}

    if not is_pending_entry_order(order):
        return _result(
            order=order,
            action="noop",
            reason="not_pending_entry_order",
            cancel_required=False,
            cancel_reason="",
            blockers=[],
            evidence={"ignored_order_side": order.get("side"), "ignored_order_phase": order.get("phase")},
            env=env,
        )

    exchange_status = str((_as_dict(exchange_order_status).get("status") or _as_dict(exchange_order_status).get("normalized_status") or order.get("exchange_status") or "")).lower()
    filled_base = _first_decimal(_as_dict(exchange_order_status).get("filled_size"), _as_dict(exchange_order_status).get("filled_base"), order.get("filled_size"), order.get("filled_base"))
    if exchange_status in FILLED_STATUSES or (filled_base is not None and filled_base > ZERO and exchange_status in FINAL_STATUSES):
        return _result(
            order=order,
            action="noop",
            reason="handoff_to_fill_reconcile",
            cancel_required=False,
            cancel_reason="",
            blockers=[],
            evidence={"exchange_status": exchange_status, "filled_base": _fmt(filled_base)},
            env=env,
            handoff_to_fill_reconcile=True,
        )
    if exchange_status in {"partially_filled", "partial_fill"} or (filled_base is not None and filled_base > ZERO):
        return _result(
            order=order,
            action="noop",
            reason="partial_fill_reconcile_before_cancel",
            cancel_required=False,
            cancel_reason="",
            blockers=[],
            evidence={"exchange_status": exchange_status, "filled_base": _fmt(filled_base), "partial_fill_reconcile_required": True},
            env=env,
            partial_fill_reconcile_required=True,
        )

    mid, bid, ask, spread, liquidity = _market_values(current_market)
    levels = _order_levels(order, plan, judge)
    age = _order_age_minutes(order, now)
    max_ttl = Decimal(str(_env_int(env, "PENDING_ENTRY_MAX_TTL_MINUTES", 60)))
    max_spread = _env_dec(env, "PENDING_ENTRY_CANCEL_IF_SPREAD_GT_PCT", "0.0060")
    move_away = _env_dec(env, "PENDING_ENTRY_CANCEL_IF_PRICE_MOVES_AWAY_PCT", "0.0100")
    min_liquidity = _env_dec(env, "PENDING_ENTRY_MIN_LIQUIDITY_SCORE", "0")

    setup_still_valid = True
    invalidation_breached = bool(mid is not None and levels["invalidation"] is not None and mid <= levels["invalidation"])
    if invalidation_breached:
        blockers.append("setup_invalidated_price_breached_invalidation")
        setup_still_valid = False
    if age is None:
        blockers.append("missing_order_created_at")
    elif age > max_ttl:
        blockers.append("order_ttl_exceeded")
        setup_still_valid = False
    if spread is None:
        blockers.append("missing_spread_evidence")
    elif spread > max_spread:
        blockers.append("spread_too_wide")
        setup_still_valid = False
    if liquidity is not None and min_liquidity > ZERO and liquidity < min_liquidity:
        blockers.append("liquidity_worsened")
        setup_still_valid = False
    if levels["entry"] is None or levels["invalidation"] is None or levels["target"] is None:
        blockers.append("technical_level_missing_or_stale")
        setup_still_valid = False
    if mid is not None and levels["entry"] is not None and levels["entry"] > ZERO:
        distance = abs(mid - levels["entry"]) / levels["entry"]
        if distance > move_away:
            blockers.append("price_moved_away_without_fill")
            setup_still_valid = False
    else:
        distance = None
    if mid is not None and levels["do_not_chase"] is not None and mid > levels["do_not_chase"]:
        blockers.append("do_not_chase_breached")
        setup_still_valid = False
    if _higher_tf_invalidated(current_analysis, current_market):
        blockers.append("higher_timeframe_invalidated")
        setup_still_valid = False
    judge_invalid, judge_reason = _current_judge_invalidates(current_analysis)
    if judge_invalid:
        blockers.append(judge_reason)
        setup_still_valid = False
    if _same_ticker_position_exists(open_positions or [], ticker):
        blockers.append("same_ticker_position_exists")
        setup_still_valid = False
    if open_entry_orders_count > max_open_entry_orders:
        blockers.append("open_entry_order_capacity_no_longer_valid")
        setup_still_valid = False
    if str(order.get("cancel_requested_at") or "") and str(order.get("status") or "").lower() in {"cancel_pending", "replace_pending"}:
        blockers.append("duplicate_cancel_or_replace_already_pending")

    evidence.update(
        {
            "ticker": ticker,
            "age_minutes": _fmt(age),
            "max_ttl_minutes": str(max_ttl),
            "current_mid": _fmt(mid),
            "best_bid": _fmt(bid),
            "best_ask": _fmt(ask),
            "spread_pct": _fmt(spread),
            "max_spread_pct": str(max_spread),
            "liquidity_score": _fmt(liquidity),
            "entry_level": _fmt(levels["entry"]),
            "invalidation_level": _fmt(levels["invalidation"]),
            "target_level": _fmt(levels["target"]),
            "do_not_chase_above": _fmt(levels["do_not_chase"]),
            "distance_from_entry_pct": _fmt(distance),
            "price_moves_away_threshold_pct": str(move_away),
            "setup_still_valid": setup_still_valid,
            "invalidation_breached": invalidation_breached,
            "same_ticker_position_exists": _same_ticker_position_exists(open_positions or [], ticker),
            "exchange_status": exchange_status,
        }
    )

    if "duplicate_cancel_or_replace_already_pending" in blockers:
        return _result(order=order, action="noop", reason="duplicate_cancel_blocked_idempotent", cancel_required=False, cancel_reason="", blockers=blockers, evidence=evidence, env=env)
    if blockers:
        reason = _action_from_blocker(blockers[0])
        return _result(order=order, action=reason, reason=reason, cancel_required=True, cancel_reason=blockers[0], blockers=blockers, evidence=evidence, env=env)
    return _result(order=order, action="keep_open", reason="setup_still_valid", cancel_required=False, cancel_reason="", blockers=[], evidence=evidence, env=env)


def _action_from_blocker(blocker: str) -> str:
    mapping = {
        "setup_invalidated_price_breached_invalidation": "cancel_preview_setup_invalidated",
        "current_judge_no_setup_or_no_plan": "cancel_preview_setup_invalidated",
        "current_judge_bad_market": "cancel_preview_setup_invalidated",
        "current_judge_higher_timeframe_invalidated": "cancel_preview_higher_timeframe_invalidated",
        "higher_timeframe_invalidated": "cancel_preview_higher_timeframe_invalidated",
        "order_ttl_exceeded": "cancel_preview_stale",
        "spread_too_wide": "cancel_preview_spread_too_wide",
        "liquidity_worsened": "cancel_preview_liquidity_worsened",
        "price_moved_away_without_fill": "cancel_preview_price_moved_away",
        "do_not_chase_breached": "cancel_preview_do_not_chase_breached",
        "same_ticker_position_exists": "cancel_preview_setup_invalidated",
        "open_entry_order_capacity_no_longer_valid": "cancel_preview_setup_invalidated",
        "technical_level_missing_or_stale": "no_action_missing_required_evidence",
        "missing_order_created_at": "no_action_missing_required_evidence",
        "missing_spread_evidence": "no_action_missing_required_evidence",
    }
    return mapping.get(blocker, "cancel_preview_setup_invalidated")


def _result(
    *,
    order: Dict[str, Any],
    action: str,
    reason: str,
    cancel_required: bool,
    cancel_reason: str,
    blockers: Sequence[str],
    evidence: Dict[str, Any],
    env: Optional[Dict[str, str]],
    handoff_to_fill_reconcile: bool = False,
    partial_fill_reconcile_required: bool = False,
) -> Dict[str, Any]:
    live_enabled = _env_bool(env, "ENABLE_PENDING_ENTRY_LIVE_CANCEL", False)
    ack_valid = str((env or {}).get("PENDING_ENTRY_LIVE_CANCEL_ACK") or "").strip() == LIVE_CANCEL_ACK
    coinbase_cancel_allowed = bool(cancel_required and live_enabled and ack_valid)
    payload = {
        "generated_at": now_iso(),
        "lifecycle_action": "cancel_preview" if str(action).startswith("cancel_preview") else ("replace_preview" if str(action).startswith("replace_preview") else action),
        "specific_action": action,
        "reason": reason,
        "blockers": list(blockers),
        "cancel_required": bool(cancel_required),
        "cancel_reason": cancel_reason,
        "coinbase_cancel_allowed": coinbase_cancel_allowed,
        "coinbase_cancel_attempted": False,
        "requires_verify_cancel": bool(cancel_required),
        "state_write_allowed": False,
        "state_write_attempted": False,
        "race_condition_policy": "check_fill_before_and_after_cancel",
        "handoff_to_fill_reconcile": handoff_to_fill_reconcile,
        "partial_fill_reconcile_required": partial_fill_reconcile_required,
        "live_cancel_enabled": live_enabled,
        "live_cancel_ack_valid": ack_valid,
        "duplicate_cancel_prevention": "cancel_pending_or_existing_cancel_requested_blocks_new_cancel",
        "local_cancel_state_update_policy": "only_after_verified_exchange_cancel",
        "cancel_failure_policy": "do_not_mark_cancelled_locally_raise_blocker",
        "partial_fill_policy": "reconcile_partial_fill_first_avoid_oversell_or_naked_sell",
        "order_identity": {
            "ticker": _ticker(order),
            "client_order_id": str(order.get("client_order_id") or ""),
            "exchange_order_id": str(order.get("exchange_order_id") or order.get("order_id") or ""),
            "side": str(order.get("side") or ""),
            "status": str(order.get("status") or ""),
            "phase": str(order.get("phase") or ""),
        },
        "evidence": evidence,
    }
    payload["evidence_hash"] = _evidence_hash({"order": payload["order_identity"], "evidence": evidence, "action": action, "cancel_reason": cancel_reason})
    return payload


def build_pending_entry_cancel_route_design(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return {
        "live_cancel_enabled": _env_bool(env, "ENABLE_PENDING_ENTRY_LIVE_CANCEL", False),
        "required_ack": LIVE_CANCEL_ACK,
        "steps": [
            "read_open_order_from_local_state",
            "fetch_verify_exchange_order_status",
            "if_already_filled_do_not_cancel_handoff_to_d1_d2_d3",
            "if_still_open_recompute_lifecycle_invalidation",
            "if_cancel_required_submit_coinbase_cancel_only_when_live_flag_and_ack_valid",
            "verify_exchange_status_cancelled",
            "update_local_open_orders_only_after_verified_cancel",
            "write_audit_evidence_hash",
            "if_cancel_fails_or_status_unknown_do_not_mark_cancelled_locally_raise_blocker",
            "if_partial_fill_during_cancel_reconcile_partial_fill_first_avoid_oversell",
        ],
        "preview_policy": {
            "coinbase_cancel_attempted": False,
            "state_write_attempted": False,
            "requires_verify_cancel": True,
        },
    }


def replacement_allowed_same_thesis(order: Dict[str, Any], replacement: Dict[str, Any], *, max_replaces: int = 1) -> Dict[str, Any]:
    replace_count = int(_to_decimal(order.get("replace_count"), "0") or ZERO)
    same_ticker = _ticker(order) == str(replacement.get("ticker") or replacement.get("product_id") or "").upper()
    same_setup = str(order.get("setup_type") or order.get("original_setup_type") or "") == str(replacement.get("setup_type") or replacement.get("original_setup_type") or "")
    allowed = replace_count < max_replaces and same_ticker and same_setup
    blockers = []
    if replace_count >= max_replaces:
        blockers.append("max_replace_count_reached")
    if not same_ticker:
        blockers.append("replacement_ticker_changed")
    if not same_setup:
        blockers.append("replacement_setup_thesis_changed")
    return {"allowed": allowed, "blockers": blockers, "replace_count": replace_count, "max_replaces": max_replaces}


__all__ = [
    "D3_PHASE",
    "LIVE_CANCEL_ACK",
    "build_pending_entry_cancel_route_design",
    "evaluate_pending_entry_lifecycle",
    "is_pending_entry_order",
    "replacement_allowed_same_thesis",
]
