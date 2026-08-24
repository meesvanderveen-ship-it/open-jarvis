from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bot.exit_target_source_policy import build_exit_target_source_policy_report
from bot.live_order_size_policy import effective_exit_min_quote
from bot.phase_d3_open_exit_lifecycle_manager import logical_position_id_candidates
from bot.state_store import StateStore

ZERO = Decimal("0")
ONE = Decimal("1")
D2_PHASE = "D2_position_executor_multi_exit_fee_edge"
D2_PLAN_STATUS_READY = "position_executor_plan_ready_no_live_exit_submit"
D2_PLAN_STATUS_BLOCKED = "position_executor_plan_blocked"
D2_PLAN_STATUS_NO_POSITION = "no_open_position_for_position_executor"
D2_PLAN_FINGERPRINT_SCHEMA_VERSION = "d2_plan_fingerprint_v1"
D2_DEFAULT_PLANS_PATH = Path("state/phase_d2_position_executor_plans.json")
D2_DEFAULT_AUDIT_PATH = Path("logs/phase_d2_position_executor.jsonl")


def build_d2_exit_market_context(ticker: str, *, coinbase_client: Any = None) -> Dict[str, Any]:
    """Live 1h support/resistance for exit_target_source_policy's market-based
    target sources, so D.2 can pick a real target instead of always falling
    back to the static position.take_profit_price (a fixed R-multiple set at
    entry, not derived from market structure).

    Deferred import to avoid a module-load-time dependency on pandas/candles
    for every phase_d2 caller (most just want the pure fee-edge math). Any
    failure (no client, network, missing candles) degrades to {} -- the exact
    same fallback behaviour as before this function existed.
    """
    if coinbase_client is None:
        return {}
    try:
        from bot.market_data import MarketDataService

        feature_pack = MarketDataService(coinbase_client).build_feature_pack(ticker)
        structure = feature_pack.get("structure") if isinstance(feature_pack, dict) else None
        if not isinstance(structure, dict):
            return {}
        resistance = structure.get("nearest_resistance")
        support = structure.get("nearest_support")
        if resistance is None and support is None:
            return {}
        return {
            "nearest_resistance": resistance,
            "nearest_support": support,
            "market_structure": {"resistance_level": resistance, "support_level": support},
        }
    except Exception:
        return {}


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


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


