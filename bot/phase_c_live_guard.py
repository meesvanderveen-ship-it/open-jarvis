from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bot.amount_cap_guard import evaluate_amount_cap_guard
from bot.live_order_size_policy import (
    bounded_exploration_report,
    live_order_size_policy_report,
    validate_entry_quote_size,
    validate_exit_quote_size,
)
from bot.config import MODE_C_MARKET_ORDER_ACK_VALUE, effective_phase_c_allowed_tickers, configured_ticker_universe
from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
from bot.orderbook_entry_planner import build_resting_limit_entry_preview
from bot.product_rules import canonical_product_rules, validate_limit_buy_payload


ZERO = Decimal("0")
LIVE_ENTRY_GUARD_VERSION = "wait-preview-block-v1"
LIVE_ENTRY_REQUIRED_GATES = (
    "fresh_approve_trade",
    "buy",
    "valid_trade_plan",
    "product_rules",
    "precision_normalized",
)
BUY_PLAN_ACTIONS = {
    "buy",
    "prepare_buy",
    "place_limit_buy",
    "prepare_resting_limit_entry",
    "prepare_retest_limit_entry",
    "prepare_pullback_limit_entry",
    "prepare_reclaim_retest_limit_entry",
    "prepare_breakout_retest_limit_entry",
}
RESTING_PLAN_ACTIONS = {
    "prepare_resting_limit_entry",
    "prepare_retest_limit_entry",
    "prepare_pullback_limit_entry",
    "prepare_reclaim_retest_limit_entry",
    "prepare_breakout_retest_limit_entry",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _get_nested_dict(obj: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    current: Any = obj
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _effective_product_rules(
    explicit: Optional[Dict[str, Any]],
    analysis: Dict[str, Any],
    order_intent: Dict[str, Any],
) -> Dict[str, Any]:
    if isinstance(explicit, dict) and explicit:
        return explicit
    if isinstance(order_intent.get("product_rules"), dict) and order_intent.get("product_rules"):
        return order_intent.get("product_rules") or {}
    feature_pack = analysis.get("feature_pack") if isinstance(analysis.get("feature_pack"), dict) else {}
    decision_context = feature_pack.get("decision_context") if isinstance(feature_pack.get("decision_context"), dict) else {}
    for candidate in (
        decision_context.get("product_rules"),
        feature_pack.get("product_rules"),
        feature_pack.get("exchange_rules"),
        analysis.get("product_rules"),
        analysis.get("exchange_rules"),
    ):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _plan_action_from_inputs(
    *,
    analysis: Dict[str, Any],
    execution_plan: Dict[str, Any],
    order_intent: Dict[str, Any],
) -> str:
    trade_plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
    return _first_text(
        order_intent.get("plan_action"),
        execution_plan.get("plan_action"),
        trade_plan.get("plan_action"),
        order_intent.get("execution_action"),
        execution_plan.get("execution_action"),
    ).lower()


def _trigger_ready_from_inputs(
    *,
    analysis: Dict[str, Any],
    execution_plan: Dict[str, Any],
    order_intent: Dict[str, Any],
    pending_ctx: Dict[str, Any],
) -> bool:
    status = str(pending_ctx.get("status") or "").strip().lower()
    trade_plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
    return bool(
        _to_bool(order_intent.get("trigger_ready"))
        or _to_bool(execution_plan.get("trigger_ready"))
        or _to_bool(pending_ctx.get("trigger_ready"))
        or status in {"trigger_ready", "needs_fresh_analysis"}
        or bool(str(trade_plan.get("trigger") or "").strip())
    )


def _preview_only_from_inputs(
    *,
    analysis: Dict[str, Any],
    execution_plan: Dict[str, Any],
    order_intent: Dict[str, Any],
) -> bool:
    return any(
        _to_bool(value)
        for value in (
            analysis.get("preview_only"),
            execution_plan.get("preview_only"),
            order_intent.get("preview_only"),
            order_intent.get("paper_only"),
        )
    )


def _prepare_resting_limit_entry_from_inputs(
    *,
    execution_plan: Dict[str, Any],
    order_intent: Dict[str, Any],
    plan_action: str,
    orderbook_entry_preview: Dict[str, Any],
) -> bool:
    explicit_values = [
        order_intent.get("prepare_resting_limit_entry"),
        execution_plan.get("prepare_resting_limit_entry"),
    ]
    if any(isinstance(value, bool) and value is False for value in explicit_values):
        return False
    if any(isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off"} for value in explicit_values):
        return False
    if any(_to_bool(value) for value in explicit_values):
        return True
    if plan_action in RESTING_PLAN_ACTIONS:
        return True
    return bool(orderbook_entry_preview.get("eligible") and plan_action in BUY_PLAN_ACTIONS)


def _open_position_same_ticker(open_positions: Optional[Sequence[Dict[str, Any]]], ticker: str) -> bool:
    selected = _normalize_ticker(ticker)
    for position in open_positions or []:
        if not isinstance(position, dict):
            continue
        if _normalize_ticker(position.get("ticker") or position.get("product_id")) != selected:
            continue
        status = str(position.get("status") or "open").strip().lower()
        base = _to_decimal(
            position.get("bot_managed_base")
            or position.get("position_size_base")
            or position.get("base_size"),
            "0",
        )
        if status in {"open", "active"} and base > ZERO:
            return True
    return False


def _same_ticker_in_open_orders(open_live_entry_order_tickers: Optional[Iterable[str]], ticker: str) -> bool:
    selected = _normalize_ticker(ticker)
    return selected in {_normalize_ticker(value) for value in (open_live_entry_order_tickers or []) if _normalize_ticker(value)}


def _orderbook_is_fresh(execution_plan: Dict[str, Any]) -> Tuple[bool, str]:
    orderbook = execution_plan.get("orderbook_summary") if isinstance(execution_plan, dict) else {}
    if not isinstance(orderbook, dict):
        return False, "missing_orderbook_summary"
    if not bool(orderbook.get("snapshot_available")):
        return False, "orderbook_snapshot_missing"
    freshness = str(orderbook.get("freshness_status") or "").strip().lower()
    if freshness and freshness != "fresh":
        return False, f"orderbook_not_fresh:{freshness}"
    spread = _to_decimal(orderbook.get("spread_pct"), "0")
    if spread < ZERO:
        return False, "negative_spread_pct_invalid"
    return True, "orderbook_fresh"


def _pending_intent_context_from_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(analysis, dict):
        return {}
    direct = analysis.get("paper_pending_order_intent")
    if isinstance(direct, dict):
        return direct
    feature_pack = analysis.get("feature_pack") if isinstance(analysis.get("feature_pack"), dict) else {}
    decision_context = feature_pack.get("decision_context") if isinstance(feature_pack.get("decision_context"), dict) else {}
    ctx = decision_context.get("pending_order_intent") if isinstance(decision_context.get("pending_order_intent"), dict) else {}
    return ctx if isinstance(ctx, dict) else {}


def _paper_order_from_inputs(order_intent: Optional[Dict[str, Any]], analysis: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(order_intent, dict):
        return order_intent
    maybe = analysis.get("paper_order") if isinstance(analysis, dict) else None
    return maybe if isinstance(maybe, dict) else {}


def build_phase_c_config_snapshot(cfg: Any) -> Dict[str, Any]:
    return {
        "enable_phase_c_live_small_limit_orders": bool(getattr(cfg, "enable_phase_c_live_small_limit_orders", False)),
        "execution_mode": str(getattr(cfg, "execution_mode", "")),
        "enable_limit_order_manager": bool(getattr(cfg, "enable_limit_order_manager", False)),
        "enable_live_limit_orders": bool(getattr(cfg, "enable_live_limit_orders", False)),
        "enable_live_entry_orders": bool(getattr(cfg, "enable_live_entry_orders", False)),
        "enable_live_exit_orders": bool(getattr(cfg, "enable_live_exit_orders", False)),
        "allowed_tickers": list(getattr(cfg, "allowed_tickers", []) or []),
        "phase_c_allowed_tickers": list(getattr(cfg, "phase_c_allowed_tickers", []) or []),
        "autonomous_allowed_tickers": list(getattr(cfg, "autonomous_allowed_tickers", []) or []),
        "configured_ticker_universe": configured_ticker_universe(cfg),
        "effective_phase_c_allowed_tickers": effective_phase_c_allowed_tickers(cfg),
        "phase_c_max_order_quote": str(getattr(cfg, "phase_c_max_order_quote", "0")),
        "min_live_order_quote_usdc": str(getattr(cfg, "min_live_order_quote_usdc", "50.00")),
        "max_live_order_quote_usdc": str(getattr(cfg, "max_live_order_quote_usdc", "100.00")),
        "enable_dynamic_entry_sizing": bool(getattr(cfg, "enable_dynamic_entry_sizing", False)),
        "min_dynamic_entry_quote_usdc": str(getattr(cfg, "min_dynamic_entry_quote_usdc", "50.00")),
        "max_dynamic_entry_quote_usdc": str(getattr(cfg, "max_dynamic_entry_quote_usdc", "100.00")),
        "phase_c_max_open_entry_orders": int(getattr(cfg, "phase_c_max_open_entry_orders", 0)),
        "phase_c_max_new_orders_per_cycle": int(getattr(cfg, "phase_c_max_new_orders_per_cycle", 0)),
        "phase_c_max_cancels_per_cycle": int(getattr(cfg, "phase_c_max_cancels_per_cycle", 0)),
        "phase_c_max_replaces_per_cycle": int(getattr(cfg, "phase_c_max_replaces_per_cycle", 0)),
        "phase_c_require_pending_intent": bool(getattr(cfg, "phase_c_require_pending_intent", True)),
        "phase_c_require_promotion_ready": bool(getattr(cfg, "phase_c_require_promotion_ready", True)),
        "phase_c_require_fresh_judge": bool(getattr(cfg, "phase_c_require_fresh_judge", True)),
        "phase_c_require_risk_approval": bool(getattr(cfg, "phase_c_require_risk_approval", True)),
        "phase_c_require_orderbook_freshness": bool(getattr(cfg, "phase_c_require_orderbook_freshness", True)),
        "phase_c_entry_order_min_expiry_minutes": int(getattr(cfg, "phase_c_entry_order_min_expiry_minutes", 15)),
        "phase_c_entry_order_default_expiry_minutes": int(getattr(cfg, "phase_c_entry_order_default_expiry_minutes", 60)),
        "phase_c_entry_order_max_expiry_hours": int(getattr(cfg, "phase_c_entry_order_max_expiry_hours", 6)),
        "phase_c_disable_exit_limit_orders": bool(getattr(cfg, "phase_c_disable_exit_limit_orders", True)),
        "phase_c_paper_shadow_log": bool(getattr(cfg, "phase_c_paper_shadow_log", True)),
        "enable_phase_c_live_submit_infrastructure": bool(getattr(cfg, "enable_phase_c_live_submit_infrastructure", True)),
        "enable_phase_c_actual_coinbase_submit": bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
        "phase_c43_runtime_submit_ack_present": bool(str(getattr(cfg, "phase_c43_runtime_submit_ack", "") or "").strip()),
        "phase_c43_runtime_submit_ack_valid": (
            str(getattr(cfg, "phase_c43_runtime_submit_ack", "") or "").strip()
            == C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
        ),
        "phase_c_live_order_post_only": bool(getattr(cfg, "phase_c_live_order_post_only", True)),
        "enable_orderbook_entry_planner": bool(getattr(cfg, "enable_orderbook_entry_planner", True)),
        "enable_resting_limit_entry_preview": bool(getattr(cfg, "enable_resting_limit_entry_preview", True)),
        "enable_resting_limit_entry_live_submit": bool(getattr(cfg, "enable_resting_limit_entry_live_submit", False)),
        "enable_pending_entry_lifecycle": bool(getattr(cfg, "enable_pending_entry_lifecycle", True)),
        "orderbook_entry_max_distance_from_mid_pct": str(getattr(cfg, "orderbook_entry_max_distance_from_mid_pct", "0.0030")),
        "orderbook_entry_max_ttl_minutes": int(getattr(cfg, "orderbook_entry_max_ttl_minutes", 60)),
        "enable_bounded_exploration_mode": bool(getattr(cfg, "enable_bounded_exploration_mode", False)),
        "exploration_min_order_quote_usdc": str(getattr(cfg, "exploration_min_order_quote_usdc", "20.00")),
        "exploration_max_order_quote_usdc": str(getattr(cfg, "exploration_max_order_quote_usdc", "35.00")),
        "exploration_allowed_tickers": list(getattr(cfg, "exploration_allowed_tickers", []) or []),
        "exploration_allow_market_orders": bool(getattr(cfg, "exploration_allow_market_orders", False)),
        "exploration_require_hard_risk_green": bool(getattr(cfg, "exploration_require_hard_risk_green", True)),
        "exploration_require_fresh_trigger": bool(getattr(cfg, "exploration_require_fresh_trigger", True)),
        "exploration_require_no_chase": bool(getattr(cfg, "exploration_require_no_chase", True)),
        "exploration_max_spread_pct": str(getattr(cfg, "exploration_max_spread_pct", "0.0040")),
        "exploration_require_orderbook_snapshot": bool(getattr(cfg, "exploration_require_orderbook_snapshot", True)),
        "market_order_enabled": bool(getattr(cfg, "market_order_enabled", False)),
        "enable_market_orders": bool(getattr(cfg, "enable_market_orders", False)),
        "allow_market_orders": bool(getattr(cfg, "allow_market_orders", False)),
        "mode_c_market_order_ack_valid": str(getattr(cfg, "mode_c_market_order_ack", "") or "").strip() == MODE_C_MARKET_ORDER_ACK_VALUE,
        "replication_enabled": bool(getattr(cfg, "replication_enabled", False)),
        "replication_lifecycle_enabled": bool(getattr(cfg, "replication_lifecycle_enabled", False)),
        "replication_lifecycle_http_enabled": bool(getattr(cfg, "replication_lifecycle_http_enabled", False)),
        "max_open_positions": int(getattr(cfg, "max_open_positions", 0)),
        "autonomous_max_open_orders": int(getattr(cfg, "autonomous_max_open_orders", 0)),
        "max_new_orders_per_cycle": int(getattr(cfg, "max_new_orders_per_cycle", 0)),
    }


def mode_c_market_order_readiness(
    *,
    cfg: Any,
    open_orders_count: int = 0,
    open_positions_count: int = 0,
    new_orders_this_cycle: int = 0,
) -> Dict[str, Any]:
    cfg_snapshot = build_phase_c_config_snapshot(cfg)
    flags = {
        "MARKET_ORDER_ENABLED": cfg_snapshot["market_order_enabled"],
        "ENABLE_MARKET_ORDERS": cfg_snapshot["enable_market_orders"],
        "ALLOW_MARKET_ORDERS": cfg_snapshot["allow_market_orders"],
    }
    any_enabled = any(flags.values())
    all_enabled = all(flags.values())
    replication_enabled = any(
        bool(cfg_snapshot[name])
        for name in ("replication_enabled", "replication_lifecycle_enabled", "replication_lifecycle_http_enabled")
    )
    min_quote = _to_decimal(cfg_snapshot["min_live_order_quote_usdc"], "0")
    max_quote = _to_decimal(cfg_snapshot["max_live_order_quote_usdc"], "0")
    blockers: List[str] = []
    passed: List[str] = []
    if not any_enabled:
        passed.append("market_orders_disabled")
    elif not all_enabled:
        blockers.append("mode_c_market_order_ack_missing")
    else:
        passed.append("all_three_market_order_flags_true")
    if any_enabled and not cfg_snapshot["mode_c_market_order_ack_valid"]:
        blockers.append("market_orders_enabled_without_ack")
        if "mode_c_market_order_ack_missing" not in blockers:
            blockers.append("mode_c_market_order_ack_missing")
    elif any_enabled:
        passed.append("mode_c_market_order_ack_valid")
    if any_enabled and replication_enabled:
        blockers.append("market_orders_enabled_with_replication")
    elif any_enabled:
        passed.append("replication_disabled_for_mode_c")
    if min_quote != Decimal("50.00") or max_quote != Decimal("100.00"):
        blockers.append("market_order_quote_rails_not_50_100")
    else:
        passed.append("market_order_quote_rails_50_100")
    if int(cfg_snapshot["max_new_orders_per_cycle"]) != 1 or int(cfg_snapshot["phase_c_max_new_orders_per_cycle"]) != 1:
        blockers.append("market_order_max_new_orders_per_cycle_not_1")
    else:
        passed.append("market_order_max_new_orders_per_cycle_1")
    if int(cfg_snapshot["autonomous_max_open_orders"]) > 3 or int(cfg_snapshot["phase_c_max_open_entry_orders"]) > 3:
        blockers.append("market_order_max_open_orders_above_3")
    if open_orders_count > 3:
        blockers.append("market_order_open_orders_above_3")
    else:
        passed.append("market_order_open_orders_within_cap")
    if int(cfg_snapshot["max_open_positions"]) > 3 or open_positions_count > 3:
        blockers.append("market_order_open_positions_above_3")
    else:
        passed.append("market_order_open_positions_within_cap")
    if new_orders_this_cycle >= 1:
        blockers.append("market_order_new_order_cycle_budget_exhausted")
    else:
        passed.append("market_order_new_order_cycle_budget_available")
    return {
        "status": "disabled" if not any_enabled else ("ready" if not blockers else "blocked"),
        "ready": bool(any_enabled and not blockers),
        "enabled": bool(any_enabled),
        "all_three_flags_true": bool(all_enabled),
        "required_ack": MODE_C_MARKET_ORDER_ACK_VALUE,
        "ack_valid": bool(cfg_snapshot["mode_c_market_order_ack_valid"]),
        "replication_disabled": not replication_enabled,
        "blockers": sorted(set(blockers)),
        "passed_checks": passed,
        "config": cfg_snapshot,
    }


def evaluate_mode_c_market_order_guard(
    *,
    cfg: Any,
    ticker: str,
    side: str,
    analysis: Optional[Dict[str, Any]] = None,
    execution_plan: Optional[Dict[str, Any]] = None,
    order_intent: Optional[Dict[str, Any]] = None,
    live_risk_result: Optional[Dict[str, Any]] = None,
    existing_position: Optional[Dict[str, Any]] = None,
    open_orders_count: int = 0,
    open_positions_count: int = 0,
    new_orders_this_cycle: int = 0,
    duplicate_open_order: bool = False,
    open_d3_exit_exists: bool = False,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    side_norm = str(side or "").strip().upper()
    analysis = analysis if isinstance(analysis, dict) else {}
    execution_plan = execution_plan if isinstance(execution_plan, dict) else {}
    order = order_intent if isinstance(order_intent, dict) else {}
    judge = analysis.get("judge") if isinstance(analysis.get("judge"), dict) else {}
    trade_plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
    risk = live_risk_result if isinstance(live_risk_result, dict) else {}
    readiness = mode_c_market_order_readiness(
        cfg=cfg,
        open_orders_count=open_orders_count,
        open_positions_count=open_positions_count,
        new_orders_this_cycle=new_orders_this_cycle,
    )
    blockers: List[str] = list(readiness.get("blockers") or [])
    passed: List[str] = list(readiness.get("passed_checks") or [])
    cfg_snapshot = readiness["config"]
    allowed_tickers = {_normalize_ticker(x) for x in cfg_snapshot["effective_phase_c_allowed_tickers"]}
    if not allowed_tickers or selected_ticker not in allowed_tickers:
        blockers.append("ticker_not_in_phase_c_allowed_tickers")
    else:
        passed.append("ticker_allowed_for_mode_c")
    if side_norm not in {"BUY", "SELL"}:
        blockers.append("market_order_side_not_supported")
    if duplicate_open_order:
        blockers.append("duplicate_open_order")
    if open_orders_count >= 3:
        blockers.append("market_order_open_orders_above_3")
    if open_positions_count >= 3 and side_norm == "BUY":
        blockers.append("market_order_open_positions_above_3")
    accepted = bool(risk.get("accepted") or risk.get("approved") or risk.get("risk_approved"))
    if not accepted:
        blockers.append("deterministic_live_risk_approval_missing")
    else:
        passed.append("deterministic_live_risk_approval_present")
    action = str(execution_plan.get("execution_action") or order.get("execution_action") or "").strip().lower()
    if side_norm == "BUY":
        quote = _to_decimal(order.get("size_quote") or order.get("quote_size") or judge.get("size_quote"), "0")
        if str(judge.get("decision") or "").strip().lower() != "approve_trade":
            blockers.append("fresh_judge_buy_approval_missing")
        else:
            passed.append("fresh_judge_buy_approval_present")
        if str(judge.get("side") or order.get("side") or "").strip().upper() != "BUY":
            blockers.append("side_not_buy")
        else:
            passed.append("side_buy")
        if action not in {"place_market_buy", "market_buy"}:
            blockers.append(f"execution_action_not_market_buy:{action or 'missing'}")
        else:
            passed.append("execution_action_place_market_buy")
        if not trade_plan:
            blockers.append("concrete_trade_plan_missing")
        else:
            passed.append("concrete_trade_plan_present")
        quote_policy = validate_entry_quote_size(quote, cfg)
        for blocker in quote_policy["blockers"]:
            if blocker == "quote_size_below_min_live_order_quote":
                blockers.append("market_order_quote_below_min")
            elif blocker == "quote_size_above_max_live_order_quote":
                blockers.append("market_order_quote_above_max")
            else:
                blockers.append(blocker)
        if quote_policy["accepted"]:
            passed.append("market_buy_quote_20_100")
        base = ZERO
        estimated_quote = quote
    else:
        position = existing_position if isinstance(existing_position, dict) else {}
        position_base = _to_decimal(position.get("bot_managed_base") or position.get("position_size_base") or position.get("base_size"), "0")
        base = _to_decimal(order.get("base_size") or order.get("size_base"), "0")
        price = _to_decimal(order.get("estimated_price") or order.get("current_price") or order.get("mid_price"), "0")
        estimated_quote = base * price if base > ZERO and price > ZERO else _to_decimal(order.get("estimated_quote"), "0")
        if not position or position_base <= ZERO:
            blockers.append("market_sell_without_position")
        else:
            passed.append("market_sell_position_present")
        if base <= ZERO:
            blockers.append("market_sell_base_missing")
        elif base > position_base:
            blockers.append("market_sell_oversell")
        else:
            passed.append("market_sell_no_oversell")
        if open_d3_exit_exists:
            blockers.append("market_sell_duplicate_d3_exit")
        quote_policy = validate_exit_quote_size(estimated_quote=estimated_quote, cfg=cfg, label="MODE_C_MARKET_SELL", is_full_close=True)
        if "exit_quote_above_max_live_order_quote" in quote_policy["blockers"]:
            blockers.append("market_order_quote_above_max")
        if quote_policy["accepted"]:
            passed.append("market_sell_quote_policy_ok")
    return {
        "generated_at": _now_iso(),
        "phase": "mode_c_market_order_guard",
        "ticker": selected_ticker,
        "side": side_norm,
        "order_type": "market",
        "guard_allows_market_order": bool(readiness.get("ready") and not blockers),
        "hard_block_reasons": sorted(set(blockers)),
        "passed_checks": passed,
        "mode_c_market_order_readiness": readiness,
        "candidate_summary": {
            "execution_action": action,
            "quote_size": str(estimated_quote) if estimated_quote > ZERO else None,
            "base_size": str(base) if base > ZERO else None,
            "approval_source": "judge_approve_trade_and_deterministic_risk" if side_norm == "BUY" else "bot_managed_position_and_deterministic_risk",
        },
        "safety_policy": {
            "no_coinbase_submit_in_this_guard": True,
            "market_orders_require_mode_c_ack": True,
            "replication_must_be_disabled": True,
            "market_sell_requires_bot_managed_position": True,
            "terminal_fill_evidence_required_before_local_apply": True,
        },
    }


def _bounded_exploration_blocks(
    *,
    cfg_snapshot: Dict[str, Any],
    ticker: str,
    quote: Decimal,
    limit_price: Decimal,
    analysis: Dict[str, Any],
    execution_plan: Dict[str, Any],
    pending_ctx: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    if not cfg_snapshot["enable_bounded_exploration_mode"]:
        return [], []

    blockers: List[str] = []
    passed: List[str] = ["bounded_exploration_mode_enabled"]
    if cfg_snapshot["exploration_allow_market_orders"]:
        blockers.append("bounded_exploration_market_orders_enabled")

    min_quote = _to_decimal(cfg_snapshot["exploration_min_order_quote_usdc"], "20.00")
    max_quote = _to_decimal(cfg_snapshot["exploration_max_order_quote_usdc"], "35.00")
    if quote < min_quote:
        blockers.append("bounded_exploration_quote_below_min")
    elif quote > max_quote:
        blockers.append("bounded_exploration_quote_above_max")
    else:
        passed.append("bounded_exploration_quote_within_probe_band")

    allowed_source = cfg_snapshot["exploration_allowed_tickers"] or cfg_snapshot["effective_phase_c_allowed_tickers"]
    allowed = {_normalize_ticker(x) for x in allowed_source}
    if not allowed or ticker not in allowed:
        blockers.append("bounded_exploration_ticker_not_allowed")
    else:
        passed.append("bounded_exploration_ticker_allowed")

    orderbook = execution_plan.get("orderbook_summary") if isinstance(execution_plan.get("orderbook_summary"), dict) else {}
    if cfg_snapshot["exploration_require_orderbook_snapshot"] and not bool(orderbook.get("snapshot_available")):
        blockers.append("bounded_exploration_orderbook_snapshot_missing")
    spread = _to_decimal(orderbook.get("spread_pct"), "0")
    max_spread = _to_decimal(cfg_snapshot["exploration_max_spread_pct"], "0.0040")
    if spread > max_spread:
        blockers.append("bounded_exploration_spread_above_cap")
    else:
        passed.append("bounded_exploration_spread_within_cap")

    trigger_ready = _to_bool(pending_ctx.get("trigger_ready")) or str(pending_ctx.get("status") or "").lower() in {"trigger_ready", "needs_fresh_analysis"}
    trade_plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
    if not trigger_ready and str(trade_plan.get("trigger") or "").strip():
        trigger_ready = True
    if cfg_snapshot["exploration_require_fresh_trigger"] and not trigger_ready:
        blockers.append("bounded_exploration_fresh_trigger_missing")
    elif trigger_ready:
        passed.append("bounded_exploration_fresh_trigger_present")

    do_not_chase_above = _to_decimal(trade_plan.get("do_not_chase_above") or orderbook.get("do_not_chase_above"), "0")
    if cfg_snapshot["exploration_require_no_chase"] and do_not_chase_above > ZERO and limit_price > do_not_chase_above:
        blockers.append("bounded_exploration_do_not_chase_above_breached")
    elif cfg_snapshot["exploration_require_no_chase"]:
        passed.append("bounded_exploration_no_chase_ok")

    stop_loss = _to_decimal(trade_plan.get("stop_loss") or trade_plan.get("invalidation"), "0")
    trigger = str(trade_plan.get("trigger") or "").strip()
    if not trigger or stop_loss <= ZERO:
        blockers.append("bounded_exploration_defined_risk_missing")
    else:
        passed.append("bounded_exploration_defined_risk_present")
    return blockers, passed


def evaluate_phase_c_live_entry_readiness(
    *,
    cfg: Any,
    ticker: str,
    analysis: Optional[Dict[str, Any]] = None,
    execution_plan: Optional[Dict[str, Any]] = None,
    order_intent: Optional[Dict[str, Any]] = None,
    live_risk_result: Optional[Dict[str, Any]] = None,
    open_live_entry_orders_count: int = 0,
    open_live_entry_order_tickers: Optional[Iterable[str]] = None,
    open_positions: Optional[Sequence[Dict[str, Any]]] = None,
    new_live_orders_this_cycle: int = 0,
    product_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate whether a candidate could pass a future Phase-C live-entry guard.

    This function is intentionally side-effect-free: it does not call Coinbase,
    does not reserve balance, does not create an order, and does not mutate bot
    state. It is a deterministic checklist used before any later live submit
    function is introduced.
    """
    ticker = _normalize_ticker(ticker)
    analysis = analysis if isinstance(analysis, dict) else {}
    execution_plan = execution_plan if isinstance(execution_plan, dict) else {}
    order = _paper_order_from_inputs(order_intent, analysis)
    judge = analysis.get("judge") if isinstance(analysis.get("judge"), dict) else {}
    trade_plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
    pending_ctx = _pending_intent_context_from_analysis(analysis)
    risk = live_risk_result if isinstance(live_risk_result, dict) else {}
    effective_rules = _effective_product_rules(product_rules, analysis, order)
    cfg_snapshot = build_phase_c_config_snapshot(cfg)
    orderbook_entry_preview = build_resting_limit_entry_preview(
        ticker=ticker,
        analysis=analysis,
        open_positions=open_positions,
        product_rules=effective_rules,
        open_orders_count=open_live_entry_orders_count,
        new_orders_this_cycle=new_live_orders_this_cycle,
        max_quote=cfg_snapshot["phase_c_max_order_quote"],
        max_open_orders=cfg_snapshot["phase_c_max_open_entry_orders"],
        max_new_orders_per_cycle=cfg_snapshot["phase_c_max_new_orders_per_cycle"],
        max_distance_from_mid_pct=cfg_snapshot["orderbook_entry_max_distance_from_mid_pct"],
    )
    resting_entry_eligible = bool(orderbook_entry_preview.get("eligible"))

    hard_blocks: List[str] = []
    review_reasons: List[str] = []
    passed_checks: List[str] = []

    decision = str(judge.get("decision") or "").strip().lower()
    judge_side = str(judge.get("side") or "").strip().upper()
    valid_trade_plan = any(
        _to_bool(value)
        for value in (
            judge.get("valid_trade_plan"),
            judge.get("judge_response_valid_trade_plan"),
            trade_plan.get("valid_trade_plan"),
        )
    )
    plan_action = _plan_action_from_inputs(
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
    )
    trigger_ready = _trigger_ready_from_inputs(
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        pending_ctx=pending_ctx,
    )
    preview_only = _preview_only_from_inputs(
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
    )
    prepare_resting_limit_entry = _prepare_resting_limit_entry_from_inputs(
        execution_plan=execution_plan,
        order_intent=order,
        plan_action=plan_action,
        orderbook_entry_preview=orderbook_entry_preview,
    )

    if not cfg_snapshot["enable_phase_c_live_small_limit_orders"]:
        hard_blocks.append("phase_c_live_small_limit_orders_disabled")
    else:
        passed_checks.append("phase_c_master_switch_enabled")

    if cfg_snapshot["execution_mode"] != "live":
        hard_blocks.append("execution_mode_not_live")
    else:
        passed_checks.append("execution_mode_live")

    if not cfg_snapshot["enable_limit_order_manager"]:
        hard_blocks.append("limit_order_manager_disabled")
    else:
        passed_checks.append("limit_order_manager_enabled")

    if not cfg_snapshot["enable_live_limit_orders"]:
        hard_blocks.append("live_limit_orders_disabled")
    else:
        passed_checks.append("live_limit_orders_enabled")

    if not cfg_snapshot["enable_live_entry_orders"]:
        hard_blocks.append("live_entry_orders_disabled")
    else:
        passed_checks.append("live_entry_orders_enabled")

    if cfg_snapshot["enable_live_exit_orders"] and cfg_snapshot["phase_c_disable_exit_limit_orders"]:
        hard_blocks.append("live_exit_orders_enabled_but_phase_c_is_entry_only")

    allowed_tickers = {_normalize_ticker(x) for x in cfg_snapshot["effective_phase_c_allowed_tickers"]}
    if not allowed_tickers:
        hard_blocks.append("phase_c_allowed_tickers_empty")
    elif ticker not in allowed_tickers:
        hard_blocks.append("ticker_not_in_configured_ticker_universe")
    else:
        passed_checks.append("ticker_allowed_for_phase_c")

    action = str(execution_plan.get("execution_action") or order.get("execution_action") or "").strip().lower()
    requested_order_type = str(order.get("order_type") or execution_plan.get("order_type") or "").strip().lower()
    order_configuration = order.get("order_configuration") if isinstance(order.get("order_configuration"), dict) else {}
    if requested_order_type == "market" or "market_market_ioc" in order_configuration or "market" in action:
        hard_blocks.append("phase_c_market_order_entry_blocked")
    if action != "place_limit_buy":
        hard_blocks.append(f"execution_action_not_phase_c_live_entry:{action or 'missing'}")
    else:
        passed_checks.append("execution_action_place_limit_buy")

    side = str(order.get("side") or judge.get("side") or "").strip().upper()
    if side and side != "BUY":
        hard_blocks.append(f"side_not_buy:{side}")
    elif side == "BUY":
        passed_checks.append("side_buy")

    quote = _to_decimal(order.get("size_quote") or judge.get("size_quote") or judge.get("quote_size"), "0")
    max_quote = _to_decimal(cfg_snapshot["phase_c_max_order_quote"], "0")
    if quote <= ZERO:
        hard_blocks.append("missing_or_zero_quote_size")
    elif max_quote <= ZERO:
        hard_blocks.append("phase_c_max_order_quote_not_positive")
    elif not validate_entry_quote_size(quote, cfg)["accepted"]:
        hard_blocks.extend(validate_entry_quote_size(quote, cfg)["blockers"])
    elif quote > max_quote:
        hard_blocks.append("quote_size_above_phase_c_max_order_quote")
    else:
        passed_checks.append("quote_size_within_phase_c_cap")

    limit_price = _to_decimal(order.get("limit_price"), "0")
    if limit_price <= ZERO:
        hard_blocks.append("missing_or_zero_limit_price")
    else:
        passed_checks.append("limit_price_present")

    if int(cfg_snapshot["phase_c_max_open_entry_orders"]) >= 0 and open_live_entry_orders_count >= int(cfg_snapshot["phase_c_max_open_entry_orders"]):
        hard_blocks.append("phase_c_max_open_entry_orders_reached")
    else:
        passed_checks.append("open_live_entry_order_budget_available")

    same_ticker_open_order = _same_ticker_in_open_orders(open_live_entry_order_tickers, ticker)
    if same_ticker_open_order:
        hard_blocks.append("blocked_open_order_same_ticker")
    else:
        passed_checks.append("no_open_order_same_ticker")

    same_ticker_open_position = _open_position_same_ticker(open_positions, ticker)
    if same_ticker_open_position:
        hard_blocks.append("blocked_open_position_same_ticker")
    else:
        passed_checks.append("no_open_position_same_ticker")

    if int(cfg_snapshot["phase_c_max_new_orders_per_cycle"]) >= 0 and new_live_orders_this_cycle >= int(cfg_snapshot["phase_c_max_new_orders_per_cycle"]):
        hard_blocks.append("phase_c_new_order_cycle_budget_exhausted")
    else:
        passed_checks.append("new_order_cycle_budget_available")

    if cfg_snapshot["phase_c_require_orderbook_freshness"]:
        fresh, reason = _orderbook_is_fresh(execution_plan)
        if not fresh:
            hard_blocks.append(reason)
            hard_blocks.append("blocked_stale_opportunity")
        else:
            passed_checks.append("orderbook_freshness_ok")

    if cfg_snapshot["phase_c_require_pending_intent"]:
        if resting_entry_eligible:
            passed_checks.append("resting_entry_preview_replaces_pending_intent_for_prepared_entry")
        elif not pending_ctx:
            hard_blocks.append("missing_pending_order_intent_context")
        else:
            passed_checks.append("pending_order_intent_context_present")

    if cfg_snapshot["phase_c_require_promotion_ready"] and not resting_entry_eligible:
        status = str(pending_ctx.get("status") or "").strip().lower()
        requires_fresh = _to_bool(pending_ctx.get("requires_fresh_judge_and_risk"))
        trigger_ready = _to_bool(pending_ctx.get("trigger_ready")) or status in {"needs_fresh_analysis", "trigger_ready"}
        if not trigger_ready:
            hard_blocks.append("pending_intent_not_promotion_ready")
        elif not requires_fresh:
            hard_blocks.append("pending_intent_missing_requires_fresh_judge_and_risk")
        else:
            passed_checks.append("pending_intent_promotion_ready")

    if cfg_snapshot["phase_c_require_fresh_judge"]:
        if decision == "approve_trade" and judge_side == "BUY" and valid_trade_plan:
            passed_checks.append("fresh_judge_buy_approval_valid_plan_present")
        elif resting_entry_eligible:
            passed_checks.append("resting_entry_preview_available_preview_only")
            hard_blocks.append("fresh_judge_buy_approval_valid_plan_required_for_live_entry")
        else:
            hard_blocks.append("fresh_judge_buy_approval_or_valid_trade_plan_missing")
        if decision == "wait":
            hard_blocks.append("blocked_wait_decision_cannot_live_submit")
        elif decision != "approve_trade":
            hard_blocks.append("blocked_missing_fresh_approve_trade")
        if decision == "reject":
            hard_blocks.append("blocked_missing_fresh_approve_trade")
        if judge_side != "BUY":
            hard_blocks.append("blocked_missing_fresh_approve_trade")
        if not valid_trade_plan:
            hard_blocks.append("blocked_valid_trade_plan_false")

    if preview_only:
        hard_blocks.append("blocked_preview_only_cannot_live_submit")
    else:
        passed_checks.append("not_preview_only")

    if not plan_action or plan_action not in BUY_PLAN_ACTIONS:
        hard_blocks.append("blocked_plan_action_not_buy")
    else:
        passed_checks.append("plan_action_buy")

    if not trigger_ready:
        hard_blocks.append("blocked_trigger_ready_false")
    else:
        passed_checks.append("trigger_ready")

    if not prepare_resting_limit_entry:
        hard_blocks.append("blocked_prepare_resting_limit_entry_false")
    else:
        passed_checks.append("prepare_resting_limit_entry")

    if prepare_resting_limit_entry and not resting_entry_eligible:
        hard_blocks.append("blocked_orderbook_entry_candidate_false")
    elif prepare_resting_limit_entry:
        passed_checks.append("orderbook_entry_candidate_true")

    if (
        "do_not_chase_above_breached" in orderbook_entry_preview.get("blockers", [])
        or "entry_level_above_do_not_chase" in orderbook_entry_preview.get("blockers", [])
    ):
        hard_blocks.append("blocked_do_not_chase")

    product_rule_context = canonical_product_rules(ticker, effective_rules)
    if not product_rule_context.get("raw_rules_present"):
        hard_blocks.append("blocked_missing_product_rules")
    elif product_rule_context.get("precision_context_available"):
        passed_checks.append("product_rules_available")
    else:
        hard_blocks.append("blocked_precision_invalid")

    precision_report = validate_limit_buy_payload(
        ticker,
        quote,
        limit_price,
        effective_rules,
        max_quote_size=cfg_snapshot["phase_c_max_order_quote"],
    )
    if not bool(precision_report.get("valid")):
        hard_blocks.append("blocked_precision_invalid")
    else:
        passed_checks.append("precision_normalized")

    amount_cap_guard = evaluate_amount_cap_guard(
        cfg=cfg,
        ticker=ticker,
        requested_quote=quote,
        limit_price=limit_price,
        product_rules=effective_rules,
    )
    if not amount_cap_guard.get("accepted"):
        hard_blocks.extend([f"amount_cap:{reason}" for reason in amount_cap_guard.get("blockers") or []])
    else:
        passed_checks.append("quote_within_caps")

    if _to_bool(execution_plan.get("stale_opportunity")) or _to_bool(order.get("stale_opportunity")) or _to_bool(analysis.get("stale_opportunity")):
        hard_blocks.append("blocked_stale_opportunity")

    if cfg_snapshot["phase_c_require_risk_approval"]:
        accepted = bool(risk.get("accepted") or risk.get("approved") or risk.get("risk_approved"))
        mode = str(risk.get("mode") or "").strip().lower()
        if not accepted:
            hard_blocks.append("deterministic_live_risk_approval_missing")
        elif mode and "paper" in mode:
            hard_blocks.append("risk_result_is_paper_not_live")
        else:
            passed_checks.append("deterministic_live_risk_approval_present")

    exploration_blocks, exploration_passed = _bounded_exploration_blocks(
        cfg_snapshot=cfg_snapshot,
        ticker=ticker,
        quote=quote,
        limit_price=limit_price,
        analysis=analysis,
        execution_plan=execution_plan,
        pending_ctx=pending_ctx,
    )
    hard_blocks.extend(exploration_blocks)
    passed_checks.extend(exploration_passed)

    if not bool(execution_plan.get("read_only", False)):
        review_reasons.append("execution_plan_not_marked_read_only_or_missing")
    else:
        passed_checks.append("execution_plan_read_only_context_confirmed")

    hard_blocks = list(dict.fromkeys(hard_blocks))
    passed_checks = list(dict.fromkeys(passed_checks))
    guard_allows_live_submit = len(hard_blocks) == 0
    return {
        "generated_at": _now_iso(),
        "phase": "C0_live_entry_preflight_guard",
        "live_entry_guard_version": LIVE_ENTRY_GUARD_VERSION,
        "ticker": ticker,
        "guard_allows_live_submit": guard_allows_live_submit,
        "live_submission_attempted": False,
        "hard_block_reasons": hard_blocks,
        "review_reasons": review_reasons,
        "passed_checks": passed_checks,
        "config": cfg_snapshot,
        "live_order_size_policy": live_order_size_policy_report(cfg),
        "bounded_exploration": bounded_exploration_report(cfg),
        "amount_cap_guard": amount_cap_guard,
        "product_rules": product_rule_context,
        "precision_normalization": precision_report,
        "candidate_summary": {
            "execution_action": action,
            "side": side or None,
            "quote_size": str(quote) if quote > ZERO else None,
            "limit_price": str(limit_price) if limit_price > ZERO else None,
            "judge_decision": str(judge.get("decision") or ""),
            "judge_side": str(judge.get("side") or ""),
            "valid_trade_plan": valid_trade_plan,
            "plan_action": plan_action or "n/a",
            "trigger_ready": trigger_ready,
            "prepare_resting_limit_entry": prepare_resting_limit_entry,
            "preview_only": preview_only,
            "pending_intent_status": pending_ctx.get("status"),
            "pending_intent_trigger_ready": pending_ctx.get("trigger_ready"),
            "orderbook_freshness_status": _get_nested_dict(execution_plan, "orderbook_summary").get("freshness_status"),
            "product_rules_available": bool(product_rule_context.get("raw_rules_present")),
            "precision_normalized": bool(precision_report.get("valid")),
            "quote_within_caps": bool(amount_cap_guard.get("accepted")),
            "no_open_order_same_ticker": not same_ticker_open_order,
            "no_open_position_same_ticker": not same_ticker_open_position,
            "not_preview_only": not preview_only,
            "not_wait": decision != "wait",
            "not_stale_opportunity": "blocked_stale_opportunity" not in hard_blocks,
            "orderbook_entry_candidate": bool(resting_entry_eligible),
            "resting_entry_eligible": bool(resting_entry_eligible),
            "resting_entry_reason": orderbook_entry_preview.get("reason"),
            "preferred_limit_price": orderbook_entry_preview.get("entry_level"),
            "entry_route_type": orderbook_entry_preview.get("entry_route_type"),
            "pending_entry_preview_created": bool(resting_entry_eligible),
            "live_resting_entry_submit_enabled": bool(getattr(cfg, "enable_resting_limit_entry_live_submit", False)),
            "live_resting_entry_submit_attempted": False,
        },
        "safety_policy": {
            "no_coinbase_submit_in_this_guard": True,
            "pending_intent_is_not_execution_permission": True,
            "fresh_judge_and_deterministic_risk_required": True,
            "phase_c_is_master_only_entry_limit_orders": True,
            "exit_limit_orders_remain_disabled_for_phase_c": bool(getattr(cfg, "phase_c_disable_exit_limit_orders", True)),
            "required_gates": list(LIVE_ENTRY_REQUIRED_GATES),
            "wait_preview_valid_plan_false_never_arms_live_submit": True,
        },
    }


def summarize_phase_c_readiness(
    *,
    cfg: Any,
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pending_summary = pending_summary if isinstance(pending_summary, dict) else {}
    order_summary = order_summary if isinstance(order_summary, dict) else {}
    cfg_snapshot = build_phase_c_config_snapshot(cfg)

    blockers: List[str] = []
    if not cfg_snapshot["enable_phase_c_live_small_limit_orders"]:
        blockers.append("phase_c_master_switch_disabled")
    if cfg_snapshot["enable_live_exit_orders"] and cfg_snapshot["phase_c_disable_exit_limit_orders"]:
        blockers.append("live_exit_orders_must_remain_disabled_for_phase_c")
    if not cfg_snapshot["effective_phase_c_allowed_tickers"]:
        blockers.append("configured_ticker_universe_empty")
    if _to_decimal(cfg_snapshot["phase_c_max_order_quote"], "0") <= ZERO:
        blockers.append("phase_c_max_order_quote_not_positive")

    return {
        "generated_at": _now_iso(),
        "phase": "C0_live_entry_preflight_summary",
        "config": cfg_snapshot,
        "blockers": blockers,
        "orders": {
            "total": order_summary.get("total_orders", order_summary.get("total", 0)),
            "open": order_summary.get("open_orders", order_summary.get("open", 0)),
            "diagnostics": order_summary.get("diagnostic_order_count", order_summary.get("diagnostics", 0)),
        },
        "pending_order_intents": {
            "total": pending_summary.get("total_intents", 0),
            "open_intents": pending_summary.get("open_intents", pending_summary.get("active_intents", 0)),
            "trigger_ready_current": _as_list(pending_summary.get("trigger_ready")),
            "needs_fresh_analysis_current": _as_list(pending_summary.get("needs_fresh_analysis")),
            "promotion_ready_current": _as_list(pending_summary.get("promotion_ready")),
        },
        "safety_policy": {
            "summary_is_read_only": True,
            "no_coinbase_submit": True,
            "phase_c_requires_extra_master_switch": True,
        },
    }


__all__ = [
    "LIVE_ENTRY_GUARD_VERSION",
    "LIVE_ENTRY_REQUIRED_GATES",
    "build_phase_c_config_snapshot",
    "evaluate_phase_c_live_entry_readiness",
    "evaluate_mode_c_market_order_guard",
    "mode_c_market_order_readiness",
    "summarize_phase_c_readiness",
]
