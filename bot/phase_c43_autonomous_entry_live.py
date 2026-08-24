
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bot.live_order_size_policy import (
    MAX_LIVE_ORDER_QUOTE_USDC,
    bounded_exploration_report,
    live_order_size_policy_report,
    validate_entry_quote_size,
)
from bot.dynamic_entry_sizing import calculate_dynamic_entry_quote
from bot.order_lifecycle import (
    FINAL_ORDER_STATUSES,
    OPEN_ORDER_STATUSES,
    is_final_order_status,
    is_open_order_status,
    normalize_order_status,
)
from bot.order_store import OrderStore
from bot.coinbase_order_snapshot import normalized_filled_quote_value
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness
from bot.phase_c_live_submitter import prepare_mode_c_market_order_submission, prepare_phase_c_live_entry_submission
from bot.orderbook_entry_planner import build_resting_limit_entry_preview
from bot.product_rules import canonical_product_rules, execution_feasibility_context
from bot.config import effective_phase_c_allowed_tickers, configured_ticker_universe
from bot.autonomous_order_manager import build_pending_entry_lifecycle_preview
from bot.atomic_io import process_lock, runtime_mutation_lock_path
from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
from replication.lifecycle_publisher import build_lifecycle_order_event, publish_lifecycle_event_best_effort

ZERO = Decimal("0")
C43_PHASE = "C4.3_autonomous_entry_live_activation_fill_to_position_bridge"
C43_MAX_QUOTE = MAX_LIVE_ORDER_QUOTE_USDC
C43_MAX_OPEN_ORDERS = 4
C43_MANAGED_PREFIXES = ("phasec-",)
C43_FINAL_ORDER_STATUSES = FINAL_ORDER_STATUSES
C43_OPEN_ORDER_STATUSES = OPEN_ORDER_STATUSES
_C43_LIFECYCLE_APPLY_AUTHORITY = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _derive_entry_protective_levels(
    *,
    local_order: Dict[str, Any],
    trade_plan: Dict[str, Any],
    entry_price: Any,
    min_stop_distance_pct: Decimal,
) -> Dict[str, Any]:
    entry = _to_decimal(entry_price, "0")
    candidates_stop = (
        local_order.get("stop_price"),
        local_order.get("initial_stop_price"),
        local_order.get("invalidation_level"),
        trade_plan.get("initial_stop_price"),
        trade_plan.get("stop_price"),
        trade_plan.get("stop_loss_price"),
        trade_plan.get("stop_loss"),
        trade_plan.get("invalidation_price"),
        trade_plan.get("invalidation"),
    )
    candidates_invalidation = (
        local_order.get("invalidation_price"),
        local_order.get("invalidation_level"),
        trade_plan.get("invalidation_price"),
        trade_plan.get("invalidation"),
        trade_plan.get("initial_stop_price"),
        trade_plan.get("stop_price"),
        trade_plan.get("stop_loss_price"),
        trade_plan.get("stop_loss"),
    )

    def first_valid(values: Iterable[Any]) -> Decimal:
        for value in values:
            dec = _to_decimal(value, "0")
            if dec > ZERO and (entry <= ZERO or dec < entry):
                return dec
        return ZERO

    stop = first_valid(candidates_stop)
    invalidation = first_valid(candidates_invalidation)
    source = "explicit_entry_risk"
    if entry > ZERO:
        if stop <= ZERO:
            stop = entry * Decimal("0.975")
            source = "conservative_entry_fill_fallback"
        if invalidation <= ZERO:
            invalidation = stop
            source = "conservative_entry_fill_fallback"
        if stop >= entry:
            stop = entry * Decimal("0.975")
            source = "conservative_entry_fill_fallback"
        if invalidation >= entry:
            invalidation = stop
            source = "conservative_entry_fill_fallback"
        if min_stop_distance_pct > ZERO:
            floor = entry * (Decimal("1") - min_stop_distance_pct)
            if ZERO < stop < entry and stop > floor:
                stop = floor
                if source == "explicit_entry_risk":
                    source = "widened_to_minimum_stop_distance_floor"
            if ZERO < invalidation < entry and invalidation > floor:
                invalidation = floor
                if source == "explicit_entry_risk":
                    source = "widened_to_minimum_stop_distance_floor"
    complete = bool(entry > ZERO and stop > ZERO and invalidation > ZERO and stop < entry and invalidation < entry)
    return {
        "stop_price": str(stop if stop > ZERO else ZERO),
        "invalidation_price": str(invalidation if invalidation > ZERO else ZERO),
        "risk_state_complete": complete,
        "risk_source": source if complete else "missing_entry_risk",
    }


def _load_open_positions_from_state(path: str | Path = "state/positions.json") -> List[Dict[str, Any]]:
    state_path = Path(path)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    out: List[Dict[str, Any]] = []
    for ticker, value in payload.items():
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or "open").strip().lower()
        base = _to_decimal(value.get("bot_managed_base") or value.get("position_size_base") or value.get("base_size"), "0")
        if status in {"open", "active"} and base > ZERO:
            row = dict(value)
            row.setdefault("ticker", _normalize_ticker(ticker))
            out.append(row)
    return out


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_dec(cfg: Any, name: str, default: Decimal) -> Decimal:
    return _to_decimal(getattr(cfg, name, default), str(default))


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    try:
        return int(getattr(cfg, name, default))
    except Exception:
        return int(default)