def _stable_decimal_str(value: Any) -> str:
    dec = _to_decimal(value, "0")
    return format(dec.normalize(), "f") if dec != ZERO else "0"


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _stable_exit_fingerprint_payload(exits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in exits:
        row = _as_dict(raw)
        out.append({
            "label": str(row.get("label") or "").strip().upper(),
            "fraction": _stable_decimal_str(row.get("fraction")),
            "base_size": _stable_decimal_str(row.get("base_size")),
            "limit_price": None if row.get("limit_price") is None else _stable_decimal_str(row.get("limit_price")),
            "trailing_stop": bool(row.get("trailing_stop")),
        })
    return out


def build_d2_plan_fingerprint(plan: Dict[str, Any]) -> Dict[str, str]:
    plan_dict = _as_dict(plan)
    entry = _as_dict(plan_dict.get("entry"))
    risk = _as_dict(plan_dict.get("risk"))
    trailing = _as_dict(plan_dict.get("trailing"))
    fee_edge = _as_dict(plan_dict.get("fee_edge"))
    payload = {
        "schema_version": D2_PLAN_FINGERPRINT_SCHEMA_VERSION,
        "ticker": _normalize_ticker(plan_dict.get("ticker")),
        "position_id": str(plan_dict.get("position_id") or "").strip(),
        "source_order_id": str(entry.get("source_order_id") or "").strip(),
        "source_client_order_id": str(plan_dict.get("source_client_order_id") or "").strip(),
        "entry_price": _stable_decimal_str(entry.get("entry_price")),
        "base_size": _stable_decimal_str(entry.get("base_size")),
        "quote_size": _stable_decimal_str(entry.get("quote_size")),
        "initial_stop_price": _stable_decimal_str(risk.get("initial_stop_price")),
        "invalidation_price": _stable_decimal_str(risk.get("invalidation_price")),
        "time_limit_hours": int(_to_int(risk.get("time_limit_hours"), 0)),
        "exits": _stable_exit_fingerprint_payload(_as_dict({"exits": plan_dict.get("exits")}).get("exits") or []),
        "runner_enabled": bool(trailing.get("runner_enabled")),
        "trailing_activation_profit_pct": _stable_decimal_str(trailing.get("activation_profit_pct")),
        "trailing_distance_pct": _stable_decimal_str(trailing.get("distance_pct")),
        "fee_edge_status": str(fee_edge.get("status") or "").strip(),
        "expected_net_edge_pct": _stable_decimal_str(fee_edge.get("expected_net_edge_pct")),
        "minimum_expected_net_edge_pct": _stable_decimal_str(fee_edge.get("minimum_expected_net_edge_pct")),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        "plan_fingerprint_schema_version": D2_PLAN_FINGERPRINT_SCHEMA_VERSION,
        "plan_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _cfg_dec(cfg: Any, name: str, default: Decimal) -> Decimal:
    return _to_decimal(getattr(cfg, name, default), str(default))


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    return _to_int(getattr(cfg, name, default), default)


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= ZERO:
        return value
    try:
        units = (value / increment).to_integral_value(rounding=ROUND_DOWN)
        return units * increment
    except Exception:
        return value


def _first_positive(*values: Any, default: str = "0") -> Decimal:
    for value in values:
        dec = _to_decimal(value, "0")
        if dec > ZERO:
            return dec
    return Decimal(default)


def position_protective_risk_state(position: Dict[str, Any], market_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    position = _as_dict(position)
    market_context = _as_dict(market_context)
    stop = _first_positive(position.get("stop_price"), market_context.get("initial_stop_price"), default="0")
    invalidation = _first_positive(position.get("invalidation_price"), market_context.get("invalidation_price"), market_context.get("initial_stop_price"), default="0")
    entry = _entry_price(position)
    incomplete = bool(stop <= ZERO or invalidation <= ZERO or (entry > ZERO and (stop >= entry or invalidation >= entry)))
    blockers: List[str] = []
    if stop <= ZERO:
        blockers.append("stop_price_missing")
    if invalidation <= ZERO:
        blockers.append("invalidation_price_missing")
    if entry > ZERO and stop > ZERO and stop >= entry:
        blockers.append("stop_price_not_below_entry")
    if entry > ZERO and invalidation > ZERO and invalidation >= entry:
        blockers.append("invalidation_price_not_below_entry")
    return _json_safe({
        "status": "position_risk_incomplete" if incomplete else "protective_stop_state_complete",
        "complete": not incomplete,
        "stop_price": str(stop),
        "invalidation_price": str(invalidation),
        "blockers": blockers,
        "blocks_new_same_ticker_entries": incomplete,
    })


def _raw_entry_price(position: Dict[str, Any]) -> Decimal:
    plan = _as_dict(position.get("position_plan_snapshot"))
    return _first_positive(
        position.get("entry_price"),
        position.get("avg_entry_price"),
        position.get("average_entry_price"),
        position.get("avg_fill_price"),
        position.get("source_order_avg_fill_price"),
        plan.get("entry_mid_price"),
        default="0",
    )


def _position_quote(position: Dict[str, Any]) -> Decimal:
    return _first_positive(
        position.get("position_size_quote"),
        position.get("quote_size"),
        position.get("filled_quote_value"),
        position.get("filled_quote"),
        default="0",
    )


def _position_base(position: Dict[str, Any]) -> Decimal:
    base = _first_positive(
        position.get("position_size_base"),
        position.get("bot_managed_base"),
        position.get("live_inventory_base"),
        position.get("size_base"),
        position.get("filled_size_base"),
        position.get("filled_size"),
        position.get("filled_base"),
    )
    if base > ZERO:
        return base
    quote = _position_quote(position)
    price = _raw_entry_price(position)
    if quote > ZERO and price > ZERO:
        return quote / price
    return ZERO


def _entry_price(position: Dict[str, Any]) -> Decimal:
    price = _raw_entry_price(position)
    if price <= ZERO:
        quote = _position_quote(position)
        base = _first_positive(
            position.get("position_size_base"),
            position.get("bot_managed_base"),
            position.get("live_inventory_base"),
            position.get("size_base"),
            position.get("filled_size_base"),
            position.get("filled_size"),
            position.get("filled_base"),
        )
        if quote > ZERO and base > ZERO:
            return quote / base
    return price


def _default_min_order_quote(exchange_rules: Optional[Dict[str, Any]]) -> Decimal:
    rules = _as_dict(exchange_rules)
    product_min = _first_positive(
        rules.get("quote_min_size"),
        rules.get("min_market_funds"),
        rules.get("min_order_quote"),
        default="1.00",
    )
    return max(product_min, Decimal("20.00"))


def _base_increment(exchange_rules: Optional[Dict[str, Any]]) -> Decimal:
    rules = _as_dict(exchange_rules)
    return _first_positive(rules.get("base_increment"), rules.get("base_increment_size"), default="0")


def _price_increment(exchange_rules: Optional[Dict[str, Any]]) -> Decimal:
    rules = _as_dict(exchange_rules)
    return _first_positive(
        rules.get("price_increment"),
        rules.get("price_increment_size"),
        rules.get("quote_increment"),
        rules.get("quote_increment_size"),
        default="0",
    )


def build_fee_cost_model(
    *,
    cfg: Any,
    spread_pct: Decimal | str | None = None,
    slippage_pct: Decimal | str | None = None,
) -> Dict[str, Any]:
    entry_fee = _cfg_dec(cfg, "phase_d2_estimated_entry_fee_pct", Decimal("0.0040"))
    exit_fee = _cfg_dec(cfg, "phase_d2_estimated_exit_fee_pct", Decimal("0.0040"))
    default_spread_slippage = _cfg_dec(cfg, "phase_d2_estimated_spread_slippage_pct", Decimal("0.0020"))
    buffer = _cfg_dec(cfg, "phase_d2_fee_safety_buffer_pct", Decimal("0.0025"))
    spread = _to_decimal(spread_pct, "0") if spread_pct is not None else ZERO
    slippage = _to_decimal(slippage_pct, "0") if slippage_pct is not None else ZERO
    observed_cost = spread + slippage
    spread_slippage = max(default_spread_slippage, observed_cost)
    total = entry_fee + exit_fee + spread_slippage + buffer
    return {
        "entry_fee_pct": str(entry_fee),
        "exit_fee_pct": str(exit_fee),
        "spread_slippage_pct": str(spread_slippage),
        "fee_safety_buffer_pct": str(buffer),
        "estimated_total_cost_pct": str(total),
    }


def assess_minimum_net_edge(
    *,
    cfg: Any,
    entry_price: Decimal | str,
    target_price: Decimal | str,
    stop_price: Decimal | str,
    spread_pct: Decimal | str | None = None,
    slippage_pct: Decimal | str | None = None,
) -> Dict[str, Any]:
    entry = _to_decimal(entry_price, "0")
    target = _to_decimal(target_price, "0")
    stop = _to_decimal(stop_price, "0")
    blockers: List[str] = []
    passed: List[str] = []
    warnings: List[str] = []

    cost_model = build_fee_cost_model(cfg=cfg, spread_pct=spread_pct, slippage_pct=slippage_pct)
    total_cost = _to_decimal(cost_model["estimated_total_cost_pct"], "0")
    min_net_edge = _cfg_dec(cfg, "phase_d2_min_expected_net_edge_pct", Decimal("0.0125"))
    min_reward_fee = _cfg_dec(cfg, "phase_d2_min_reward_to_fee_ratio", Decimal("3.0"))
    min_reward_risk = _cfg_dec(cfg, "phase_d2_min_reward_to_risk_ratio", Decimal("1.5"))

    gross_profit_pct = ZERO
    risk_pct = ZERO
    reward_to_fee_ratio: Optional[Decimal] = None
    reward_to_risk_ratio: Optional[Decimal] = None

    if entry <= ZERO:
        blockers.append("entry_price_missing_or_zero")
    if target <= entry:
        blockers.append("target_price_not_above_entry")
    if stop <= ZERO or stop >= entry:
        blockers.append("initial_stop_missing_or_not_below_entry")

    if entry > ZERO and target > entry:
        gross_profit_pct = (target - entry) / entry
    if entry > ZERO and ZERO < stop < entry:
        risk_pct = (entry - stop) / entry

    expected_net_edge_pct = gross_profit_pct - total_cost
    if total_cost > ZERO:
        reward_to_fee_ratio = gross_profit_pct / total_cost
    if risk_pct > ZERO:
        reward_to_risk_ratio = gross_profit_pct / risk_pct

    if expected_net_edge_pct >= min_net_edge:
        passed.append("expected_net_edge_above_minimum")
    else:
        blockers.append("expected_net_edge_too_low")

    if reward_to_fee_ratio is not None and reward_to_fee_ratio >= min_reward_fee:
        passed.append("reward_to_fee_ratio_above_minimum")
    else:
        blockers.append("reward_to_fee_ratio_too_low")

    if reward_to_risk_ratio is not None and reward_to_risk_ratio >= min_reward_risk:
        passed.append("reward_to_risk_ratio_above_minimum")
    else:
        blockers.append("reward_to_risk_ratio_too_low")

    status = "net_edge_pass" if not blockers else "net_edge_blocked"
    return {
        "status": status,
        "passed": passed,
        "blockers": blockers,
        "warnings": warnings,
        "entry_price": str(entry),
        "target_price": str(target),
        "stop_price": str(stop),
        "expected_gross_profit_pct": str(gross_profit_pct),
        "risk_pct": str(risk_pct),
        "expected_net_edge_pct": str(expected_net_edge_pct),
        "minimum_expected_net_edge_pct": str(min_net_edge),
        "reward_to_fee_ratio": str(reward_to_fee_ratio) if reward_to_fee_ratio is not None else None,
        "minimum_reward_to_fee_ratio": str(min_reward_fee),
        "reward_to_risk_ratio": str(reward_to_risk_ratio) if reward_to_risk_ratio is not None else None,
        "minimum_reward_to_risk_ratio": str(min_reward_risk),
        "cost_model": cost_model,
    }


def _fallback_exit_slices(
    *,
    base_size: Decimal,
    entry_price: Decimal,
    tp1_price: Decimal,
    tp2_price: Decimal,
    min_order_quote: Decimal,
    base_increment: Decimal,
    price_increment: Decimal,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []

    def mk(label: str, fraction: Decimal, price: Decimal, trailing: bool = False) -> Dict[str, Any]:
        raw_base = base_size * fraction
        q_base = _quantize_down(raw_base, base_increment)
        q_price = _quantize_down(price, price_increment) if not trailing else price
        quote = q_base * q_price if q_price > ZERO else ZERO
        return {
            "label": label,
            "fraction": str(fraction),
            "base_size": str(q_base),
            "limit_price": str(q_price) if not trailing else None,
            "estimated_quote": str(quote),
            "trailing_stop": bool(trailing),
        }

    default_slices = [
        mk("TP1", Decimal("0.50"), tp1_price),
        mk("TP2", Decimal("0.25"), tp2_price),
        mk("RUNNER", Decimal("0.25"), entry_price, trailing=True),
    ]
    valid_tp = [x for x in default_slices if x["trailing_stop"] or _to_decimal(x["estimated_quote"], "0") >= min_order_quote]
    if len(valid_tp) == len(default_slices):
        return default_slices, warnings

    # Small-position fallback: 70% TP1 + 30% runner.
    warnings.append("partial_exit_under_min_live_order_quote_blocked")
    warnings.append("small_position_fallback_reduced_to_tp1_plus_runner")
    fallback_two = [mk("TP1", Decimal("0.70"), tp1_price), mk("RUNNER", Decimal("0.30"), entry_price, trailing=True)]
    if _to_decimal(fallback_two[0]["estimated_quote"], "0") >= min_order_quote:
        return fallback_two, warnings

    # Smaller fallback: single TP/close intent for all base if even 70% is below min-size.
    warnings.append("small_position_fallback_single_tp_only")
    single = [mk("TP_CLOSE", Decimal("1.00"), tp1_price)]
    if _to_decimal(single[0]["estimated_quote"], "0") < min_order_quote:
        warnings.append("full_close_below_min_live_order_quote_allowed_if_product_rules_allow")
        single[0]["below_min_order_quote"] = True
    return single, warnings




def _is_test_or_diagnostic_ticker(ticker: Any) -> bool:
    t = _normalize_ticker(ticker)
    return t.startswith("TEST-") or t.startswith("DIAGNOSTIC-")


def is_d2_manageable_open_position(position: Dict[str, Any], *, ticker: str | None = None) -> bool:
    """Return True only for real, non-diagnostic, non-zero open positions.

    D.2.1 pre-D.3 hardening: state files may contain old paper diagnostics or
    zero-base placeholder records. Those must not be treated as selected open
    positions, because D.3 will later derive live reduce-only exit orders from
    real position state.
    """
    p = _as_dict(position)
    pticker = _normalize_ticker(p.get("ticker") or ticker)
    selected = _normalize_ticker(ticker) if ticker else ""
    if selected and pticker and pticker != selected:
        return False
    if _is_test_or_diagnostic_ticker(pticker):
        return False
    if str(p.get("paper_only", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return False
    if str(p.get("status", "open")).strip().lower() not in {"open", "active"}:
        return False
    if _position_base(p) <= ZERO:
        return False
    if _entry_price(p) <= ZERO:
        return False
    return True

def build_multi_exit_bracket_lite_plan(
    *,
    cfg: Any,
    position: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
    exchange_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    position = _as_dict(position)
    market_context = _as_dict(market_context)
    ticker = _normalize_ticker(position.get("ticker") or market_context.get("ticker"))
    base = _position_base(position)
    quote = _position_quote(position)
    entry = _entry_price(position)
    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    if not ticker:
        blockers.append("ticker_missing")
    if base <= ZERO:
        blockers.append("position_base_missing_or_zero")
    if entry <= ZERO:
        blockers.append("entry_price_missing_or_zero")

    costs = build_fee_cost_model(cfg=cfg)
    total_cost = _to_decimal(costs["estimated_total_cost_pct"], "0")
    min_net = _cfg_dec(cfg, "phase_d2_min_expected_net_edge_pct", Decimal("0.0125"))
    min_reward_fee = _cfg_dec(cfg, "phase_d2_min_reward_to_fee_ratio", Decimal("3.0"))
    min_reward_risk = _cfg_dec(cfg, "phase_d2_min_reward_to_risk_ratio", Decimal("1.5"))
    risk_state = position_protective_risk_state(position, market_context)
    provided_stop = _first_positive(market_context.get("initial_stop_price"), position.get("stop_price"), position.get("invalidation_price"), default="0")
    provisional_stop = provided_stop if ZERO < provided_stop < entry else entry * Decimal("0.9750")
    provisional_risk_pct = (entry - provisional_stop) / entry if entry > ZERO and provisional_stop > ZERO else Decimal("0.0250")
    required_first_target_pct = max(
        Decimal("0.0250"),
        min_net + total_cost + Decimal("0.0050"),
        total_cost * min_reward_fee,
        provisional_risk_pct * min_reward_risk,
    )
    risk_reward_default_tp1 = entry * (ONE + required_first_target_pct) if entry > ZERO else ZERO
    target_policy = build_exit_target_source_policy_report(
        cfg=cfg,
        position=position,
        market_context=market_context,
        trade_plan=market_context.get("trade_plan") if isinstance(market_context.get("trade_plan"), dict) else None,
        risk_reward_fallback_target=risk_reward_default_tp1,
    )
    provided_tp1 = _to_decimal(target_policy.get("target_price"), "0")
    provided_tp2 = _first_positive(market_context.get("tp2_price"), position.get("take_profit_2"), default="0")

    # Conservative bracket defaults if analyst/judge did not yet provide levels.
    tp1 = provided_tp1 if provided_tp1 > entry else entry * (ONE + required_first_target_pct)
    # TP2 must always be above TP1. Earlier preview defaults could create
    # confusing labels when the required TP1 exceeded the static 5.5% default.
    tp2_default = max(tp1 * Decimal("1.0100"), entry * (ONE + required_first_target_pct + Decimal("0.0150")))
    tp2 = provided_tp2 if provided_tp2 > tp1 else tp2_default
    if tp2 <= tp1:
        tp2 = tp1 * Decimal("1.0100")
        warnings.append("tp2_adjusted_above_tp1")
    stop = provided_stop if ZERO < provided_stop < entry else entry * Decimal("0.9750")

    edge = assess_minimum_net_edge(cfg=cfg, entry_price=entry, target_price=tp1, stop_price=stop)
    if target_policy.get("is_stale_target"):
        blockers.append("exit_target_policy_stale_target")
        warnings.append(str(target_policy.get("target_reason") or "exit_target_policy_stale_target"))
    if not risk_state["complete"]:
        blockers.append("position_risk_incomplete_stop_or_invalidation_missing")
        warnings.append("d2_requires_explicit_stop_and_invalidation_before_d3")
    if edge["status"] == "net_edge_pass":
        passed.append("minimum_net_edge_passed_for_tp1")
    else:
        blockers.extend(edge["blockers"])

    min_order_quote = effective_exit_min_quote(cfg, _default_min_order_quote(exchange_rules))
    increment = _base_increment(exchange_rules)
    price_increment = _price_increment(exchange_rules)
    exits, fallback_warnings = _fallback_exit_slices(
        base_size=base,
        entry_price=entry,
        tp1_price=tp1,
        tp2_price=tp2,
        min_order_quote=min_order_quote,
        base_increment=increment,
        price_increment=price_increment,
    )
    warnings.extend(fallback_warnings)

    total_exit_base = sum((_to_decimal(x.get("base_size"), "0") for x in exits), ZERO)
    if total_exit_base > base:
        blockers.append("exit_intents_exceed_position_base")
    else:
        passed.append("exit_intents_do_not_exceed_position_base")

    if len([x for x in exits if not x.get("trailing_stop")]) > _cfg_int(cfg, "phase_d2_max_tp_orders_per_position", 2):
        blockers.append("too_many_tp_orders_for_position")

    trailing_activation = _cfg_dec(cfg, "phase_d2_default_trailing_activation_pct", Decimal("0.0250"))
    trailing_distance = _cfg_dec(cfg, "phase_d2_default_trailing_distance_pct", Decimal("0.0180"))
    time_limit_hours = _cfg_int(cfg, "phase_d2_default_time_limit_hours", 48)

    plan_status = D2_PLAN_STATUS_READY if not blockers else D2_PLAN_STATUS_BLOCKED
    plan_id = f"d2-{ticker}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}" if ticker else f"d2-UNKNOWN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    plan = {
        "phase": D2_PHASE,
        "status": plan_status,
        "plan_id": plan_id,
        "generated_at": _now_iso(),
        "ticker": ticker,
        "position_id": (
            logical_position_id_candidates(position)[0]
            if logical_position_id_candidates(position)
            else str(position.get("position_id") or position.get("order_id") or ticker)
        ),
        "entry": {
            "entry_price": str(entry),
            "base_size": str(base),
            "quote_size": str(quote),
            "source_order_id": str(position.get("order_id") or position.get("client_order_id") or ""),
        },
        "risk": {
            "initial_stop_price": str(stop),
            "invalidation_price": str(_to_decimal(risk_state.get("invalidation_price"), str(stop)) or stop),
            "time_limit_hours": time_limit_hours,
            "protective_stop_status": risk_state["status"],
            "risk_state_complete": risk_state["complete"],
        },
        "exits": exits,
        "trailing": {
            "runner_enabled": any(bool(x.get("trailing_stop")) for x in exits),
            "activation_profit_pct": str(trailing_activation),
            "distance_pct": str(trailing_distance),
        },
        "scaling": {
            "allow_add_to_winner": _cfg_bool(cfg, "phase_d2_allow_add_to_winner", False),
            "max_adds": _cfg_int(cfg, "phase_d2_max_adds_to_winner", 0),
            "allow_averaging_down": _cfg_bool(cfg, "phase_d2_allow_averaging_down", False),
        },
        "fee_edge": edge,
        "exit_target_source_policy": target_policy,
        "coinbase_min_size_fallback": {
            "min_order_quote": str(min_order_quote),
            "base_increment": str(increment),
            "price_increment": str(price_increment),
            "fallback_warnings": fallback_warnings,
        },
        "reserved_exit_base_preview": str(total_exit_base),
        "unreserved_runner_or_residual_base": str(max(ZERO, base - total_exit_base)),
        "passed_checks": passed,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "protective_risk_state": risk_state,
        "risk_incomplete_action_route": (
            {
                "required": True,
                "route": "controlled_close_or_risk_reconstruction",
                "controlled_close_tool": "tools/prepare_risk_incomplete_position_action.py",
                "normal_d3_live_exit_allowed": False,
                "reason": "D.3 live exits require complete stop_price and invalidation_price",
            }
            if not risk_state["complete"]
            else {"required": False, "normal_d3_live_exit_allowed": True}
        ),
        "safety_policy": {
            "d2_does_not_submit_live_sell_orders": True,
            "reduce_only_exit_intents_only": True,
            "exit_intents_must_not_exceed_position_base": True,
            "minimum_net_edge_required": True,
            "no_averaging_down": not _cfg_bool(cfg, "phase_d2_allow_averaging_down", False),
            "live_exits_still_forbidden_until_d3": True,
        },
    }
    plan["source_client_order_id"] = str(position.get("phase_c43_client_order_id") or position.get("client_order_id") or "")
    plan.update(build_d2_plan_fingerprint(plan))
    return plan


def load_position_executor_plans(path: Path = D2_DEFAULT_PLANS_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {"plans": {}}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {"plans": {}}
    except Exception:
        return {"plans": {}}


def save_position_executor_plan(plan: Dict[str, Any], path: Path = D2_DEFAULT_PLANS_PATH) -> Dict[str, Any]:
    data = load_position_executor_plans(path)
    plans = data.setdefault("plans", {})
    ticker = _normalize_ticker(plan.get("ticker")) or "UNKNOWN"
    plans[ticker] = _json_safe(plan)
    data["updated_at"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    return data


def append_position_executor_audit(event: Dict[str, Any], path: Path = D2_DEFAULT_AUDIT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_json_safe(event), sort_keys=True) + "\n")


def build_phase_d2_position_executor_report(
    *,
    cfg: Any,
    ticker: str,
    state_store: Optional[StateStore] = None,
    position: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    exchange_rules: Optional[Dict[str, Any]] = None,
    persist_plan: bool = False,
    plans_path: Path = D2_DEFAULT_PLANS_PATH,
    audit_path: Path = D2_DEFAULT_AUDIT_PATH,
) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker)
    store = state_store or StateStore()
    raw_selected_pos = position if position is not None else store.get_position(selected)
    if position is None:
        raw_positions = [p for p in store.get_positions().values() if isinstance(p, dict)]
        open_positions = [p for p in raw_positions if is_d2_manageable_open_position(p)]
        ignored_positions = [p for p in raw_positions if str(p.get("status", "open")).lower() in {"open", "active"} and not is_d2_manageable_open_position(p)]
        pos = raw_selected_pos if is_d2_manageable_open_position(raw_selected_pos or {}, ticker=selected) else None
    else:
        open_positions = [position] if is_d2_manageable_open_position(position, ticker=selected) else []
        ignored_positions = [] if is_d2_manageable_open_position(position, ticker=selected) else [position]
        pos = position

    hygiene_warnings: List[str] = []
    if raw_selected_pos and position is None and pos is None:
        hygiene_warnings.append("ghost_or_zero_base_selected_position_ignored")
    if ignored_positions:
        hygiene_warnings.append(f"ignored_non_manageable_positions={len(ignored_positions)}")

    base_report: Dict[str, Any] = {
        "phase": D2_PHASE,
        "generated_at": _now_iso(),
        "ticker": selected,
        "enable_phase_d2_position_executor": _cfg_bool(cfg, "enable_phase_d2_position_executor", True),
        "enable_live_exit_orders": _cfg_bool(cfg, "enable_live_exit_orders", False),
        "autonomous_allow_exits": _cfg_bool(cfg, "autonomous_allow_exits", False),
        "phase_c_disable_exit_limit_orders": _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True),
        "open_position_count": len(open_positions),
        "ignored_position_count": len(ignored_positions),
        "selected_position_present": bool(pos),
        "raw_selected_position_present": bool(raw_selected_pos),
        "pre_d3_hygiene": {
            "ghost_zero_base_filter_enabled": True,
            "diagnostic_test_ticker_filter_enabled": True,
            "ignored_position_count": len(ignored_positions),
        },
        "live_sell_submit_attempted_by_this_tool": False,
        "live_sell_order_submitted": False,
        "safety_policy": {
            "d2_scaffold_only": True,
            "does_not_submit_live_sell_orders": True,
            "does_not_modify_env": True,
            "multiple_exit_intents_are_preview_only": True,
            "d3_required_for_live_reduce_only_exits": True,
        },
        "persisted": False,
        "persisted_path": str(plans_path),
        "persisted_ticker_key": selected,
        "linked_position_id": (
            logical_position_id_candidates(pos)[0]
            if logical_position_id_candidates(pos)
            else selected
        ),
        "source_order_id": str((pos or {}).get("source_order_id") or (pos or {}).get("order_id") or ""),
        "source_client_order_id": str((pos or {}).get("phase_c43_client_order_id") or (pos or {}).get("client_order_id") or ""),
        "plan_fingerprint": None,
        "plan_fingerprint_schema_version": D2_PLAN_FINGERPRINT_SCHEMA_VERSION,
    }

    if not pos:
        base_report.update({
            "status": D2_PLAN_STATUS_NO_POSITION,
            "plan": None,
            "blockers": ["selected_open_position_not_found"],
            "warnings": hygiene_warnings,
            "next_step": "Wacht op een gevulde C.4.3 entry of lever een sample/open position aan; D.2 plaatst geen live SELL-orders.",
        })
        return _json_safe(base_report)

    plan = build_multi_exit_bracket_lite_plan(
        cfg=cfg,
        position=pos,
        market_context=market_context,
        exchange_rules=exchange_rules,
    )
    persisted = False
    if persist_plan and plan["status"] == D2_PLAN_STATUS_READY:
        save_position_executor_plan(plan, plans_path)
        append_position_executor_audit({"event_type": "phase_d2_position_executor_plan_saved", "ticker": selected, "plan": plan}, audit_path)
        persisted = True

    risk_route = _as_dict(plan.get("risk_incomplete_action_route"))
    next_step = "D.3 controlled live reduce-only exits is nodig voordat deze exit-intenties echte SELL-orders mogen worden."
    if risk_route.get("required"):
        next_step = "Gebruik eerst controlled-close of risk-reconstruction; normale D.3 live SELL blijft geblokkeerd voor risk-incomplete posities."
    base_report.update({
        "status": plan["status"],
        "plan_ready_no_live_exit_submit": plan["status"] == D2_PLAN_STATUS_READY,
        "plan": plan,
        "plan_fingerprint": plan.get("plan_fingerprint"),
        "plan_fingerprint_schema_version": plan.get("plan_fingerprint_schema_version", D2_PLAN_FINGERPRINT_SCHEMA_VERSION),
        "persisted": persisted,
        "blockers": plan.get("blockers", []),
        "warnings": hygiene_warnings + plan.get("warnings", []),
        "risk_incomplete_action_route": risk_route,
        "next_step": next_step,
    })
    return _json_safe(base_report)


__all__ = [
    "D2_PHASE",
    "D2_PLAN_STATUS_READY",
    "D2_PLAN_STATUS_BLOCKED",
    "assess_minimum_net_edge",
    "build_fee_cost_model",
    "build_d2_plan_fingerprint",
    "build_multi_exit_bracket_lite_plan",
    "build_phase_d2_position_executor_report",
    "load_position_executor_plans",
    "save_position_executor_plan",
    "is_d2_manageable_open_position",
    "position_protective_risk_state",
]
