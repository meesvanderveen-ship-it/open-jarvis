from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Tuple

from bot.orderbook_analyzer import build_orderbook_summary
from bot.orderbook_entry_planner import build_resting_limit_entry_preview
from bot.product_rules import canonical_product_rules


EXECUTION_PLANNER_ALLOWED_KEYS = [
    "data_sufficiency",
    "execution_action",
    "execution_quality_score",
    "fill_probability_estimate",
    "adverse_selection_risk",
    "expiry_hours",
    "expiry_reason",
    "cancel_if",
    "replace_if",
    "reason",
]

DATA_SUFFICIENCY_VALUES = {"sufficient", "insufficient", "stale", "conflicting"}
EXECUTION_ACTION_VALUES = {
    "place_limit_buy",
    "place_market_buy",
    "pending_plan_only",
    "place_limit_sell_reduce",
    "place_limit_sell_close",
    "place_market_sell_close",
    "tighten_trailing",
    "loosen_trailing",
    "cancel_order",
    "replace_order",
    "hold_order",
    "no_order",
}
PROBABILITY_VALUES = {"low", "medium", "high"}
RISK_VALUES = {"low", "medium", "high"}

EXECUTION_PLANNER_PROMPT = """
You are the read-only execution planner for a Coinbase SPOT LLM swing-trading bot.

Important scope:
- Phase A is read-only. You do not place, cancel or replace live orders.
- You only advise how an already reviewed trade or position action could be executed.
- Trade thesis and execution thesis are separate: do not approve a trade; evaluate execution only.
- Orderbook data is context for tactical placement, never an independent buy/sell trigger.
- Deterministic risk rails always override your output.
- No leverage, no shorts, spot only.
- Market orders are forbidden unless Mode C market order governance is explicitly armed by deterministic config.

Use the structured orderbook summary, trade plan, judge output, position/action context and risk context.
For buys, prefer pending/limit plans. Only output place_market_buy when the strategy input already indicates a concrete BUY trade plan and deterministic Mode C governance will still perform all hard checks.
For sells, prefer local reduce-only logic; sell suggestions are only valid when a real open position/live base exists.
For trailing, suggest tighten/loosen only when a real filled position exists.

Return only strict JSON with exactly these keys:
- data_sufficiency: sufficient | insufficient | stale | conflicting
- execution_action: place_limit_buy | place_market_buy | pending_plan_only | place_limit_sell_reduce | place_limit_sell_close | place_market_sell_close | tighten_trailing | loosen_trailing | cancel_order | replace_order | hold_order | no_order
- execution_quality_score: integer 0-100
- fill_probability_estimate: low | medium | high
- adverse_selection_risk: low | medium | high
- expiry_hours: integer number of hours; 0 only when no_order/hold_order/tighten_trailing/loosen_trailing/cancel_order
- expiry_reason: concise explanation for the expiry choice
- cancel_if: array of concise cancel conditions
- replace_if: array of concise replace conditions
- reason: concise explanation

Do not include markdown, prose outside JSON, or extra keys.
""".strip()


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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _list_of_strings(value: Any, *, limit: int = 8) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return [str(value)] if str(value).strip() else []
    out: List[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _clean_enum(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _judge_decision(judge: Dict[str, Any]) -> str:
    return str((judge or {}).get("decision", "")).strip().lower()


def _judge_side(judge: Dict[str, Any]) -> str:
    return str((judge or {}).get("side", "")).strip().upper()


def _trade_plan_action(trade_plan: Dict[str, Any]) -> str:
    return str((trade_plan or {}).get("plan_action", "no_plan")).strip().lower()


ENTRY_PREPARE_ACTIONS = {
    "prepare_buy",
    "prepare_reclaim",
    "prepare_breakout",
    "prepare_mean_reversion",
    "prepare_resting_limit_entry",
    "prepare_retest_limit_entry",
    "prepare_pullback_limit_entry",
    "prepare_reclaim_retest_limit_entry",
    "prepare_breakout_retest_limit_entry",
}


def _infer_default_execution_action(
    *,
    judge: Dict[str, Any],
    trade_plan: Dict[str, Any],
    existing_position: Optional[Dict[str, Any]],
    position_action: Optional[Dict[str, Any]],
) -> str:
    decision = _judge_decision(judge)
    side = _judge_side(judge)
    plan_action = _trade_plan_action(trade_plan)
    position_action_type = str((position_action or {}).get("action", "")).strip().lower()

    if position_action_type == "reduce":
        return "place_limit_sell_reduce"
    if position_action_type == "close":
        return "place_limit_sell_close"
    if position_action_type == "hold" and existing_position:
        return "hold_order"
    if decision == "reduce_size":
        return "place_limit_sell_reduce"
    if decision == "close_position":
        return "place_limit_sell_close"
    if decision == "approve_trade" and side == "BUY":
        if plan_action in {"pending_buy_plan", "watch_for_trigger", "plan_only"}:
            return "pending_plan_only"
        return "place_limit_buy"
    if side in {"", "BUY", "NONE"} and plan_action in ENTRY_PREPARE_ACTIONS:
        return "pending_plan_only"
    if existing_position:
        return "hold_order"
    if plan_action in {"pending_buy_plan", "watch_for_trigger", "plan_only"}:
        return "pending_plan_only"
    return "no_order"


def _expiry_bounds_for_action(cfg: Any, action: str) -> Tuple[int, int, int]:
    if action in {"place_limit_sell_reduce", "place_limit_sell_close", "place_market_sell_close"}:
        return (
            int(getattr(cfg, "exit_limit_order_min_expiry_hours", 1)),
            int(getattr(cfg, "exit_limit_order_default_expiry_hours", 24)),
            int(getattr(cfg, "exit_limit_order_max_expiry_hours", 72)),
        )
    if action in {"pending_plan_only"}:
        return (
            int(getattr(cfg, "entry_limit_order_min_expiry_hours", 1)),
            int(getattr(cfg, "entry_limit_order_default_expiry_hours", 6)),
            int(getattr(cfg, "entry_limit_order_max_expiry_hours", 12)),
        )
    if action in {"place_limit_buy", "place_market_buy"}:
        return (
            int(getattr(cfg, "entry_limit_order_min_expiry_hours", 1)),
            int(getattr(cfg, "entry_limit_order_default_expiry_hours", 6)),
            int(getattr(cfg, "entry_limit_order_max_expiry_hours", 12)),
        )
    return (0, 0, 0)


def normalize_execution_plan(
    payload: Dict[str, Any],
    *,
    cfg: Any,
    ticker: str,
    source: str,
    fallback_action: str,
) -> Dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    action = _clean_enum(payload.get("execution_action"), EXECUTION_ACTION_VALUES, fallback_action)
    data_sufficiency = _clean_enum(payload.get("data_sufficiency"), DATA_SUFFICIENCY_VALUES, "insufficient")
    fill_probability = _clean_enum(payload.get("fill_probability_estimate"), PROBABILITY_VALUES, "low")
    adverse_risk = _clean_enum(payload.get("adverse_selection_risk"), RISK_VALUES, "medium")

    quality_score = max(0, min(100, _as_int(payload.get("execution_quality_score"), 0)))

    min_expiry, default_expiry, max_expiry = _expiry_bounds_for_action(cfg, action)
    raw_expiry = _as_int(payload.get("expiry_hours"), default_expiry)
    if action in {"no_order", "hold_order", "tighten_trailing", "loosen_trailing", "cancel_order"}:
        expiry_hours = 0
    elif bool(getattr(cfg, "allow_gpt_dynamic_order_expiry", True)):
        expiry_hours = max(min_expiry, min(max_expiry, raw_expiry if raw_expiry > 0 else default_expiry))
    else:
        expiry_hours = default_expiry

    safety_notes: List[str] = [
        "phase_a_read_only_no_coinbase_order_will_be_placed",
        "execution_plan_is_context_only_existing_market_execution_path_unchanged",
        "deterministic_risk_rails_override_execution_planner",
    ]
    if raw_expiry != expiry_hours and action not in {"no_order", "hold_order", "tighten_trailing", "loosen_trailing", "cancel_order"}:
        safety_notes.append(f"expiry_clamped_from_{raw_expiry}_to_{expiry_hours}_hours")

    return {
        "generated_at": _now_iso(),
        "ticker": ticker,
        "source": source,
        "read_only": True,
        "data_sufficiency": data_sufficiency,
        "execution_action": action,
        "execution_quality_score": quality_score,
        "fill_probability_estimate": fill_probability,
        "adverse_selection_risk": adverse_risk,
        "expiry_hours": expiry_hours,
        "expiry_reason": str(payload.get("expiry_reason") or ("No live order in phase A" if expiry_hours == 0 else "Expiry bounded by deterministic config")),
        "cancel_if": _list_of_strings(payload.get("cancel_if")),
        "replace_if": _list_of_strings(payload.get("replace_if")),
        "reason": str(payload.get("reason") or "Fallback normalized execution plan"),
        "risk_layer_notes": safety_notes,
    }


def build_execution_planner_input(
    *,
    ticker: str,
    analysis: Dict[str, Any],
    existing_position: Optional[Dict[str, Any]] = None,
    position_action: Optional[Dict[str, Any]] = None,
    orderbook_summary: Optional[Dict[str, Any]] = None,
    cycle_source: str = "strategy_engine",
) -> Dict[str, Any]:
    analysis = analysis if isinstance(analysis, dict) else {}
    feature_pack = analysis.get("feature_pack", {}) if isinstance(analysis.get("feature_pack"), dict) else {}
    judge = analysis.get("judge", {}) if isinstance(analysis.get("judge"), dict) else {}
    trade_plan = analysis.get("trade_plan", {}) if isinstance(analysis.get("trade_plan"), dict) else {}
    orderbook_summary = orderbook_summary or build_orderbook_summary(feature_pack)
    orderbook_entry_preview = build_resting_limit_entry_preview(ticker=ticker, analysis=analysis)
    decision_context = feature_pack.get("decision_context", {}) if isinstance(feature_pack.get("decision_context"), dict) else {}
    product_rules = canonical_product_rules(
        ticker,
        decision_context.get("product_rules") or feature_pack.get("product_rules") or feature_pack.get("exchange_rules") or {},
    )
    recent_rejections = decision_context.get("recent_exchange_rejections") or []
    execution_feasibility = decision_context.get("execution_feasibility") or orderbook_entry_preview.get("execution_feasibility") or {}

    return {
        "generated_at": _now_iso(),
        "phase": "A_read_only_execution_planner",
        "cycle_source": cycle_source,
        "ticker": ticker,
        "task": {
            "objective": "Suggest execution method only; do not approve trade thesis and do not place orders.",
            "read_only": True,
            "trade_thesis_not_equal_execution_thesis": True,
        },
        "judge": {
            "decision": judge.get("decision"),
            "side": judge.get("side"),
            "strategy": judge.get("strategy"),
            "confidence": judge.get("confidence"),
            "size_quote": judge.get("size_quote"),
            "setup_type": judge.get("setup_type"),
            "position_action": judge.get("position_action"),
            "entry_mode": judge.get("entry_mode"),
            "trigger": judge.get("trigger"),
            "reasons": judge.get("reasons", []),
        },
        "trade_plan": trade_plan,
        "position_context": {
            "has_existing_position": bool(existing_position),
            "position": existing_position or {},
            "position_action": position_action or {},
        },
        "market_context": {
            "market": feature_pack.get("market", {}),
            "structure": feature_pack.get("structure", {}),
            "sentiment": feature_pack.get("sentiment", {}),
            "news_context": feature_pack.get("news_context", {}),
            "risk_context": feature_pack.get("risk_context", {}),
            "decision_context": feature_pack.get("decision_context", {}),
        },
        "technical_context": {
            "chart_patterns": analysis.get("chart_patterns", {}),
            "regime": analysis.get("regime", {}),
            "trend": analysis.get("trend", {}),
            "breakout": analysis.get("breakout", {}),
            "meanrev": analysis.get("meanrev", {}),
            "synth": analysis.get("synth", {}),
        },
        "orderbook_summary": orderbook_summary,
        "orderbook_entry_preview": orderbook_entry_preview,
        "product_rules": product_rules,
        "recent_exchange_rejections": recent_rejections,
        "execution_feasibility": execution_feasibility,
        "safety_policy": {
            "phase_a_read_only": True,
            "no_live_limit_orders": True,
            "market_orders_require_mode_c_ack": True,
            "orderbook_is_context_not_trigger": True,
            "deterministic_risk_rails_override_gpt": True,
            "no_leverage_no_short_spot_only": True,
        },
    }


class ReadOnlyExecutionPlanner:
    """GPT-backed read-only execution planner for Phase A.

    This class never calls Coinbase and never mutates positions/orders. It only
    returns and logs an execution suggestion that later phases can evaluate.
    """

    def __init__(
        self,
        *,
        cfg: Any,
        llm_client: Any,
        log_writer: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.cfg = cfg
        self.llm_client = llm_client
        self.log_writer = log_writer
        self.model = getattr(cfg, "openai_execution_planner_model", None) or getattr(cfg, "openai_judge_model", "gpt-5.5")

    def should_plan(
        self,
        *,
        analysis: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
        position_action: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not bool(getattr(self.cfg, "enable_read_only_execution_planner", True)):
            return False

        judge = analysis.get("judge", {}) if isinstance(analysis, dict) else {}
        trade_plan = analysis.get("trade_plan", {}) if isinstance(analysis, dict) else {}
        decision = _judge_decision(judge)
        side = _judge_side(judge)
        plan_action = _trade_plan_action(trade_plan)
        position_action_type = str((position_action or {}).get("action", "")).strip().lower()

        if existing_position is not None:
            return True
        if position_action_type in {"reduce", "close", "hold"}:
            return True
        if decision in {"approve_trade", "reduce_size", "close_position"}:
            return True
        if plan_action in {"pending_buy_plan", "watch_for_trigger", "plan_only"} or plan_action in ENTRY_PREPARE_ACTIONS:
            return True
        return bool(getattr(self.cfg, "execution_planner_call_on_wait", False))

    def plan(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
        position_action: Optional[Dict[str, Any]] = None,
        cycle_source: str = "strategy_engine",
    ) -> Optional[Dict[str, Any]]:
        if not self.should_plan(
            analysis=analysis,
            existing_position=existing_position,
            position_action=position_action,
        ):
            return None

        analysis = analysis if isinstance(analysis, dict) else {}
        feature_pack = analysis.get("feature_pack", {}) if isinstance(analysis.get("feature_pack"), dict) else {}
        judge = analysis.get("judge", {}) if isinstance(analysis.get("judge"), dict) else {}
        trade_plan = analysis.get("trade_plan", {}) if isinstance(analysis.get("trade_plan"), dict) else {}
        fallback_action = _infer_default_execution_action(
            judge=judge,
            trade_plan=trade_plan,
            existing_position=existing_position,
            position_action=position_action,
        )
        orderbook_summary = build_orderbook_summary(feature_pack)
        planner_input = build_execution_planner_input(
            ticker=ticker,
            analysis=analysis,
            existing_position=existing_position,
            position_action=position_action,
            orderbook_summary=orderbook_summary,
            cycle_source=cycle_source,
        )

        raw_payload: Dict[str, Any]
        source = f"openai:{self.model}"
        try:
            raw_payload = self.llm_client.json_response(
                EXECUTION_PLANNER_PROMPT,
                planner_input,
                model=self.model,
                ticker=ticker,
                stage="execution_planner_read_only",
                allowed_keys=EXECUTION_PLANNER_ALLOWED_KEYS,
                require_all_keys=False,
                drop_unknown_keys=True,
            )
        except Exception as exc:
            raw_payload = {
                "data_sufficiency": "insufficient" if orderbook_summary.get("freshness_status") != "stale" else "stale",
                "execution_action": fallback_action,
                "execution_quality_score": 0,
                "fill_probability_estimate": "low",
                "adverse_selection_risk": "medium",
                "expiry_hours": 0,
                "expiry_reason": "Fallback because GPT execution planner failed",
                "cancel_if": [],
                "replace_if": [],
                "reason": f"execution_planner_fallback_after_error: {exc}",
            }
            source = "fallback:execution_planner_error"

        normalized = normalize_execution_plan(
            raw_payload,
            cfg=self.cfg,
            ticker=ticker,
            source=source,
            fallback_action=fallback_action,
        )
        orderbook_entry_preview = planner_input.get("orderbook_entry_preview") or {}
        if bool(orderbook_entry_preview.get("eligible")) and fallback_action in {"place_limit_buy", "pending_plan_only", "no_order"}:
            normalized["execution_action"] = "place_limit_buy"
            if int(normalized.get("expiry_hours") or 0) <= 0:
                normalized["expiry_hours"] = int(getattr(self.cfg, "entry_limit_order_default_expiry_hours", 6))
                normalized["expiry_reason"] = "Resting entry preview TTL bounded by deterministic config"
            normalized["plan_action"] = orderbook_entry_preview.get("recommended_entry_type") or "prepare_resting_limit_entry"
            normalized["execution_status"] = "pending_entry_ready"
            normalized["orderbook_entry_candidate"] = True
            normalized["resting_entry_eligible"] = True
            normalized["resting_entry_reason"] = orderbook_entry_preview.get("reason")
            normalized["preferred_limit_price"] = orderbook_entry_preview.get("entry_level")
            normalized["entry_route_type"] = orderbook_entry_preview.get("entry_route_type")
            normalized["pending_entry_preview_created"] = True
            normalized["live_resting_entry_submit_enabled"] = False
            normalized["live_resting_entry_submit_attempted"] = False
            normalized["cancel_if"] = list(orderbook_entry_preview.get("cancel_if") or normalized.get("cancel_if") or [])
            normalized["replace_if"] = list(orderbook_entry_preview.get("replace_if") or normalized.get("replace_if") or [])
            normalized["reason"] = "eligible_resting_limit_entry_prepared_from_wait_setup"
        elif bool(orderbook_entry_preview):
            normalized["orderbook_entry_candidate"] = False
            normalized["resting_entry_eligible"] = bool(orderbook_entry_preview.get("eligible"))
            normalized["resting_entry_reason"] = orderbook_entry_preview.get("reason")
            normalized["preferred_limit_price"] = orderbook_entry_preview.get("entry_level")
            normalized["entry_route_type"] = orderbook_entry_preview.get("entry_route_type")
            normalized["pending_entry_preview_created"] = False
            normalized["live_resting_entry_submit_enabled"] = False
            normalized["live_resting_entry_submit_attempted"] = False
        normalized["planner_input_summary"] = {
            "cycle_source": cycle_source,
            "judge_decision": _judge_decision(judge),
            "judge_side": _judge_side(judge),
            "trade_plan_action": _trade_plan_action(trade_plan),
            "has_existing_position": bool(existing_position),
            "position_action": (position_action or {}).get("action"),
            "orderbook_freshness_status": orderbook_summary.get("freshness_status"),
            "orderbook_snapshot_available": orderbook_summary.get("snapshot_available"),
            "orderbook_entry_preview_eligible": bool((planner_input.get("orderbook_entry_preview") or {}).get("eligible")),
            "orderbook_entry_preview_reason": (planner_input.get("orderbook_entry_preview") or {}).get("reason"),
            "entry_route_type": (planner_input.get("orderbook_entry_preview") or {}).get("entry_route_type"),
            "product_rules_available": bool((planner_input.get("product_rules") or {}).get("precision_context_available")),
            "recent_exchange_rejections_available": bool(planner_input.get("recent_exchange_rejections")),
            "execution_feasibility_available": bool(planner_input.get("execution_feasibility")),
        }
        normalized["orderbook_summary"] = orderbook_summary
        normalized["orderbook_entry_preview"] = planner_input.get("orderbook_entry_preview") or {}
        normalized["product_rules"] = planner_input.get("product_rules") or {}
        normalized["recent_exchange_rejections"] = planner_input.get("recent_exchange_rejections") or []
        normalized["execution_feasibility"] = planner_input.get("execution_feasibility") or {}

        if self.log_writer is not None:
            self.log_writer("execution_plans.jsonl", normalized)

        return normalized

# Backward-compatible alias for diagnostics/import checks.
# The actual phase-A/B strategy code uses ReadOnlyExecutionPlanner; this alias
# prevents older helper commands from failing with ImportError.
ExecutionPlanner = ReadOnlyExecutionPlanner

__all__ = [
    "ReadOnlyExecutionPlanner",
    "ExecutionPlanner",
    "normalize_execution_plan",
    "build_execution_planner_input",
    "EXECUTION_PLANNER_ALLOWED_KEYS",
]