def _apply_dynamic_entry_sizing(
    *,
    cfg: Any,
    analysis: Dict[str, Any],
    execution_plan: Dict[str, Any],
    order_intent: Dict[str, Any],
    product_rules: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Replace LLM quote intent with the deterministic live BUY quote.

    This is intentionally at the C4.3 boundary, immediately before the live
    risk guard and Coinbase payload builder.  Consequently no earlier planner
    or judge supplied quote can bypass the 10-20%-of-portfolio sizing policy.
    """
    sized_analysis = dict(analysis or {})
    sized_order = dict(order_intent or {})
    if not _cfg_bool(cfg, "enable_dynamic_entry_sizing", False):
        return sized_analysis, sized_order, {
            "enabled": False,
            "accepted": True,
            "final_reason": "dynamic_entry_sizing_disabled_by_config",
        }

    sizing = calculate_dynamic_entry_quote(
        cfg=cfg,
        analysis=sized_analysis,
        execution_plan=execution_plan,
        product_rules=product_rules,
    )
    quote = _to_decimal(sizing.get("clamped_quote"), "0")
    sized_order["size_quote"] = str(quote)
    sized_order["quote_size"] = str(quote)
    sized_order["dynamic_entry_sizing"] = sizing
    sized_analysis["dynamic_entry_sizing"] = sizing
    judge = _as_dict(sized_analysis.get("judge"))
    if judge:
        judge = dict(judge)
        judge["llm_requested_size_quote"] = judge.get("size_quote")
        judge["size_quote"] = float(quote)
        judge["dynamic_entry_sizing_reason"] = sizing.get("final_reason")
        sized_analysis["judge"] = judge
    return sized_analysis, sized_order, sizing


def _full_workflow_live_mode(cfg: Any) -> bool:
    return _cfg_bool(cfg, "enable_full_workflow_live_mode", False)


def _d3_exits_configured_for_full_workflow(cfg: Any) -> bool:
    return (
        _cfg_bool(cfg, "enable_live_exit_orders", False)
        and _cfg_bool(cfg, "autonomous_allow_exits", False)
        and _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False)
        and not _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True)
        and not _cfg_bool(cfg, "autonomous_entry_only_first", True)
    )


def _fresh_judge_live_buy_approval(analysis: Dict[str, Any]) -> Dict[str, Any]:
    judge = _as_dict(analysis.get("judge"))
    trade_plan = _as_dict(analysis.get("trade_plan"))
    decision = str(judge.get("decision") or "").strip().lower()
    side = str(judge.get("side") or "").strip().upper()
    judge_valid = _to_bool(judge.get("valid_trade_plan")) or _to_bool(judge.get("judge_response_valid_trade_plan"))
    plan_valid = _to_bool(trade_plan.get("valid_trade_plan"))
    valid_trade_plan = judge_valid or plan_valid
    return {
        "approved": bool(decision == "approve_trade" and side == "BUY" and valid_trade_plan),
        "decision": decision,
        "side": side,
        "valid_trade_plan": valid_trade_plan,
        "judge_valid_trade_plan": judge_valid,
        "trade_plan_valid_trade_plan": plan_valid,
    }


def _effective_product_rules(
    *,
    explicit: Optional[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]],
    order_intent: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if isinstance(explicit, dict) and explicit:
        return explicit
    order = _as_dict(order_intent)
    if isinstance(order.get("product_rules"), dict) and order.get("product_rules"):
        return _as_dict(order.get("product_rules"))
    analysis_dict = _as_dict(analysis)
    feature_pack = _as_dict(analysis_dict.get("feature_pack"))
    decision_context = _as_dict(feature_pack.get("decision_context"))
    for candidate in (
        decision_context.get("product_rules"),
        feature_pack.get("product_rules"),
        feature_pack.get("exchange_rules"),
        analysis_dict.get("product_rules"),
        analysis_dict.get("exchange_rules"),
    ):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def _allowed_tickers(cfg: Any) -> List[str]:
    return [_normalize_ticker(x) for x in effective_phase_c_allowed_tickers(cfg) if _normalize_ticker(x)]


def _exploration_allowed_tickers(cfg: Any) -> List[str]:
    return [_normalize_ticker(x) for x in _as_list(getattr(cfg, "exploration_allowed_tickers", [])) if _normalize_ticker(x)]


def _has_open_position_same_ticker(open_positions: Optional[Sequence[Dict[str, Any]]], ticker: str) -> bool:
    selected = _normalize_ticker(ticker)
    for position in open_positions or []:
        if not isinstance(position, dict):
            continue
        if _normalize_ticker(position.get("ticker") or position.get("product_id")) != selected:
            continue
        status = str(position.get("status") or "open").strip().lower()
        base = _to_decimal(position.get("bot_managed_base") or position.get("position_size_base") or position.get("base_size"), "0")
        if status in {"open", "active"} and base > ZERO:
            return True
    return False


def _client_order_id(order: Dict[str, Any]) -> str:
    return str(order.get("client_order_id") or order.get("client_order_id_preview") or order.get("id") or "").strip()


def _exchange_order_id(order: Dict[str, Any]) -> str:
    return str(order.get("order_id") or order.get("id") or order.get("exchange_order_id") or "").strip()


def _coinbase_response_order_id(response: Dict[str, Any]) -> str:
    """Extract Coinbase order id from both flat and Advanced Trade nested responses."""
    data = _as_dict(response)
    direct = str(data.get("order_id") or data.get("id") or data.get("exchange_order_id") or "").strip()
    if direct:
        return direct
    success = _as_dict(data.get("success_response"))
    nested = str(success.get("order_id") or success.get("id") or success.get("exchange_order_id") or "").strip()
    if nested:
        return nested
    # Some clients wrap the exchange response one level deeper. Keep this defensive
    # and schema-light so future SDK response variants still populate lifecycle ids.
    response_obj = _as_dict(data.get("response"))
    success2 = _as_dict(response_obj.get("success_response"))
    return str(
        response_obj.get("order_id")
        or response_obj.get("id")
        or success2.get("order_id")
        or success2.get("id")
        or ""
    ).strip()


def _order_status(order: Dict[str, Any]) -> str:
    status = str(order.get("status") or order.get("order_status") or "").strip().lower()
    if not status and _to_decimal(order.get("filled_size") or order.get("filled_size_base"), "0") > ZERO:
        return "partially_filled"
    return status or "unknown"


def _order_ticker(order: Dict[str, Any]) -> str:
    return _normalize_ticker(order.get("ticker") or order.get("product_id") or order.get("product"))


def _order_side(order: Dict[str, Any]) -> str:
    return str(order.get("side") or "").strip().upper()


def _extract_limit_gtc(order: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _as_dict(order.get("order_configuration"))
    return _as_dict(cfg.get("limit_limit_gtc") or cfg.get("limit_limit_ioc") or cfg.get("limit_limit_fok"))


def _limit_price(order: Dict[str, Any]) -> Decimal:
    gtc = _extract_limit_gtc(order)
    return _to_decimal(order.get("limit_price") or gtc.get("limit_price"), "0")


def _base_size(order: Dict[str, Any]) -> Decimal:
    gtc = _extract_limit_gtc(order)
    return _to_decimal(order.get("base_size") or order.get("size_base") or order.get("size_base_normalized") or gtc.get("base_size"), "0")


def _quote_size(order: Dict[str, Any]) -> Decimal:
    return _to_decimal(order.get("quote_size") or order.get("size_quote") or order.get("size_quote_normalized") or order.get("size_quote_requested"), "0")


def _filled_base(order: Dict[str, Any]) -> Decimal:
    return _to_decimal(order.get("filled_size_base") or order.get("filled_base") or order.get("filled_size") or order.get("completion_percentage_filled_size"), "0")


def _avg_fill_price(order: Dict[str, Any]) -> Decimal:
    return _to_decimal(order.get("avg_fill_price") or order.get("average_filled_price") or order.get("average_price") or order.get("filled_price") or _limit_price(order), "0")


def _is_managed_live_order(order: Dict[str, Any]) -> bool:
    cid = _client_order_id(order)
    mode = str(order.get("mode") or order.get("source_mode") or "").lower()
    return cid.startswith(C43_MANAGED_PREFIXES) or mode in {"live", "phase_c_live", "autonomous_small_live"}


def count_local_phase_c_live_entry_orders(order_store: Optional[OrderStore] = None) -> Dict[str, Any]:
    store = order_store or OrderStore()
    open_orders = []
    for order in store.open_entry_orders():
        if _is_managed_live_order(order):
            open_orders.append(order)
    return {
        "total_open_live_entry_orders": len(open_orders),
        "tickers": sorted({_order_ticker(o) for o in open_orders if _order_ticker(o)}),
        "orders": [_json_safe(o) for o in open_orders],
    }


def build_phase_c43_deterministic_live_risk_snapshot(
    *,
    cfg: Any,
    ticker: str,
    analysis: Optional[Dict[str, Any]],
    execution_plan: Optional[Dict[str, Any]],
    order_intent: Optional[Dict[str, Any]],
    open_live_entry_orders_count: int = 0,
    open_live_entry_order_tickers: Optional[Iterable[str]] = None,
    open_positions: Optional[Sequence[Dict[str, Any]]] = None,
    new_live_orders_this_cycle: int = 0,
    product_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the deterministic live-risk snapshot used by C.4.3.

    This is deliberately conservative. It accepts only entry-only BUY intents
    inside the autonomous hard caps. It never calls Coinbase and never submits.
    """
    ticker = _normalize_ticker(ticker)
    analysis = _as_dict(analysis)
    execution_plan = _as_dict(execution_plan)
    order = _as_dict(order_intent)
    judge = _as_dict(analysis.get("judge"))
    blockers: List[str] = []
    passed: List[str] = []
    warnings: List[str] = []

    allowed = set(_allowed_tickers(cfg))
    quote = _to_decimal(order.get("size_quote") or judge.get("size_quote") or judge.get("quote_size"), "0")
    # No longer hard-clamped to C43_MAX_QUOTE: entries scale with
    # portfolio_value_usdc (strategy_engine._apply_portfolio_based_entry_sizing
    # writes the current portfolio-scaled value onto both cfg fields below
    # every cycle), so clamping to the legacy fixed 100.00 here would silently
    # re-cap every entry back to the old fixed-USDC band. C43_MAX_QUOTE
    # remains the fallback default only for a cfg that has no override.
    max_quote = min(_cfg_dec(cfg, "phase_c_max_order_quote", C43_MAX_QUOTE), _cfg_dec(cfg, "autonomous_max_order_quote", C43_MAX_QUOTE))
    max_open = min(_cfg_int(cfg, "phase_c_max_open_entry_orders", C43_MAX_OPEN_ORDERS), _cfg_int(cfg, "autonomous_max_open_orders", C43_MAX_OPEN_ORDERS), C43_MAX_OPEN_ORDERS)
    max_new = min(_cfg_int(cfg, "phase_c_max_new_orders_per_cycle", 1), _cfg_int(cfg, "autonomous_max_new_orders_per_cycle", 1), 1)
    open_entry_tickers = {
        _normalize_ticker(value)
        for value in (open_live_entry_order_tickers or [])
        if _normalize_ticker(value)
    }
    limit_price = _to_decimal(order.get("limit_price"), "0")
    effective_rules = _effective_product_rules(explicit=product_rules, analysis=analysis, order_intent=order)
    product_rule_context = canonical_product_rules(ticker, effective_rules)
    execution_feasibility = execution_feasibility_context(
        ticker,
        quote,
        limit_price,
        product_rule_context,
        max_quote_size=max_quote,
    )
    action = str(execution_plan.get("execution_action") or order.get("execution_action") or "").strip().lower()
    side = str(order.get("side") or judge.get("side") or "").strip().upper()
    fresh_judge = _fresh_judge_live_buy_approval(analysis)
    decision = str(fresh_judge.get("decision") or "").strip().lower()
    orderbook_entry_preview = build_resting_limit_entry_preview(
        ticker=ticker,
        analysis=analysis,
        open_positions=open_positions,
        open_orders_count=open_live_entry_orders_count,
        new_orders_this_cycle=new_live_orders_this_cycle,
        max_quote=max_quote,
        max_open_orders=max_open,
        max_new_orders_per_cycle=max_new,
    )
    resting_entry_eligible = bool(orderbook_entry_preview.get("eligible"))
    pending_entry_lifecycle_preview = build_pending_entry_lifecycle_preview(orderbook_entry_preview)

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(_cfg_bool(cfg, "enable_autonomous_small_live_orderbook_mode", False), "autonomous_mode_enabled", "autonomous_mode_disabled")
    require(_cfg_bool(cfg, "enable_phase_c_live_small_limit_orders", False), "phase_c_small_live_enabled", "phase_c_small_live_disabled")
    require(_cfg_bool(cfg, "enable_live_limit_orders", False), "live_limit_orders_enabled", "live_limit_orders_disabled")
    require(_cfg_bool(cfg, "enable_live_entry_orders", False), "live_entry_orders_enabled", "live_entry_orders_disabled")
    exits_enabled = _cfg_bool(cfg, "enable_live_exit_orders", False) or _cfg_bool(cfg, "autonomous_allow_exits", False)
    full_workflow_exits_ok = _full_workflow_live_mode(cfg) and _d3_exits_configured_for_full_workflow(cfg)
    require((not exits_enabled) or full_workflow_exits_ok, "live_exits_disabled_or_d3_full_workflow_guarded", "live_exit_orders_enabled_without_full_workflow_d3_guards")
    require(_cfg_bool(cfg, "autonomous_entry_only_first", True) or full_workflow_exits_ok, "entry_only_first_or_full_workflow_d3_guarded", "entry_only_first_not_true_without_d3_full_workflow")
    require(_cfg_bool(cfg, "autonomous_require_post_only", True), "post_only_required", "post_only_not_required")
    require(bool(ticker), "ticker_present", "ticker_missing")
    require(bool(allowed) and ticker in allowed, "ticker_allowed", "ticker_not_allowed")
    market_action = action == "place_market_buy"
    require(action in {"place_limit_buy", "place_market_buy"}, "execution_action_place_buy", f"execution_action_not_place_buy:{action or 'missing'}")
    if bool(fresh_judge.get("approved")):
        passed.append("fresh_judge_approve_trade_buy_valid_plan")
    elif action == "place_limit_buy" and resting_entry_eligible:
        passed.append("resting_entry_preview_available_preview_only")
        blockers.append("fresh_judge_approve_trade_buy_valid_plan_required_for_live_entry")
    else:
        blockers.append("judge_not_approve_trade_buy_or_valid_trade_plan_missing")
    if decision == "wait":
        blockers.append("blocked_wait_decision_cannot_live_submit")
    elif decision != "approve_trade":
        blockers.append("blocked_missing_fresh_approve_trade")
    if side != "BUY":
        blockers.append("blocked_missing_fresh_approve_trade")
    if not bool(fresh_judge.get("valid_trade_plan")):
        blockers.append("blocked_valid_trade_plan_false")
    require(side == "BUY", "side_buy", f"side_not_buy:{side or 'missing'}")
    quote_policy = validate_entry_quote_size(quote, cfg)
    require(quote_policy["accepted"] and quote <= max_quote, "quote_within_autonomous_cap", (quote_policy["blockers"] or ["quote_missing_or_above_autonomous_cap"])[0])
    if market_action:
        passed.append("mode_c_market_buy_intent_present")
    else:
        require(limit_price > ZERO, "limit_price_present", "limit_price_missing")
        require(bool(product_rule_context.get("precision_context_available")), "product_precision_context_available", "product_precision_context_missing")
        require(bool(execution_feasibility.get("can_construct_valid_limit_buy_payload")), "valid_limit_buy_payload_constructible", "valid_limit_buy_payload_not_constructible")
    require(open_live_entry_orders_count < max_open, "open_order_capacity_available", "max_open_live_entry_orders_reached")
    require(ticker not in open_entry_tickers, "no_duplicate_open_live_entry_order_same_ticker", "duplicate_open_live_entry_order_same_ticker")
    require(ticker not in open_entry_tickers, "no_open_order_same_ticker", "blocked_open_order_same_ticker")
    require(not _has_open_position_same_ticker(open_positions, ticker), "no_open_position_same_ticker", "blocked_open_position_same_ticker")
    require(new_live_orders_this_cycle < max_new, "new_order_cycle_capacity_available", "new_order_cycle_budget_exhausted")

    orderbook = _as_dict(execution_plan.get("orderbook_summary"))
    if bool(getattr(cfg, "phase_c_require_orderbook_freshness", True)):
        require(bool(orderbook.get("snapshot_available")), "orderbook_snapshot_available", "orderbook_snapshot_missing")
        freshness = str(orderbook.get("freshness_status") or "").lower()
        require(freshness in {"fresh", ""}, "orderbook_fresh_or_unspecified", f"orderbook_not_fresh:{freshness or 'missing'}")

    if _cfg_bool(cfg, "enable_bounded_exploration_mode", False):
        require(not _cfg_bool(cfg, "exploration_allow_market_orders", False), "bounded_exploration_market_orders_disabled", "bounded_exploration_market_orders_enabled")
        exploration_min = _cfg_dec(cfg, "exploration_min_order_quote_usdc", Decimal("20.00"))
        exploration_max = _cfg_dec(cfg, "exploration_max_order_quote_usdc", Decimal("35.00"))
        require(quote >= exploration_min, "bounded_exploration_quote_above_min", "bounded_exploration_quote_below_min")
        require(quote <= exploration_max, "bounded_exploration_quote_below_max", "bounded_exploration_quote_above_max")
        exploration_allowed = set(_exploration_allowed_tickers(cfg))
        require(bool(exploration_allowed) and ticker in exploration_allowed, "bounded_exploration_ticker_allowed", "bounded_exploration_ticker_not_allowed")
        if _cfg_bool(cfg, "exploration_require_orderbook_snapshot", True):
            require(bool(orderbook.get("snapshot_available")), "bounded_exploration_orderbook_snapshot_available", "bounded_exploration_orderbook_snapshot_missing")
        spread = _to_decimal(orderbook.get("spread_pct"), "0")
        max_spread = _cfg_dec(cfg, "exploration_max_spread_pct", Decimal("0.0040"))
        require(spread <= max_spread, "bounded_exploration_spread_within_cap", "bounded_exploration_spread_above_cap")
        trade_plan = _as_dict(analysis.get("trade_plan"))
        pending_ctx = _as_dict((_as_dict(_as_dict(analysis.get("feature_pack")).get("decision_context"))).get("pending_order_intent"))
        trigger_ready = _to_bool(pending_ctx.get("trigger_ready")) or str(pending_ctx.get("status") or "").lower() in {"trigger_ready", "needs_fresh_analysis"} or bool(str(trade_plan.get("trigger") or "").strip())
        if _cfg_bool(cfg, "exploration_require_fresh_trigger", True):
            require(trigger_ready, "bounded_exploration_fresh_trigger_present", "bounded_exploration_fresh_trigger_missing")
        do_not_chase_above = _to_decimal(trade_plan.get("do_not_chase_above"), "0")
        if _cfg_bool(cfg, "exploration_require_no_chase", True):
            require(market_action or do_not_chase_above <= ZERO or limit_price <= do_not_chase_above, "bounded_exploration_no_chase_ok", "bounded_exploration_do_not_chase_above_breached")
        stop_loss = _to_decimal(trade_plan.get("stop_loss") or trade_plan.get("invalidation"), "0")
        require(bool(str(trade_plan.get("trigger") or "").strip()) and stop_loss > ZERO, "bounded_exploration_defined_risk_present", "bounded_exploration_defined_risk_missing")

    if quote > ZERO and quote < Decimal("1.00"):
        warnings.append("quote_below_typical_coinbase_min_notional_check_product_rules")

    blockers = list(dict.fromkeys(blockers))
    passed = list(dict.fromkeys(passed))
    accepted = not blockers
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": C43_PHASE,
        "ticker": ticker,
        "mode": "autonomous_small_live_entry_risk",
        "accepted": accepted,
        "approved": accepted,
        "risk_approved": accepted,
        "side": "BUY" if side == "BUY" else side,
        "order_type": "market" if market_action else "limit",
        "post_only": False if market_action else True,
        "max_quote": str(max_quote),
        "max_open_orders": max_open,
        "max_new_orders_per_cycle": max_new,
        "quote_size": str(quote),
        "fresh_judge_live_buy_approval": fresh_judge,
        "live_order_size_policy": live_order_size_policy_report(cfg),
        "bounded_exploration": bounded_exploration_report(cfg),
        "quote_size_policy": quote_policy,
        "limit_price": str(limit_price) if limit_price > ZERO else "0",
        "open_live_entry_orders_count": int(open_live_entry_orders_count),
        "open_live_entry_order_tickers": sorted(open_entry_tickers),
        "new_live_orders_this_cycle": int(new_live_orders_this_cycle),
        "blockers": blockers,
        "passed_checks": passed,
        "warnings": warnings,
        "orderbook_entry_preview": orderbook_entry_preview,
        "product_rules": product_rule_context,
        "recent_exchange_rejections": list(order.get("recent_exchange_rejections") or []),
        "execution_feasibility": execution_feasibility,
        "pending_entry_lifecycle_preview": pending_entry_lifecycle_preview,
        "orderbook_entry_candidate": bool(resting_entry_eligible),
        "resting_entry_eligible": bool(resting_entry_eligible),
        "resting_entry_reason": orderbook_entry_preview.get("reason"),
        "preferred_limit_price": orderbook_entry_preview.get("entry_level"),
        "entry_route_type": orderbook_entry_preview.get("entry_route_type"),
        "pending_entry_preview_created": bool(resting_entry_eligible),
        "live_resting_entry_submit_enabled": _cfg_bool(cfg, "enable_resting_limit_entry_live_submit", False),
        "live_resting_entry_submit_attempted": False,
        "reason": "accepted_autonomous_small_live_entry" if accepted else "blocked_autonomous_small_live_entry",
        "safety_policy": {
            "deterministic_no_llm_permission_fabrication": True,
            "entry_only_buy_only": True,
            "resting_entry_preview_is_not_live_permission": True,
            "fresh_approve_trade_buy_valid_plan_required_for_live_submit": True,
            "same_ticker_open_entry_order_blocks_live_submit": True,
            "max_quote_100_usdc": True,
            "max_open_orders_4": True,
            "post_only_required": not market_action,
            "market_orders_require_mode_c_governance": market_action,
            "live_exits_only_through_d3_full_workflow": True,
        },
    })


