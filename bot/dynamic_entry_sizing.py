"""Deterministic 10--20%-of-portfolio sizing for live BUY entries.

The final judge may describe a setup and its confidence, but it never chooses
the submitted notional.  This module turns the already-available analysis and
execution context into a bounded quote amount.  It is deliberately pure so the
same input produces the same sizing report in previews, guards and submits.

The bounds are a percentage of total account equity (portfolio_value_usdc:
free USDC cash plus the market value of every held asset, priced fresh once
per cycle by strategy_engine.py), not a fixed USDC range -- a bigger account
sizes bigger trades automatically, a smaller one sizes smaller. Everything
between the bounds is still the same deterministic quality score this module
always computed (confidence/edge/orderbook/spread/setup/trend/learning
signals); that score used to be added as small USDC deltas onto a fixed
50 USDC floor, calibrated against a fixed 50 USDC span (50 to 100). It's now
expressed as a 0..1 fraction of that same calibration span and applied to
today's actual span (max_quote - min_quote in USDC) so the scoring logic
itself didn't need to be re-tuned for the new range.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Iterable, Optional


ZERO = Decimal("0")
# Legacy fixed-USDC fallback, used only before the first successful
# per-cycle portfolio pricing (e.g. at startup, or if a Coinbase balance
# fetch fails) -- see calculate_dynamic_entry_quote's portfolio_value_usdc
# handling below for the actual live policy.
ENTRY_MIN_QUOTE = Decimal("50.00")
ENTRY_MAX_QUOTE = Decimal("100.00")
DEFAULT_MIN_POSITION_PCT_OF_PORTFOLIO = Decimal("0.10")
DEFAULT_MAX_POSITION_PCT_OF_PORTFOLIO = Decimal("0.20")
# The quality-score components below were tuned against the historical fixed
# 50-USDC span (100 - 50). Kept as the calibration denominator so the same
# tuned weights translate into a 0..1 fraction of *today's* span, whatever
# that span is now in percentage-of-portfolio terms.
_QUALITY_SCORE_CALIBRATION_SPAN = Decimal("50")


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        text = str(value).strip()
        if not text:
            return Decimal(default)
        value = Decimal(text)
        if value.is_nan() or value.is_infinite():
            return Decimal(default)
        return value
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _first(mapping: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _score(value: Any, default: Decimal = ZERO) -> Decimal:
    score = _decimal(value, str(default))
    if ZERO <= score <= Decimal("1"):
        score *= Decimal("100")
    return max(ZERO, min(Decimal("100"), score))


def _ratio_component(value: Any, *, low: str, high: str, weight: str) -> Decimal:
    ratio = _decimal(value, "0")
    lower = Decimal(low)
    upper = Decimal(high)
    maximum = Decimal(weight)
    if ratio <= lower:
        return ZERO
    if ratio >= upper:
        return maximum
    return ((ratio - lower) / (upper - lower)) * maximum


def _nested(mapping: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return _dict(current)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _context_adjustment(summary: Dict[str, Any]) -> Decimal:
    """Return a small bounded adjustment from an existing learning summary."""
    explicit = _decimal(
        _first(summary, "sizing_adjustment_usdc", "quote_adjustment_usdc", "adjustment_usdc"),
        "0",
    )
    if explicit:
        return max(Decimal("-5"), min(Decimal("5"), explicit))

    win_rate = _decimal(_first(summary, "win_rate", "recent_win_rate"), "-1")
    if win_rate > ONE:
        win_rate /= Decimal("100")
    if win_rate >= Decimal("0.60"):
        return Decimal("2")
    if ZERO <= win_rate <= Decimal("0.40"):
        return Decimal("-3")
    outcome = _decimal(_first(summary, "recent_net_pnl", "net_pnl", "recent_outcome_score"), "0")
    if outcome > ZERO:
        return Decimal("1")
    if outcome < ZERO:
        return Decimal("-1")
    return ZERO


ONE = Decimal("1")


def calculate_dynamic_entry_quote(
    *,
    cfg: Any = None,
    analysis: Optional[Dict[str, Any]] = None,
    execution_plan: Optional[Dict[str, Any]] = None,
    product_rules: Optional[Dict[str, Any]] = None,
    confidence: Any = None,
    expected_edge_score: Any = None,
    objective_score: Any = None,
    reward_to_fee: Any = None,
    reward_to_risk: Any = None,
    spread_pct: Any = None,
    slippage_pct: Any = None,
    orderbook_freshness: Any = None,
    orderbook_depth: Any = None,
    orderbook_imbalance: Any = None,
    setup_type: Any = None,
    trend_alignment: Any = None,
    market_regime: Any = None,
    available_quote_balance: Any = None,
    portfolio_value_usdc: Any = None,
    min_pct: Any = None,
    max_pct: Any = None,
    min_quote: Any = None,
    max_quote: Any = None,
    product_min_quote: Any = None,
) -> Dict[str, Any]:
    """Calculate one deterministic live-entry quote inside the configured rails.

    Missing optional context contributes zero; it cannot manufacture a positive
    signal.  Missing/insufficient balance and a product minimum above the BUY
    cap block the entry instead of silently shrinking it below the portfolio
    minimum.

    min_quote/max_quote, when explicitly passed, force fixed USDC rails
    (bypassing the portfolio-percentage calculation entirely) -- kept for
    callers/tests that want to pin exact dollar bounds. The live callers
    (phase_c43_autonomous_entry_live.py, order_plan.py) never pass them, so
    normal operation always sizes off portfolio_value_usdc.
    """
    analysis = _dict(analysis)
    execution_plan = _dict(execution_plan)
    feature_pack = _dict(analysis.get("feature_pack"))
    decision_context = _dict(feature_pack.get("decision_context"))
    judge = _dict(analysis.get("judge"))
    trade_plan = _dict(analysis.get("trade_plan"))
    orderbook = _dict(execution_plan.get("orderbook_summary"))
    if not orderbook:
        orderbook = _dict(feature_pack.get("orderbook_context")) or _dict(feature_pack.get("orderbook_summary"))
    rules = _dict(product_rules) or _dict(decision_context.get("product_rules")) or _dict(feature_pack.get("product_rules"))

    explicit_dollar_rails = min_quote is not None or max_quote is not None
    portfolio_value = _decimal(
        portfolio_value_usdc if portfolio_value_usdc is not None else _nested(feature_pack, "risk_context").get("portfolio_value_usdc"),
        "-1",
    )
    min_pct_value = _decimal(
        min_pct if min_pct is not None else getattr(cfg, "min_position_pct_of_portfolio", DEFAULT_MIN_POSITION_PCT_OF_PORTFOLIO),
        str(DEFAULT_MIN_POSITION_PCT_OF_PORTFOLIO),
    )
    max_pct_value = _decimal(
        max_pct if max_pct is not None else getattr(cfg, "max_position_pct_of_portfolio", DEFAULT_MAX_POSITION_PCT_OF_PORTFOLIO),
        str(DEFAULT_MAX_POSITION_PCT_OF_PORTFOLIO),
    )

    portfolio_priced = not explicit_dollar_rails and portfolio_value >= ZERO
    if portfolio_priced:
        minimum = portfolio_value * min_pct_value
        maximum = portfolio_value * max_pct_value
    else:
        # No live portfolio pricing available this call (explicit dollar
        # rails requested, or portfolio pricing hasn't succeeded yet this
        # cycle/at startup) -- fall back to the configured USDC rails rather
        # than sizing off an unknown/zero portfolio value.
        minimum = _decimal(
            min_quote if min_quote is not None else getattr(cfg, "min_dynamic_entry_quote_usdc", getattr(cfg, "min_live_order_quote_usdc", ENTRY_MIN_QUOTE)),
            str(ENTRY_MIN_QUOTE),
        )
        maximum = _decimal(
            max_quote if max_quote is not None else getattr(cfg, "max_dynamic_entry_quote_usdc", getattr(cfg, "max_live_order_quote_usdc", ENTRY_MAX_QUOTE)),
            str(ENTRY_MAX_QUOTE),
        )
    product_min = _decimal(
        product_min_quote if product_min_quote is not None else _first(rules, "quote_min_size", "quote_min", "min_market_funds"),
        "0",
    )
    effective_minimum = max(minimum, product_min)

    confidence_value = _score(confidence if confidence is not None else judge.get("confidence"))
    edge_value = _score(expected_edge_score if expected_edge_score is not None else judge.get("expected_edge_score"))
    objective_value = _score(objective_score if objective_score is not None else judge.get("objective_score"))

    preview = _dict(analysis.get("orderbook_entry_preview"))
    reward_fee_value = _decimal(
        reward_to_fee if reward_to_fee is not None else _first(preview, "expected_reward_to_fee"),
        "0",
    )
    reward_risk_value = _decimal(
        reward_to_risk if reward_to_risk is not None else _first(preview, "expected_reward_to_risk"),
        "0",
    )
    if reward_fee_value <= ZERO:
        reward_fee_value = _decimal(_first(trade_plan, "reward_to_fee", "expected_reward_to_fee"), "0")
    if reward_risk_value <= ZERO:
        reward_risk_value = _decimal(_first(trade_plan, "reward_to_risk", "expected_reward_to_risk"), "0")

    # A merely admissible confidence does not spend above the 50-USDC base.
    # Quality has to clear the normal judge threshold before it increases size.
    confidence_component = max(ZERO, (confidence_value - Decimal("60")) / Decimal("40")) * Decimal("14")
    edge_component = (
        max(ZERO, (edge_value - Decimal("50")) / Decimal("50")) * Decimal("7")
        + max(ZERO, (objective_value - Decimal("50")) / Decimal("50")) * Decimal("7")
    )
    reward_to_fee_component = _ratio_component(reward_fee_value, low="1", high="5", weight="6")
    reward_to_risk_component = _ratio_component(reward_risk_value, low="1", high="3", weight="6")

    freshness = str(orderbook_freshness if orderbook_freshness is not None else _first(orderbook, "freshness_status", "freshness") or "").strip().lower()
    depth = _decimal(orderbook_depth if orderbook_depth is not None else _first(orderbook, "depth_score", "depth_usd", "total_depth_usd", "bid_depth_usd"), "0")
    imbalance = _decimal(orderbook_imbalance if orderbook_imbalance is not None else _first(orderbook, "imbalance", "orderbook_imbalance", "bid_ask_imbalance"), "0")
    if imbalance > ONE:
        imbalance = imbalance / Decimal("100")
    imbalance = max(Decimal("-1"), min(ONE, imbalance))
    orderbook_component = ZERO
    if freshness in {"fresh", "current", "ok"}:
        orderbook_component += Decimal("3")
    elif freshness and freshness not in {"unknown", "unspecified"}:
        orderbook_component -= Decimal("4")
    if depth >= Decimal("75"):
        orderbook_component += Decimal("3")
    elif depth > ZERO:
        orderbook_component += Decimal("1")
    if imbalance > ZERO:
        orderbook_component += min(Decimal("3"), imbalance * Decimal("3"))
    elif imbalance < ZERO:
        orderbook_component += max(Decimal("-3"), imbalance * Decimal("3"))

    spread = _decimal(spread_pct if spread_pct is not None else _first(orderbook, "spread_pct", "bid_ask_spread_pct"), "0")
    slippage = _decimal(slippage_pct if slippage_pct is not None else _first(orderbook, "slippage_pct", "estimated_slippage_pct"), "0")
    if slippage <= ZERO:
        slippage = _decimal(getattr(cfg, "phase_d2_estimated_spread_slippage_pct", "0"), "0")
    spread_penalty = ZERO if spread <= Decimal("0.001") else (Decimal("-2") if spread <= Decimal("0.003") else (Decimal("-6") if spread <= Decimal("0.006") else Decimal("-10")))
    slippage_penalty = ZERO if slippage <= Decimal("0.001") else (Decimal("-2") if slippage <= Decimal("0.003") else (Decimal("-5") if slippage <= Decimal("0.006") else Decimal("-8")))

    setup = str(setup_type if setup_type is not None else _first(judge, "setup_type") or _first(trade_plan, "setup_type") or "").lower()
    setup_component = Decimal("4") if any(token in setup for token in ("trend_continuation", "reclaim", "breakout_retest")) else (Decimal("2") if any(token in setup for token in ("mean_reversion", "pullback", "retest")) else ZERO)
    trend = _dict(analysis.get("trend"))
    trend_text = str(trend_alignment if trend_alignment is not None else _first(trend, "higher_timeframe_alignment", "trend_alignment", "trend_direction") or "").lower()
    trend_component = Decimal("4") if any(token in trend_text for token in ("bull", "up", "aligned", "long")) else (Decimal("-4") if any(token in trend_text for token in ("bear", "down", "against", "short")) else ZERO)

    entry = _decimal(_first(trade_plan, "preferred_limit_price", "entry_price", "trigger_price", "entry_zone_high"), "0")
    support = _decimal(_first(trade_plan, "support_price", "entry_zone_low", "invalidation_price", "stop_loss_price"), "0")
    resistance = _decimal(_first(trade_plan, "resistance_price", "take_profit_1", "target_price"), "0")
    support_resistance_component = ZERO
    if entry > ZERO and support > ZERO and support < entry:
        risk_distance = (entry - support) / entry
        support_resistance_component += Decimal("2") if risk_distance <= Decimal("0.03") else Decimal("-2")
    if entry > ZERO and resistance > entry:
        reward_distance = (resistance - entry) / entry
        support_resistance_component += Decimal("2") if reward_distance >= Decimal("0.015") else Decimal("-2")

    regime = _dict(analysis.get("regime"))
    regime_text = str(market_regime if market_regime is not None else _first(regime, "market_regime", "regime", "trend_regime") or "").lower()
    regime_penalty = Decimal("-3") if any(token in regime_text for token in ("high_vol", "risk_off", "chaotic", "bear")) else (Decimal("2") if any(token in regime_text for token in ("bull", "trend", "stable")) else ZERO)

    external = _nested(decision_context, "external_context")
    market_intelligence = _dict(external.get("market_intelligence"))
    market_summary = _dict(market_intelligence.get("summary"))
    market_adjustment = min(Decimal("2"), Decimal(len(_list(market_summary.get("positive_context")))))
    market_adjustment -= min(Decimal("3"), Decimal(len(_list(market_summary.get("risk_warnings")))))

    reflection = _dict(analysis.get("recent_reflections"))
    outcomes = _dict(analysis.get("decision_outcomes"))
    adaptive = _dict(decision_context.get("adaptive_context")) or _dict(decision_context.get("autonomous_parameter_governor"))
    neural = _dict(decision_context.get("neural_shadow_policy"))
    reflection_adjustment = _context_adjustment(reflection)
    outcomes_adjustment = _context_adjustment(outcomes)
    adaptive_adjustment = _context_adjustment(adaptive)
    neural_text = " ".join(str(x) for x in (
        neural.get("decision"), neural.get("recommendation"), neural.get("reason"), neural.get("warnings"),
    )).lower()
    neural_adjustment = Decimal("-8") if any(token in neural_text for token in ("prefer_no_trade", "no_trade", "avoid")) else (Decimal("-4") if "bear" in neural_text or "caution" in neural_text else ZERO)
    learning_adjustment = max(Decimal("-10"), min(Decimal("8"), reflection_adjustment + outcomes_adjustment + adaptive_adjustment + neural_adjustment + market_adjustment))

    # Every signal above is still summed exactly as before -- only what it's
    # applied to has changed. Historically these were USDC deltas added onto
    # a fixed 50 USDC floor, tuned so the sum spans roughly the fixed 50-100
    # USDC range. Read as a fraction of that same calibration span (0..1) and
    # applied to today's actual span (maximum - minimum, now in
    # percentage-of-portfolio USDC terms), the tuned weights carry over
    # unchanged: a top-quality setup still gets sized at the top of the
    # configured range, a marginal one at the bottom, regardless of the
    # portfolio's absolute size.
    component_total = (
        confidence_component + edge_component + reward_to_fee_component + reward_to_risk_component
        + orderbook_component + spread_penalty + slippage_penalty + setup_component + trend_component
        + support_resistance_component + regime_penalty + learning_adjustment
    )
    quality_fraction = max(ZERO, min(ONE, component_total / _QUALITY_SCORE_CALIBRATION_SPAN))
    span = maximum - minimum
    raw_quote = minimum + quality_fraction * span
    calculated_quote = raw_quote.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    clamped_quote = max(effective_minimum, min(maximum, calculated_quote)) if maximum >= effective_minimum else ZERO

    balance = _decimal(
        available_quote_balance if available_quote_balance is not None else _nested(feature_pack, "risk_context").get("available_quote_balance"),
        "-1",
    )
    blockers: list[str] = []
    if min_pct_value <= ZERO:
        blockers.append("min_position_pct_of_portfolio_not_positive")
    if max_pct_value > ONE:
        blockers.append("max_position_pct_of_portfolio_above_100_pct")
    if min_pct_value > max_pct_value:
        blockers.append("min_position_pct_of_portfolio_above_max")
    if maximum < effective_minimum:
        blockers.append("product_or_configured_minimum_exceeds_dynamic_entry_cap")
    if balance >= ZERO and balance < effective_minimum:
        blockers.append("insufficient_quote_balance_for_min_dynamic_entry")
    if blockers:
        clamped_quote = ZERO

    final_reason = (
        f"deterministic_dynamic_entry_sizing: portfolio_priced={portfolio_priced}; "
        f"min={minimum:.2f}; max={maximum:.2f}; quality_fraction={quality_fraction:.4f}; "
        f"final={clamped_quote:.2f}; "
        f"confidence={confidence_component:.2f}; edge={edge_component:.2f}; "
        f"reward_fee={reward_to_fee_component:.2f}; reward_risk={reward_to_risk_component:.2f}; "
        f"orderbook={orderbook_component:.2f}; learning={learning_adjustment:.2f}"
    )
    return {
        "enabled": True,
        "accepted": not blockers,
        "blockers": blockers,
        "portfolio_priced": portfolio_priced,
        "portfolio_value_usdc": str(portfolio_value) if portfolio_value >= ZERO else None,
        "min_position_pct_of_portfolio": str(min_pct_value),
        "max_position_pct_of_portfolio": str(max_pct_value),
        "quality_fraction": str(quality_fraction.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        "min_quote": str(effective_minimum),
        "max_quote": str(maximum),
        "base_quote": str(minimum),
        "calculated_quote": str(calculated_quote),
        "clamped_quote": str(clamped_quote),
        "confidence_component": str(confidence_component.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "edge_component": str(edge_component.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "reward_to_fee_component": str(reward_to_fee_component.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "reward_to_risk_component": str(reward_to_risk_component.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "orderbook_component": str(orderbook_component.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "spread_penalty": str(spread_penalty),
        "slippage_penalty": str(slippage_penalty),
        "regime_penalty": str(regime_penalty),
        "learning_adjustment": str(learning_adjustment),
        "final_reason": final_reason,
        "inputs": {
            "confidence": str(confidence_value),
            "expected_edge_score": str(edge_value),
            "objective_score": str(objective_value),
            "reward_to_fee": str(reward_fee_value),
            "reward_to_risk": str(reward_risk_value),
            "spread_pct": str(spread),
            "slippage_pct": str(slippage),
            "orderbook_freshness": freshness or "unknown",
            "orderbook_depth": str(depth),
            "orderbook_imbalance": str(imbalance),
            "setup_type": setup or "unknown",
            "trend_alignment": trend_text or "unknown",
            "market_regime": regime_text or "unknown",
            "available_quote_balance": None if balance < ZERO else str(balance),
            "product_min_quote": str(product_min),
        },
    }


__all__ = [
    "ENTRY_MAX_QUOTE",
    "ENTRY_MIN_QUOTE",
    "DEFAULT_MIN_POSITION_PCT_OF_PORTFOLIO",
    "DEFAULT_MAX_POSITION_PCT_OF_PORTFOLIO",
    "calculate_dynamic_entry_quote",
]