def _build_phase_c43_guard_and_submit_preparation_unlocked(
    *,
    cfg: Any,
    ticker: str,
    analysis: Dict[str, Any],
    execution_plan: Optional[Dict[str, Any]],
    order_intent: Optional[Dict[str, Any]],
    coinbase_client: Any = None,
    order_store: Optional[OrderStore] = None,
    new_live_orders_this_cycle: int = 0,
    submit_live: bool = False,
    product_rules: Optional[Dict[str, Any]] = None,
    open_positions: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Prepare and optionally submit one autonomous live entry order.

    This is the C.4.3 bridge used by StrategyEngine. It only calls Coinbase when
    every guard is green, cfg allows actual submit, submit_live=True and a client
    is provided. It also records submitted orders in OrderStore so later fill
    reconciliation can connect live orders back to local state.
    """
    ticker = _normalize_ticker(ticker)
    store = order_store or OrderStore()
    analysis, order_intent, dynamic_entry_sizing = _apply_dynamic_entry_sizing(
        cfg=cfg,
        analysis=_as_dict(analysis),
        execution_plan=_as_dict(execution_plan),
        order_intent=_as_dict(order_intent),
        product_rules=product_rules,
    )
    counts = count_local_phase_c_live_entry_orders(store)
    open_count = int(counts.get("total_open_live_entry_orders") or 0)
    effective_open_positions = list(open_positions) if open_positions is not None else _load_open_positions_from_state()
    risk = build_phase_c43_deterministic_live_risk_snapshot(
        cfg=cfg,
        ticker=ticker,
        analysis=analysis,
        execution_plan=execution_plan or {},
        order_intent=order_intent or {},
        open_live_entry_orders_count=open_count,
        open_live_entry_order_tickers=counts.get("tickers") or [],
        open_positions=effective_open_positions,
        new_live_orders_this_cycle=new_live_orders_this_cycle,
        product_rules=product_rules,
    )
    risk["dynamic_entry_sizing"] = dynamic_entry_sizing
    effective_rules = _effective_product_rules(explicit=product_rules, analysis=analysis, order_intent=order_intent)
    guard = evaluate_phase_c_live_entry_readiness(
        cfg=cfg,
        ticker=ticker,
        analysis=analysis,
        execution_plan=execution_plan or {},
        order_intent=order_intent or {},
        live_risk_result=risk,
        open_live_entry_orders_count=open_count,
        open_live_entry_order_tickers=counts.get("tickers") or [],
        open_positions=effective_open_positions,
        new_live_orders_this_cycle=new_live_orders_this_cycle,
        product_rules=effective_rules,
    )
    action = str((execution_plan or {}).get("execution_action") or (order_intent or {}).get("execution_action") or "").strip().lower()
    if action == "place_market_buy":
        submit_result = prepare_mode_c_market_order_submission(
            cfg=cfg,
            ticker=ticker,
            side="BUY",
            order_intent=order_intent or {},
            analysis=analysis,
            execution_plan=execution_plan or {},
            live_risk_result=risk,
            existing_position=None,
            coinbase_client=coinbase_client,
            submit_live=bool(submit_live),
            open_orders_count=open_count,
            open_positions_count=0,
            new_orders_this_cycle=new_live_orders_this_cycle,
            duplicate_open_order=False,
            open_d3_exit_exists=False,
            reason="phase_c43_mode_c_market_buy",
        )
        return _json_safe({
            "generated_at": _now_iso(),
            "phase": C43_PHASE,
            "ticker": ticker,
            "status": "c43_mode_c_market_entry_submitted" if submit_result.get("live_order_submitted") else "c43_mode_c_market_entry_blocked_or_preview",
            "submit_allowed_by_c43": bool(submit_result.get("status") == "mode_c_market_order_ready"),
            "live_submission_attempted": bool(submit_result.get("live_submission_attempted")),
            "live_order_submitted": bool(submit_result.get("live_order_submitted")),
            "risk_snapshot": risk,
            "dynamic_entry_sizing": dynamic_entry_sizing,
            "guard_result": submit_result.get("guard_result"),
            "submit_result": submit_result,
            "local_order_record": None,
            "open_live_entry_order_counts": counts,
            "safety_policy": {
                "entry_only": True,
                "order_type": "market",
                "requires_mode_c_market_order_ack": True,
                "replication_must_be_disabled": True,
                "requires_submit_live_true_and_actual_submit_flag": True,
                "max_100_usdc_order": True,
                "max_3_open_orders": True,
            },
        })
    submit_allowed_by_c43 = (
        bool(getattr(cfg, "enable_phase_c43_autonomous_entry_submitter", True))
        and bool(getattr(cfg, "enable_autonomous_small_live_orderbook_mode", False))
        and bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))
        and (
            str(getattr(cfg, "phase_c43_runtime_submit_ack", "") or "").strip()
            == C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
        )
        and (
            not bool(getattr(cfg, "enable_live_exit_orders", False))
            or (_full_workflow_live_mode(cfg) and _d3_exits_configured_for_full_workflow(cfg))
        )
        and bool(risk.get("accepted"))
        and bool(guard.get("guard_allows_live_submit"))
        and submit_live
        and coinbase_client is not None
    )
    submit_result = prepare_phase_c_live_entry_submission(
        cfg=cfg,
        ticker=ticker,
        order_intent=order_intent or {},
        guard_result=guard,
        coinbase_client=coinbase_client if submit_allowed_by_c43 else coinbase_client,
        product_rules=effective_rules,
        submit_live=bool(submit_allowed_by_c43),
    )
    status = "c43_autonomous_live_entry_blocked"
    if submit_result.get("live_order_submitted"):
        status = "c43_autonomous_live_entry_submitted"
    elif submit_result.get("live_submission_attempted"):
        status = "c43_autonomous_live_entry_attempted_not_submitted"
    elif bool(risk.get("accepted")) and bool(guard.get("guard_allows_live_submit")):
        status = "c43_ready_but_submit_not_armed"

    local_order_record = None
    if submit_result.get("live_order_submitted"):
        payload = _as_dict(submit_result.get("payload"))
        preview = _as_dict(payload.get("coinbase_payload_preview"))
        gtc = _extract_limit_gtc(preview)
        response = _as_dict(submit_result.get("coinbase_response"))
        order_id = _coinbase_response_order_id(response)
        client_oid = str(preview.get("client_order_id") or payload.get("client_order_id") or "")
        trade_plan_snapshot = _as_dict(analysis.get("trade_plan"))
        protective_levels = _derive_entry_protective_levels(
            local_order=order_intent or {},
            trade_plan=trade_plan_snapshot,
            entry_price=gtc.get("limit_price") or payload.get("limit_price") or payload.get("limit_price_requested"),
            min_stop_distance_pct=_to_decimal(getattr(cfg, "stop_distance_pct", None), "0.02"),
        )
        record = {
            "client_order_id": client_oid,
            "exchange_order_id": order_id,
            "order_id": order_id,
            "ticker": ticker,
            "product_id": ticker,
            "side": "BUY",
            "status": "submitted",
            "mode": "live",
            "source_mode": "autonomous_small_live",
            "phase": C43_PHASE,
            "created_at": _now_iso(),
            "size_base": str(gtc.get("base_size") or payload.get("size_base_normalized") or "0"),
            "size_quote": str(payload.get("size_quote_normalized") or payload.get("size_quote_requested") or "0"),
            "remaining_quote": str(payload.get("size_quote_normalized") or payload.get("size_quote_requested") or "0"),
            "remaining_size": str(gtc.get("base_size") or payload.get("size_base_normalized") or "0"),
            "limit_price": str(gtc.get("limit_price") or payload.get("limit_price") or "0"),
            "post_only": bool(gtc.get("post_only", True)),
            "execution_action": "place_limit_buy",
            "risk_snapshot": risk,
            "guard_snapshot": guard,
            "trade_plan_snapshot": trade_plan_snapshot,
            "stop_price": protective_levels["stop_price"],
            "invalidation_price": protective_levels["invalidation_price"],
            "entry_risk_source": protective_levels["risk_source"],
            "entry_risk_state_complete": protective_levels["risk_state_complete"],
            "coinbase_response": response,
            "opened_via_phase_c43": True,
        }
        local_order_record = store.upsert_order(record, event_type="phase_c43_live_entry_order_submitted")
        lifecycle_event = build_lifecycle_order_event(
            event_type="c4_entry_order",
            ticker=ticker,
            order={
                "product_id": ticker,
                "side": "BUY",
                "client_order_id": client_oid,
                "exchange_order_id": order_id,
                "limit_price": str(record.get("limit_price") or ""),
                "quote_size": str(record.get("size_quote") or ""),
                "base_size": str(record.get("size_base") or ""),
                "phase": "C4.3",
            },
            metadata={"source_phase": C43_PHASE},
        )
        lifecycle_publish_result = publish_lifecycle_event_best_effort(lifecycle_event)
        if isinstance(local_order_record, dict):
            local_order_record = dict(local_order_record)
            local_order_record["replication_lifecycle_publish_result"] = lifecycle_publish_result
    elif submit_result.get("live_submission_attempted") and str(submit_result.get("status") or "") in {"phase_c_live_order_rejected_by_coinbase", "phase_c_live_order_submit_unconfirmed_no_order_id"}:
        payload = _as_dict(submit_result.get("payload"))
        preview = _as_dict(payload.get("coinbase_payload_preview"))
        gtc = _extract_limit_gtc(preview)
        response = _as_dict(submit_result.get("coinbase_response"))
        client_oid = str(preview.get("client_order_id") or payload.get("client_order_id") or "")
        now = _now_iso()
        trade_plan_snapshot = _as_dict(analysis.get("trade_plan"))
        protective_levels = _derive_entry_protective_levels(
            local_order=order_intent or {},
            trade_plan=trade_plan_snapshot,
            entry_price=gtc.get("limit_price") or payload.get("limit_price") or payload.get("limit_price_requested"),
            min_stop_distance_pct=_to_decimal(getattr(cfg, "stop_distance_pct", None), "0.02"),
        )
        record = {
            "client_order_id": client_oid,
            "exchange_order_id": "",
            "order_id": "",
            "ticker": ticker,
            "product_id": ticker,
            "side": "BUY",
            "status": "submit_rejected",
            "mode": "live",
            "source_mode": "autonomous_small_live",
            "phase": C43_PHASE,
            "created_at": now,
            "finalized_at": now,
            "closed_at": now,
            "rejected_at": now,
            "size_base": str(gtc.get("base_size") or payload.get("size_base_normalized") or "0"),
            "size_quote": str(payload.get("size_quote_normalized") or payload.get("size_quote_requested") or "0"),
            "remaining_quote": "0",
            "remaining_size": "0",
            "limit_price": str(gtc.get("limit_price") or payload.get("limit_price") or "0"),
            "post_only": bool(gtc.get("post_only", True)),
            "execution_action": "place_limit_buy",
            "risk_snapshot": risk,
            "guard_snapshot": guard,
            "trade_plan_snapshot": trade_plan_snapshot,
            "stop_price": protective_levels["stop_price"],
            "invalidation_price": protective_levels["invalidation_price"],
            "entry_risk_source": protective_levels["risk_source"],
            "entry_risk_state_complete": protective_levels["risk_state_complete"],
            "coinbase_response": response,
            "reject_reason": submit_result.get("reject_reason"),
            "reject_message": submit_result.get("reject_message"),
            "preview_failure_reason": submit_result.get("preview_failure_reason"),
            "opened_via_phase_c43": True,
            "position_created": False,
            "d2_plan_created": False,
            "live_exit_order_created": False,
            "lifecycle_orchestrator_note": "coinbase_submit_rejected_no_position_created",
        }
        local_order_record = store.upsert_order(record, event_type="phase_c43_live_entry_order_submit_rejected")

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": C43_PHASE,
        "ticker": ticker,
        "status": status,
        "submit_allowed_by_c43": submit_allowed_by_c43,
        "live_submission_attempted": bool(submit_result.get("live_submission_attempted")),
        "live_order_submitted": bool(submit_result.get("live_order_submitted")),
        "risk_snapshot": risk,
        "dynamic_entry_sizing": dynamic_entry_sizing,
        "guard_result": guard,
        "submit_result": submit_result,
        "local_order_record": local_order_record,
        "open_live_entry_order_counts": counts,
        "safety_policy": {
            "entry_only": True,
            "live_exits_only_through_d3_full_workflow": True,
            "requires_c43_risk_and_phase_c_guard": True,
            "requires_submit_live_true_and_actual_submit_flag": True,
            "runtime_authority_required_for_live_submit": True,
            "max_100_usdc_order": True,
            "max_4_open_orders": True,
        },
    })


def build_phase_c43_guard_and_submit_preparation(
    *,
    cfg: Any,
    ticker: str,
    analysis: Dict[str, Any],
    execution_plan: Optional[Dict[str, Any]],
    order_intent: Optional[Dict[str, Any]],
    coinbase_client: Any = None,
    order_store: Optional[OrderStore] = None,
    new_live_orders_this_cycle: int = 0,
    submit_live: bool = False,
    product_rules: Optional[Dict[str, Any]] = None,
    open_positions: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Prepare C.4.3, locking only an explicitly requested live boundary."""
    if not submit_live:
        return _build_phase_c43_guard_and_submit_preparation_unlocked(
            cfg=cfg,
            ticker=ticker,
            analysis=analysis,
            execution_plan=execution_plan,
            order_intent=order_intent,
            coinbase_client=coinbase_client,
            order_store=order_store,
            new_live_orders_this_cycle=new_live_orders_this_cycle,
            submit_live=False,
            product_rules=product_rules,
            open_positions=open_positions,
        )

    with process_lock(
        runtime_mutation_lock_path(cfg=cfg, order_store=order_store),
        allow_reentrant=True,
    ) as lock_info:
        report = _build_phase_c43_guard_and_submit_preparation_unlocked(
            cfg=cfg,
            ticker=ticker,
            analysis=analysis,
            execution_plan=execution_plan,
            order_intent=order_intent,
            coinbase_client=coinbase_client,
            order_store=order_store,
            new_live_orders_this_cycle=new_live_orders_this_cycle,
            submit_live=True,
            product_rules=product_rules,
            open_positions=open_positions,
        )
    report["mutation_lock"] = {
        "acquired": True,
        "reentrant": bool(lock_info.get("reentrant")),
    }
    return report


def _summarize_fills(fills: Iterable[Dict[str, Any]], *, fallback_price: Any = None) -> Dict[str, Any]:
    total_base = ZERO
    total_quote = ZERO
    count = 0
    for fill in fills or []:
        if not isinstance(fill, dict):
            continue
        count += 1
        price = _to_decimal(fill.get("price") or fill.get("fill_price") or fallback_price, "0")
        size = _to_decimal(fill.get("size") or fill.get("filled_size") or fill.get("base_size"), "0")
        quote = _to_decimal(fill.get("quote_size") or fill.get("filled_value") or fill.get("commissionless_value") or fill.get("trade_value"), "0")
        size_in_quote = _to_bool(fill.get("size_in_quote"), False)
        if size_in_quote:
            if quote <= ZERO:
                quote = size
            base = (quote / price) if price > ZERO else ZERO
        else:
            base = size
            if quote <= ZERO and price > ZERO and base > ZERO:
                quote = base * price
        total_base += max(ZERO, base)
        total_quote += max(ZERO, quote)
    avg_price = (total_quote / total_base) if total_base > ZERO and total_quote > ZERO else _to_decimal(fallback_price, "0")
    return {"fill_count": count, "filled_base": str(total_base), "filled_quote": str(total_quote), "avg_fill_price": str(avg_price)}


def _nested_raw_order(raw: Dict[str, Any]) -> Dict[str, Any]:
    nested = raw.get("raw_order")
    if isinstance(nested, dict):
        deeper = nested.get("raw_order")
        if isinstance(deeper, dict):
            return deeper
        return nested
    return {}


def _filled_quote(raw: Dict[str, Any], *, filled_base: Decimal, avg_price: Decimal) -> Decimal:
    fills_summary = raw.get("fills_summary") if isinstance(raw.get("fills_summary"), dict) else {}
    return normalized_filled_quote_value(
        raw,
        filled_base=filled_base,
        avg_fill_price=avg_price,
        fallback_local_order=raw,
        fills_summary=fills_summary,
    )


def _normalize_live_order_snapshot(order: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(order or {})
    filled_base = _filled_base(raw)
    avg_price = _avg_fill_price(raw)
    filled_quote = _filled_quote(raw, filled_base=filled_base, avg_price=avg_price)
    return _json_safe({
        "client_order_id": _client_order_id(raw),
        "exchange_order_id": _exchange_order_id(raw),
        "ticker": _order_ticker(raw),
        "side": _order_side(raw),
        "status": _order_status(raw),
        "limit_price": str(_limit_price(raw)),
        "base_size": str(_base_size(raw)),
        "quote_size": str(_quote_size(raw)),
        "filled_base": str(filled_base),
        "filled_quote": str(filled_quote),
        "avg_fill_price": str(avg_price),
        "managed_by_phase_c43": _is_managed_live_order(raw),
        "raw": raw,
    })


def _lifecycle_mutation_lock_path(*, cfg: Any, order_store: Optional[OrderStore]) -> Path:
    """Return the runtime-wide mutation lock without touching state in preview."""
    return runtime_mutation_lock_path(cfg=cfg, order_store=order_store)


def _reconcile_phase_c43_fills_to_positions_unlocked(
    *,
    cfg: Any,
    order_store: Optional[OrderStore] = None,
    state_store: Any = None,
    coinbase_client: Any = None,
    live_orders_snapshot: Optional[List[Dict[str, Any]]] = None,
    allow_coinbase_poll: bool = False,
    tickers: Optional[List[str]] = None,
    apply_local: bool = False,
) -> Dict[str, Any]:
    """Reconcile Phase-C live BUY order fills into local OrderStore/StateStore.

    The function can run from snapshots in tests/tools or, when explicitly
    allowed and a Coinbase client is supplied, inspect the known local live
    orders. It never places new orders and never creates live exit orders.
    """
    store = order_store or OrderStore()
    selected_tickers = {_normalize_ticker(t) for t in (tickers or []) if _normalize_ticker(t)}
    # A filled order without a linked local position is a recoverable
    # incomplete transition (for example a process crash after the position
    # write).  Keep it visible until the link is durably committed.
    local_orders = [
        o
        for o in store.all_orders()
        if _is_managed_live_order(o)
        and (
            is_open_order_status(o.get("status"))
            or (
                normalize_order_status(o.get("status")) == "filled"
                and not bool(o.get("position_created"))
            )
        )
    ]
    if selected_tickers:
        local_orders = [o for o in local_orders if _order_ticker(o) in selected_tickers]

    live_by_key: Dict[str, Dict[str, Any]] = {}
    coinbase_call_attempted = False
    coinbase_call_succeeded = False
    errors: List[Dict[str, str]] = []

    for snap in live_orders_snapshot or []:
        norm = _normalize_live_order_snapshot(snap)
        key = norm.get("client_order_id") or norm.get("exchange_order_id")
        if key:
            live_by_key[str(key)] = norm

    if allow_coinbase_poll and coinbase_client is not None:
        for local in local_orders:
            oid = str(local.get("exchange_order_id") or local.get("order_id") or "").strip()
            if not oid:
                continue
            coinbase_call_attempted = True
            try:
                payload = coinbase_client.get_order(oid)
                order_obj = _as_dict(payload.get("order") if isinstance(payload, dict) else payload)
                if not order_obj and isinstance(payload, dict):
                    order_obj = payload
                norm = _normalize_live_order_snapshot(order_obj)
                key = norm.get("client_order_id") or str(local.get("client_order_id") or oid)
                norm.setdefault("client_order_id", str(local.get("client_order_id") or ""))
                norm.setdefault("exchange_order_id", oid)
                live_by_key[str(key)] = norm
                coinbase_call_succeeded = True
            except Exception as exc:
                errors.append({"order_id": oid, "error_type": type(exc).__name__, "error": str(exc)})

    actions: List[Dict[str, Any]] = []
    for local in local_orders:
        cid = str(local.get("client_order_id") or "")
        oid = str(local.get("exchange_order_id") or local.get("order_id") or "")
        live = live_by_key.get(cid) or live_by_key.get(oid) or {}
        if not live and normalize_order_status(local.get("status")) == "filled":
            # The order itself is durable fill evidence for recovery only when
            # its terminal filled status and quantities were already persisted.
            live = _normalize_live_order_snapshot(local)
        if not live:
            actions.append({"client_order_id": cid, "ticker": _order_ticker(local), "action": "no_live_snapshot", "status": "skipped"})
            continue
        status = normalize_order_status(live.get("status"))
        filled_base = _to_decimal(live.get("filled_base"), "0")
        avg_price = _to_decimal(live.get("avg_fill_price") or local.get("limit_price"), "0")
        fills_summary: Optional[Dict[str, Any]] = None
        if allow_coinbase_poll and coinbase_client is not None and oid:
            try:
                fills = coinbase_client.get_recent_fills_for_order(oid, limit=100)
                fills_summary = _summarize_fills(fills, fallback_price=avg_price)
                filled_base = max(filled_base, _to_decimal(fills_summary.get("filled_base"), "0"))
                avg_price = _to_decimal(fills_summary.get("avg_fill_price"), str(avg_price))
            except Exception as exc:
                errors.append({"order_id": oid, "error_type": type(exc).__name__, "error": str(exc)})
        is_final_fill = status == "filled" or (filled_base > ZERO and is_final_order_status(status))
        is_partial = filled_base > ZERO and not is_final_fill
        ticker = _order_ticker(local) or _normalize_ticker(live.get("ticker"))
        if is_partial:
            if not apply_local:
                actions.append({
                    "client_order_id": cid,
                    "ticker": ticker,
                    "action": "partial_fill_record_proposed",
                    "state_write_performed": False,
                    "order_write_performed": False,
                })
                continue
            updated = store.update_order(cid, {
                "status": "partially_filled",
                "filled_size": str(filled_base),
                "filled_size_base": str(filled_base),
                "avg_fill_price": str(avg_price),
                "last_live_order_snapshot": live,
                "last_fills_summary": fills_summary,
            }, event_type="phase_c43_live_entry_order_partially_filled")
            actions.append({"client_order_id": cid, "ticker": ticker, "action": "partial_fill_recorded", "order": updated})
            continue
        if is_final_fill and filled_base > ZERO:
            filled_quote_dec = _to_decimal(fills_summary.get("filled_quote") if fills_summary else None, "0")
            if filled_quote_dec <= ZERO:
                filled_quote_dec = _to_decimal(live.get("filled_quote"), "0")
            if filled_quote_dec <= ZERO and filled_base > ZERO and avg_price > ZERO:
                filled_quote_dec = filled_base * avg_price
            filled_quote = str(filled_quote_dec)
            if not apply_local:
                actions.append({
                    "client_order_id": cid,
                    "ticker": ticker,
                    "action": "fill_to_position_proposed",
                    "state_write_performed": False,
                    "order_write_performed": False,
                })
                continue
            if state_store is None:
                actions.append({
                    "client_order_id": cid,
                    "ticker": ticker,
                    "action": "blocked_state_store_missing",
                    "state_write_performed": False,
                    "order_write_performed": False,
                })
                continue
            position = None
            position_transition = "created_from_fill"
            existing_position = state_store.get_position(ticker) if hasattr(state_store, "get_position") else None
            existing_position_status = str((existing_position or {}).get("status") or "open").strip().lower()
            # A closed position left under this ticker key (positions.json keeps a
            # permanent record per ticker, not per trade) must not be treated as a
            # live conflict: it belongs to a prior, already-closed trade, so a fresh
            # fill under a different order id is a legitimate re-entry, not an
            # ambiguous double-open. Only a still-open/active record under this
            # ticker with unrelated order ids is a genuine conflict worth blocking.
            if isinstance(existing_position, dict) and existing_position_status in {"open", "active"}:
                known_fill_ids = {
                    str(existing_position.get("phase_c43_client_order_id") or "").strip(),
                    str(existing_position.get("phase_c43_exchange_order_id") or "").strip(),
                    str(existing_position.get("source_entry_order_id") or "").strip(),
                    str(existing_position.get("order_id") or "").strip(),
                }
                known_fill_ids.discard("")
                if {cid, oid}.intersection(known_fill_ids):
                    position = existing_position
                    position_transition = "recovered_existing_position"
                else:
                    actions.append({
                        "client_order_id": cid,
                        "ticker": ticker,
                        "action": "blocked_existing_position_not_linked_to_fill",
                        "state_write_performed": False,
                        "order_write_performed": False,
                    })
                    continue
            else:
                extra = {
                    "opened_via_phase_c43_live_order": True,
                    "phase_c43_client_order_id": cid,
                    "phase_c43_exchange_order_id": oid,
                    "source_entry_order_id": oid or cid,
                    "phase_c43_fills_summary": fills_summary or {},
                    "inventory_sell_enabled": False,
                    "inventory_sell_mode": "bot_only",
                }
                trade_plan = _as_dict(local.get("trade_plan_snapshot") or local.get("trade_plan"))
                protective_levels = _derive_entry_protective_levels(
                    local_order=local,
                    trade_plan=trade_plan,
                    entry_price=avg_price,
                    min_stop_distance_pct=_to_decimal(getattr(cfg, "stop_distance_pct", None), "0.02"),
                )
                stop_price = protective_levels["stop_price"]
                invalidation_price = protective_levels["invalidation_price"]
                setup_type_value = str(local.get("setup_type") or trade_plan.get("setup_type") or "")
                extra.update({
                    "source_trade_plan_id": str(local.get("trade_plan_id") or trade_plan.get("plan_id") or ""),
                    # setup_type (not just the source_* audit copy) is what
                    # position_manager._get_position_setup_type() actually
                    # reads to pick a trailing-stop tier (trend_continuation /
                    # reclaim_reversal / mean_reversion). Before this fix only
                    # source_setup_type was ever set here, so every live
                    # position silently fell back to the generic "unclear"
                    # tier regardless of its real setup.
                    "setup_type": setup_type_value,
                    "source_setup_type": setup_type_value,
                    "stop_price": stop_price,
                    "invalidation_price": invalidation_price,
                    "entry_risk_source": protective_levels["risk_source"],
                    "entry_risk_state_complete": protective_levels["risk_state_complete"],
                    "protective_stop_status": (
                        "protective_stop_state_complete"
                        if protective_levels["risk_state_complete"]
                        else "position_risk_incomplete"
                    ),
                    "position_risk_incomplete": not protective_levels["risk_state_complete"],
                    "d2_plan_status": "pending",
                    "d3_exit_status": "pending",
                    "last_risk_check_at": _now_iso(),
                })
                if hasattr(state_store, "create_position"):
                    position = state_store.create_position(
                        ticker=ticker,
                        side="BUY",
                        order_id=oid or cid,
                        entry_price=str(avg_price),
                        position_size_base=str(filled_base),
                        position_size_quote=filled_quote,
                        entry_reason="phase_c43_live_limit_buy_filled",
                        extra=extra,
                    )
            if not position:
                actions.append({
                    "client_order_id": cid,
                    "ticker": ticker,
                    "action": "blocked_position_create_failed",
                    "state_write_performed": False,
                    "order_write_performed": False,
                })
                continue
            position_id = str(position.get("order_id") or position.get("position_id") or oid or cid)
            updated = store.update_order(cid, {
                "status": "filled",
                "filled_at": _now_iso(),
                "filled_size": str(filled_base),
                "filled_size_base": str(filled_base),
                "filled_quote_value": filled_quote,
                "remaining_size": "0",
                "remaining_quote": "0",
                "avg_fill_price": str(avg_price),
                "last_live_order_snapshot": live,
                "last_fills_summary": fills_summary,
                "position_created": True,
                "position_created_at": _now_iso(),
                "linked_position_id": position_id,
                "position_link_source": "fill_to_position",
                "position_created_from_fill_status": "filled" if is_final_fill else "partially_filled",
                "position_transition": position_transition,
                "d2_plan_created": False,
                "d3_preview_created": False,
                "live_exit_order_created": False,
            }, event_type="phase_c43_live_entry_order_filled_and_linked_to_position")
            actions.append({"client_order_id": cid, "ticker": ticker, "action": "filled_to_position", "order": updated, "position": position, "position_transition": position_transition})
            continue
        actions.append({"client_order_id": cid, "ticker": ticker, "action": "kept_open", "live_status": status or "unknown"})

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": C43_PHASE,
        "status": "fill_reconciliation_completed",
        "apply_local": bool(apply_local),
        "coinbase_call_attempted": coinbase_call_attempted,
        "coinbase_call_succeeded": coinbase_call_succeeded,
        "local_live_entry_orders_seen": len(local_orders),
        "actions": actions,
        "errors": errors,
        "safety_policy": {
            "does_not_submit": True,
            "does_not_create_exit_orders": True,
            "entry_fills_only": True,
            "positions_opened_only_after_fill_evidence": True,
            "preview_does_not_mutate_order_or_position_state": True,
        },
    })


def reconcile_phase_c43_fills_to_positions(
    *,
    cfg: Any,
    order_store: Optional[OrderStore] = None,
    state_store: Any = None,
    coinbase_client: Any = None,
    live_orders_snapshot: Optional[List[Dict[str, Any]]] = None,
    allow_coinbase_poll: bool = False,
    tickers: Optional[List[str]] = None,
    apply_local: bool = False,
    _apply_authority: Any = None,
) -> Dict[str, Any]:
    """Preview C.4.3 fills; only C.4.4 can authorize local apply.

    ``_apply_authority`` is an opaque process-local capability, not an ACK. It
    is intentionally only held by the C.4.4 orchestrator so application code
    cannot make this lower-level reconciler a second state-transition owner.
    """
    if apply_local and _apply_authority is not _C43_LIFECYCLE_APPLY_AUTHORITY:
        report = _reconcile_phase_c43_fills_to_positions_unlocked(
            cfg=cfg,
            order_store=order_store,
            state_store=state_store,
            coinbase_client=coinbase_client,
            live_orders_snapshot=live_orders_snapshot,
            allow_coinbase_poll=allow_coinbase_poll,
            tickers=tickers,
            apply_local=False,
        )
        report.update({
            "status": "apply_local_blocked_requires_c44_lifecycle_orchestrator",
            "apply_local": False,
            "apply_local_requested": True,
            "authority_blockers": ["c43_local_apply_owned_by_c44_lifecycle_orchestrator"],
        })
        report.setdefault("safety_policy", {})["local_apply_owned_by_c44_lifecycle_orchestrator"] = True
        return report

    if not apply_local:
        return _reconcile_phase_c43_fills_to_positions_unlocked(
            cfg=cfg,
            order_store=order_store,
            state_store=state_store,
            coinbase_client=coinbase_client,
            live_orders_snapshot=live_orders_snapshot,
            allow_coinbase_poll=allow_coinbase_poll,
            tickers=tickers,
            apply_local=False,
        )

    with process_lock(
        _lifecycle_mutation_lock_path(cfg=cfg, order_store=order_store),
        allow_reentrant=True,
    ) as lock_info:
        report = _reconcile_phase_c43_fills_to_positions_unlocked(
            cfg=cfg,
            order_store=order_store,
            state_store=state_store,
            coinbase_client=coinbase_client,
            live_orders_snapshot=live_orders_snapshot,
            allow_coinbase_poll=allow_coinbase_poll,
            tickers=tickers,
            apply_local=True,
        )
    report["mutation_lock"] = {
        "acquired": True,
        "reentrant": bool(lock_info.get("reentrant")),
    }
    return report


def build_phase_c43_status_report(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    order_store: Optional[OrderStore] = None,
    state_store: Any = None,
    live_orders_snapshot: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    store = order_store or OrderStore()
    counts = count_local_phase_c_live_entry_orders(store)
    reconcile_preview = reconcile_phase_c43_fills_to_positions(
        cfg=cfg,
        order_store=store,
        state_store=state_store,
        live_orders_snapshot=live_orders_snapshot or [],
        allow_coinbase_poll=False,
        tickers=None,
    )
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": C43_PHASE,
        "ticker": _normalize_ticker(ticker),
        "config": {
            "enable_phase_c43_autonomous_entry_submitter": bool(getattr(cfg, "enable_phase_c43_autonomous_entry_submitter", True)),
            "enable_autonomous_small_live_orderbook_mode": bool(getattr(cfg, "enable_autonomous_small_live_orderbook_mode", False)),
            "enable_phase_c_actual_coinbase_submit": bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
            "enable_live_entry_orders": bool(getattr(cfg, "enable_live_entry_orders", False)),
            "enable_live_exit_orders": bool(getattr(cfg, "enable_live_exit_orders", False)),
            "allowed_tickers": list(getattr(cfg, "allowed_tickers", []) or []),
            "phase_c_allowed_tickers": list(getattr(cfg, "phase_c_allowed_tickers", []) or []),
            "autonomous_allowed_tickers": list(getattr(cfg, "autonomous_allowed_tickers", []) or []),
            "configured_ticker_universe": configured_ticker_universe(cfg),
            "effective_phase_c_allowed_tickers": effective_phase_c_allowed_tickers(cfg),
            "phase_c_max_order_quote": str(getattr(cfg, "phase_c_max_order_quote", "0")),
            "autonomous_max_order_quote": str(getattr(cfg, "autonomous_max_order_quote", "0")),
            "autonomous_max_open_orders": int(getattr(cfg, "autonomous_max_open_orders", 0)),
        },
        "local_live_entry_order_counts": counts,
        "fill_reconciliation_preview": reconcile_preview,
        "next_step": "enable actual submit only when you accept autonomous entry live mode with max 100 USDC/order and max 4 open orders",
        "safety_policy": {
            "entry_only_first": True,
            "live_exits_forbidden": True,
            "max_quote_100_usdc": True,
            "max_open_orders_4": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "C43_PHASE",
    "build_phase_c43_deterministic_live_risk_snapshot",
    "build_phase_c43_guard_and_submit_preparation",
    "count_local_phase_c_live_entry_orders",
    "reconcile_phase_c43_fills_to_positions",
    "build_phase_c43_status_report",
]
