from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bot.chart_patterns import build_chart_pattern_context
from bot.trade_planner import (
    build_default_no_plan,
    build_starter_probe_plan_from_context,
    build_trade_planner_input,
    is_valid_entry_trade_plan,
    normalize_trade_plan,
)
from bot.trade_reflection import TradeReflectionStore, build_trade_reflection_input
from bot.decision_outcome_tracker import DecisionOutcomeStore
from bot.shadow_outcome_accelerator import ShadowOutcomeStore as _ShadowOutcomeAcceleratorStore
from bot.pending_trade_plans import PendingTradePlanStore, build_default_pending_context
from bot.execution_planner import ReadOnlyExecutionPlanner
from bot.execution_outcome_tracker import ExecutionOutcomeTracker
from bot.exchange_rejection_memory import recent_rejections_for_context
from bot.live_learning_orchestrator import load_runtime_learning_context, run_live_learning_maintenance
from bot.live_order_size_policy import bounded_exploration_report, live_order_size_policy_report
from bot.market_intelligence_context import inject_market_intelligence_feature_pack
from bot.neural_shadow_policy import build_shadow_context
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness
from bot.phase_c_live_submitter import prepare_phase_c_live_entry_submission
from bot.product_rules import canonical_product_rules, execution_feasibility_context, load_product_rules_cache
from bot.phase_c43_autonomous_entry_live import (
    build_phase_c43_guard_and_submit_preparation,
    count_local_phase_c_live_entry_orders,
)
from bot.phase_d3_open_exit_lifecycle_manager import (
    iter_matching_open_d3_orders,
    logical_position_id_candidates,
)
from bot.phase_d3_controlled_live_exits import (
    D3_ACK,
    D3_BLOCKED,
    D3_PHASE,
    build_phase_d3_controlled_live_exit_report,
    build_phase_d3_full_close_exit_intent,
    submit_phase_d3_controlled_exit,
)
from bot.controlled_stop_market_exit_plan import build_controlled_stop_market_exit_plan
from bot.phase_d2_position_executor import D2_PLAN_STATUS_READY
from bot.order_store import OrderStore
from bot.order_plan import build_order_intent_from_execution_plan, is_actionable_order_intent
from bot.limit_order_manager import PaperLimitOrderManager
from bot.pending_order_intents import (
    PendingOrderIntentStore,
    build_pending_intent_from_execution_plan,
    build_watchlist_intent_from_analysis,
    _watchlist_candidate_diagnostics,
)
from bot.config import BotConfig, effective_phase_c_allowed_tickers
from bot.llm_clients import DeepSeekClient, ResilientLLMClient, AnthropicClient, FINAL_JUDGE_REQUIRED_KEYS, FINAL_JUDGE_OPTIONAL_ORDERBOOK_ENTRY_KEYS
from bot.llm_cost_ledger import set_current_cycle_id
from bot.market_data import MarketDataService
from bot.position_manager import PositionManager
from bot.prompts import (
    DEEPSEEK_PREPROCESS_PROMPT,
    GPT_NANO_GATE_PROMPT,
    GPT_NANO_POSITION_WATCH_PROMPT,
    REGIME_PROMPT,
    TREND_PROMPT,
    BREAKOUT_PROMPT,
    MEANREV_PROMPT,
    BULL_PROMPT,
    BEAR_PROMPT,
    SYNTH_PROMPT,
    TRADE_PLANNER_PROMPT,
    CLAUDE_JUDGE_PROMPT,
)
from bot.state_store import StateStore
from bot.coinbase_client import CoinbaseClient


LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

OPENAI_NANO_MODEL = "gpt-5.4-nano"
DEFAULT_ANALYST_MODEL = "gpt-5.4-mini"
DEFAULT_JUDGE_MODEL = "gpt-5.5"
DEFAULT_TRADE_PLANNER_MODEL = "gpt-5.5"
DEFAULT_EXECUTION_PLANNER_MODEL = "gpt-5.5"


MODULE_ALLOWED_KEYS = {
    "deepseek_preprocess": [
        "regime_hints",
        "trend_hints",
        "breakout_hints",
        "meanrev_hints",
        "risk_hints",
        "concise_evidence",
        "raw_pattern_hints",
        "news_sentiment_hints",
        "uncertainties",
    ],
    "entry_gate": [
        "decision",
        "priority",
        "setup_type",
        "confidence",
        "reasons",
        "warnings",
    ],
    "position_watch": [
        "decision",
        "confidence",
        "reasons",
        "warnings",
    ],
    "regime": [
        "regime_label",
        "regime_confidence",
        "regime_strength",
        "primary_driver",
        "secondary_driver",
        "regime_invalidators",
    ],
    "trend": [
        "trend_direction",
        "trend_strength_score",
        "trend_alignment_score",
        "pullback_quality_score",
        "continuation_probability",
        "overextension_risk",
        "entry_zone_low",
        "entry_zone_high",
        "trend_stop_logic",
        "trend_take_profit_logic",
        "trend_recommendation",
        "trend_reasoning_summary",
        "trend_invalidators",
    ],
    "breakout": [
        "breakout_direction",
        "compression_score",
        "breakout_quality_score",
        "breakout_confirmation_score",
        "false_breakout_risk",
        "breakout_trigger_level",
        "breakout_invalidation_level",
        "breakout_followthrough_probability",
        "breakout_recommendation",
        "breakout_reasoning_summary",
        "breakout_invalidators",
    ],
    "meanrev": [
        "meanrev_direction",
        "oversold_score",
        "reversal_quality_score",
        "snapback_probability",
        "entry_zone_low",
        "entry_zone_high",
        "meanrev_stop_logic",
        "meanrev_take_profit_logic",
        "meanrev_recommendation",
        "meanrev_reasoning_summary",
        "meanrev_invalidators",
    ],
    "bull": [
        "bull_case_score",
        "bull_conviction",
        "bull_key_points",
        "bull_invalidators",
    ],
    "bear": [
        "bear_case_score",
        "bear_conviction",
        "bear_key_points",
        "bear_invalidators",
    ],
    "synth": [
        "setup_type",
        "composite_confidence",
        "directional_bias",
        "primary_thesis",
        "why_now",
        "key_trigger",
        "invalidation",
        "risk_reward_comment",
        "summary",
    ],
    "trade_planner": [
        "plan_type",
        "plan_action",
        "ticker",
        "side",
        "setup_type",
        "entry_zone_low",
        "entry_zone_high",
        "trigger_price",
        "trigger",
        "do_not_chase_above",
        "invalidation_price",
        "stop_loss",
        "stop_loss_price",
        "take_profit_1",
        "take_profit_2",
        "invalidation",
        "max_quote_size",
        "max_size_quote",
        "monitoring_rules",
        "risk_notes",
        "confidence",
        "planner_confidence",
        "planner_blockers",
        "must_not_trade_if",
        "why_plan_is_valid",
        "why_size_is_small",
        "reason",
        "no_plan_reason",
        "missing_fields",
        "hard_blockers",
        "soft_warnings",
        "would_be_starter_probe_if_relaxed",
        "pattern_alignment",
        "preferred_limit_price",
        "target_price_1",
        "target_price_2",
        "setup_expiry_minutes",
        "entry_reason",
        "why_not_market_order",
        "why_resting_limit_is_or_is_not_valid",
    ],
    "judge": [
        *FINAL_JUDGE_REQUIRED_KEYS,
        *FINAL_JUDGE_OPTIONAL_ORDERBOOK_ENTRY_KEYS,
        "ticker",
        "size_quote",
        "position_action",
        "soft_rule_override",
        "override_rules",
        "runner_plan",
        "entry_mode",
        "trigger",
        "post_trigger_objective_score",
        "trigger_wait_reason",
    ],
    "judge_legacy": [
        "decision",
        "ticker",
        "side",
        "strategy",
        "objective_score",
        "expected_edge_score",
        "risk_penalty",
        "cost_penalty",
        "drawdown_risk",
        "execution_friction_penalty",
        "confidence",
        "size_quote",
        "reasons",
        "must_reject_if",
        "setup_type",
        "position_action",
        "soft_rule_override",
        "override_rules",
        "runner_plan",
        "entry_mode",
        "trigger",
    ],
}


class StrategyEngine:
    def __init__(self):
        self.cfg = BotConfig()
        self.cfg.validate()

        self.client = CoinbaseClient()
        self.market = MarketDataService(self.client)
        self.state = StateStore()
        self.position_manager = PositionManager()
        self.reflection_store = TradeReflectionStore(
            max_records=getattr(self.cfg, "trade_reflection_max_records", 500)
        )
        self.pending_plan_store = PendingTradePlanStore(
            max_records=getattr(self.cfg, "pending_trade_plan_max_records", 200),
            ttl_hours=getattr(self.cfg, "pending_trade_plan_ttl_hours", 24),
            enabled=getattr(self.cfg, "enable_pending_trade_plans", True),
        )
        self.decision_outcome_store = DecisionOutcomeStore(
            max_records=getattr(self.cfg, "decision_outcome_max_records", 2000),
            enabled=getattr(self.cfg, "enable_decision_outcome_tracking", True),
            min_move_pct=getattr(self.cfg, "decision_outcome_min_move_pct", Decimal("0.025")),
            adverse_move_pct=getattr(self.cfg, "decision_outcome_adverse_move_pct", Decimal("0.020")),
        )
        self.shadow_outcome_store = _ShadowOutcomeAcceleratorStore(
            enabled=getattr(self.cfg, "enable_shadow_outcome_accelerator", True),
        )

        self.deepseek = DeepSeekClient(self.cfg) if bool(getattr(self.cfg, "enable_deepseek_preprocess", False)) else None
        self.openai = ResilientLLMClient(self.cfg)
        self.anthropic = AnthropicClient(self.cfg) if (bool(getattr(self.cfg, "enable_anthropic_fallback", False)) and self.cfg.anthropic_api_key) else None

        # Cost-aware model routing:
        # - nano for cheap gate/watch tasks
        # - mini for analyst modules
        # - GPT-5.5 for trade planning and final judge, only when the expensive judge gate allows it
        self.entry_gate_model = OPENAI_NANO_MODEL
        self.position_watch_model = OPENAI_NANO_MODEL
        self.analyst_model = getattr(self.cfg, "openai_analyst_model", DEFAULT_ANALYST_MODEL) or DEFAULT_ANALYST_MODEL
        self.judge_model = getattr(self.cfg, "openai_judge_model", DEFAULT_JUDGE_MODEL) or DEFAULT_JUDGE_MODEL
        self.trade_planner_model = getattr(self.cfg, "openai_trade_planner_model", DEFAULT_TRADE_PLANNER_MODEL) or DEFAULT_TRADE_PLANNER_MODEL
        self.execution_planner_model = getattr(self.cfg, "openai_execution_planner_model", DEFAULT_EXECUTION_PLANNER_MODEL) or DEFAULT_EXECUTION_PLANNER_MODEL
        self.execution_planner = ReadOnlyExecutionPlanner(
            cfg=self.cfg,
            llm_client=self.openai,
            log_writer=self._write_jsonl,
        )
        self.order_store = OrderStore(
            path="state/open_orders.json",
            log_path="logs/order_events.jsonl",
            max_orders=max(200, int(getattr(self.cfg, "order_store_max_records", 2000))),
        )
        self._phase_c43_new_live_orders_this_cycle = 0
        self.execution_outcome_tracker = ExecutionOutcomeTracker(
            log_path="logs/execution_outcomes.jsonl",
            enabled=True,
        )
        self.paper_limit_order_manager = PaperLimitOrderManager(
            cfg=self.cfg,
            order_store=self.order_store,
            execution_outcome_tracker=self.execution_outcome_tracker,
        )
        self.pending_order_intent_store = PendingOrderIntentStore(
            path="state/pending_order_intents.json",
            log_path="logs/pending_order_intents.jsonl",
            max_records=max(50, int(getattr(self.cfg, "paper_pending_intent_max_records", 500))),
            enabled=bool(getattr(self.cfg, "enable_paper_pending_order_intents", True)),
            max_replaced_per_ticker=int(getattr(self.cfg, "paper_pending_intent_max_replaced_per_ticker", 8)),
            final_retention_hours=int(getattr(self.cfg, "paper_pending_intent_final_retention_hours", 72)),
            dedupe_tolerance_pct=getattr(self.cfg, "paper_pending_intent_dedupe_tolerance_pct", Decimal("0.0025")),
            enable_dedupe_refresh=bool(getattr(self.cfg, "paper_pending_intent_enable_dedupe_refresh", True)),
        )

        # Planner/judge proposals must already fit the executable live rails.
        # C4.3 still replaces the proposal with deterministic dynamic sizing.
        self.min_trade_quote_usdc = Decimal(str(self.cfg.min_live_order_quote_usdc))
        self.max_trade_quote_usdc = Decimal(str(self.cfg.max_live_order_quote_usdc))
        self.position_epsilon_base = Decimal("0.00000001")
        self.runtime_state_file = Path("state/runtime.json")
        self.runtime_state_file.parent.mkdir(exist_ok=True)
        self.learning_context = load_runtime_learning_context()

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): StrategyEngine._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [StrategyEngine._json_safe(v) for v in value]
        return value

    def _write_jsonl(self, filename: str, payload: Dict[str, Any]) -> None:
        path = LOGS_DIR / filename
        safe_payload = self._json_safe(payload)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe_payload, ensure_ascii=False) + "\n")

    def _maybe_run_read_only_execution_planner(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
        position_action: Optional[Dict[str, Any]] = None,
        cycle_source: str = "strategy_engine",
    ) -> Optional[Dict[str, Any]]:
        """Run Phase A execution planning without changing execution behavior.

        This method is deliberately side-effect-light: it can write an audit log
        to logs/execution_plans.jsonl, but it never calls Coinbase and never
        mutates positions or open orders. Existing market execution/reduce/close
        paths continue to be controlled by the current judge + deterministic
        risk checks.
        """
        if not getattr(self.cfg, "enable_read_only_execution_planner", True):
            return None
        try:
            return self.execution_planner.plan(
                ticker=ticker,
                analysis=analysis,
                existing_position=existing_position,
                position_action=position_action,
                cycle_source=cycle_source,
            )
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "execution_planner",
                    "error_type": "read_only_execution_planner_failed",
                    "error": str(e),
                    "safety_policy": "non_fatal_phase_a_no_live_order_side_effects",
                },
            )
            return None

    def _build_recent_reflection_summary(self, ticker: str) -> Dict[str, Any]:
        if not getattr(self.cfg, "enable_trade_reflection_memory", True):
            return {
                "enabled": False,
                "count": 0,
                "ticker": ticker,
                "summary": "Trade reflection memory disabled by config.",
                "outcome_counts": {},
                "setup_outcomes": {},
                "avoid_conditions": [],
                "prefer_conditions": [],
                "recent_lessons": [],
            }
        try:
            return self.reflection_store.summarize_recent_reflections(
                ticker=ticker,
                limit=getattr(self.cfg, "trade_reflection_recent_limit", 12),
                min_samples_for_signal=getattr(self.cfg, "trade_reflection_min_samples_for_signal", 3),
            )
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "trade_reflection",
                    "error_type": "reflection_summary_failed",
                    "error": str(e),
                },
            )
            return {
                "enabled": True,
                "count": 0,
                "ticker": ticker,
                "summary": "Trade reflection memory unavailable; continuing safely without reflection context.",
                "outcome_counts": {},
                "setup_outcomes": {},
                "avoid_conditions": [],
                "prefer_conditions": [],
                "recent_lessons": [],
            }

    def _build_trade_learning_cycle_summary(self) -> Dict[str, Any]:
        """Build a compact read-only learning summary for cycle metadata/logs."""
        if not getattr(self.cfg, "enable_trade_reflection_memory", True):
            return {
                "enabled": False,
                "summary": "Trade reflection memory disabled by config.",
                "safety_policy": "No learning analytics used.",
            }
        try:
            analytics = self.reflection_store.analytics_summary(
                limit=getattr(self.cfg, "trade_reflection_analytics_limit", 200),
                min_samples_for_signal=getattr(self.cfg, "trade_reflection_min_samples_for_signal", 3),
            )
            compact = {
                "enabled": True,
                "count": analytics.get("count", 0),
                "overall": analytics.get("overall", {}),
                "candidate_avoid_contexts": analytics.get("candidate_avoid_contexts", [])[:5],
                "candidate_prefer_contexts": analytics.get("candidate_prefer_contexts", [])[:5],
                "surprise_flags": analytics.get("surprise_flags", [])[:5],
                "learning_policy": analytics.get("learning_policy"),
            }
            self._write_jsonl(
                "trade_reflections.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "event": "trade_learning_cycle_summary",
                    "summary": compact,
                },
            )
            return compact
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "module": "trade_reflection",
                    "error_type": "reflection_learning_cycle_summary_failed",
                    "error": str(e),
                },
            )
            return {
                "enabled": True,
                "count": 0,
                "summary": "Trade learning analytics unavailable; continuing safely.",
                "safety_policy": "Failure is non-fatal and never blocks trading.",
            }

    def _refresh_live_learning_context(self) -> Dict[str, Any]:
        try:
            report = run_live_learning_maintenance()
            runtime = report.get("runtime_context") if isinstance(report, dict) else {}
            if isinstance(runtime, dict):
                self.learning_context = runtime
            return self.learning_context
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "module": "live_learning_orchestrator",
                    "error_type": "live_learning_context_refresh_failed",
                    "error": str(e),
                    "safety_policy": "fail_open_for_analysis_context_no_parameter_mutation",
                },
            )
            self.learning_context = load_runtime_learning_context()
            return self.learning_context

    def _inject_neural_shadow_context(self, ticker: str, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        decision_context = feature_pack.setdefault("decision_context", {})
        try:
            decision_context["neural_shadow_policy"] = build_shadow_context(
                feature_pack,
                ticker=ticker,
                enabled=bool(getattr(self.cfg, "neural_shadow_policy_enabled", True)),
                execution_allowed=bool(getattr(self.cfg, "neural_shadow_policy_execution_allowed", False)),
                agreement_required=bool(getattr(self.cfg, "neural_shadow_policy_agreement_required", False)),
                model_path=getattr(self.cfg, "neural_shadow_policy_model_path", "state/neural_shadow_policy.json"),
                min_confidence=float(getattr(self.cfg, "neural_shadow_policy_min_confidence", Decimal("0.65"))),
            )
        except Exception as e:
            decision_context["neural_shadow_policy"] = {
                "enabled": bool(getattr(self.cfg, "neural_shadow_policy_enabled", True)),
                "execution_allowed": False,
                "model_available": False,
                "prediction": "unavailable",
                "confidence": 0.0,
                "top_reasons": [],
                "error": str(e),
                "safety_policy": "soft_context_only_no_order_authority",
            }
        return feature_pack

    def _inject_bounded_exploration_context(self, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        decision_context = feature_pack.setdefault("decision_context", {})
        decision_context["live_order_size_policy"] = live_order_size_policy_report(self.cfg)
        decision_context["bounded_exploration"] = {
            **bounded_exploration_report(self.cfg),
            "soft_context_only": True,
            "does_not_override_hard_risk": True,
            "does_not_allow_market_orders": True,
        }
        return feature_pack

    def _load_cached_product_rules_for_ticker(self, ticker: str) -> Dict[str, Any]:
        cache = getattr(self, "_product_rules_report_cache", None)
        if cache is None:
            cache = load_product_rules_cache()
            setattr(self, "_product_rules_report_cache", cache)
        value = cache.get(str(ticker or "").upper())
        return value if isinstance(value, dict) else {}

    def _read_only_product_rules_for_ticker(self, ticker: str, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        existing = self._feature_pack_exchange_rules(feature_pack)
        if existing:
            return existing
        cached = self._load_cached_product_rules_for_ticker(ticker)
        if cached:
            return cached
        memory = getattr(self, "_runtime_product_rules_cache", None)
        if memory is None:
            memory = {}
            setattr(self, "_runtime_product_rules_cache", memory)
        norm = str(ticker or "").upper().replace("/", "-")
        if norm in memory:
            return memory[norm]
        if self.client is not None and hasattr(self.client, "get_product"):
            try:
                product = self.client.get_product(norm)
                if isinstance(product, dict):
                    rules = product.get("product") if isinstance(product.get("product"), dict) else product
                    memory[norm] = rules
                    return rules
            except Exception as exc:
                feature_pack.setdefault("decision_context", {})["product_rule_lookup_error"] = {
                    "ticker": norm,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "read_only": True,
                }
        return {}

    def _entry_context_quote_and_price(self, ticker: str, feature_pack: Dict[str, Any]) -> Tuple[Decimal, Decimal]:
        market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
        orderbook = self._feature_pack_orderbook_context(feature_pack)
        risk_context = feature_pack.get("risk_context") if isinstance(feature_pack.get("risk_context"), dict) else {}
        default_quote = min(
            self.max_trade_quote_usdc,
            self._to_decimal(getattr(self.cfg, "phase_c_max_order_quote", self.max_trade_quote_usdc), str(self.max_trade_quote_usdc)),
            self._to_decimal(getattr(self.cfg, "default_quote_size_usdc", "50"), "50"),
            self._to_decimal(risk_context.get("available_quote_balance"), str(self.max_trade_quote_usdc)),
        )
        if default_quote <= Decimal("0"):
            default_quote = min(self.max_trade_quote_usdc, Decimal("50"))
        limit_price = self._to_decimal(
            orderbook.get("best_bid")
            or orderbook.get("mid_price")
            or market.get("mid_price")
            or market.get("last_price"),
            "0",
        )
        return default_quote, limit_price

    def _inject_execution_context(self, ticker: str, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        decision_context = feature_pack.setdefault("decision_context", {})
        rules = self._read_only_product_rules_for_ticker(ticker, feature_pack)
        product_rules = canonical_product_rules(ticker, rules)
        feature_pack["product_rules"] = product_rules
        feature_pack["exchange_rules"] = product_rules
        decision_context["product_rules"] = product_rules
        decision_context["precision_context_available"] = bool(product_rules.get("precision_context_available"))
        recent_rejections = recent_rejections_for_context(root=".", ticker=ticker, limit=5)
        decision_context["recent_exchange_rejections"] = recent_rejections
        if recent_rejections:
            decision_context["last_failed_submit_reason"] = recent_rejections[-1].get("reject_reason")
        quote, limit_price = self._entry_context_quote_and_price(ticker, feature_pack)
        feasibility = execution_feasibility_context(
            ticker,
            quote,
            limit_price,
            product_rules,
            max_quote_size=getattr(self.cfg, "phase_c_max_order_quote", self.max_trade_quote_usdc),
        )
        decision_context["execution_feasibility"] = feasibility
        feature_pack["execution_feasibility"] = feasibility
        return feature_pack

    def _inject_market_intelligence_context(self, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return inject_market_intelligence_feature_pack(feature_pack, Path("."))
        except Exception as e:
            decision_context = feature_pack.setdefault("decision_context", {})
            external = decision_context.setdefault("external_context", {})
            external["market_intelligence"] = {
                "available": False,
                "stale": True,
                "summary": {
                    "liquidity_regime": "unknown",
                    "network_regime": "unknown",
                    "crowd_regime": "unknown",
                    "risk_warnings": [f"market_intelligence_context_unavailable:{e}"],
                    "positive_context": [],
                },
                "can_authorize_execution": False,
                "can_block_execution": False,
                "can_mutate_parameters": False,
            }
            return feature_pack


    def _decision_outcome_horizons(self) -> List[int]:
        raw = getattr(self.cfg, "decision_outcome_horizons_hours", [4, 12, 24])
        if isinstance(raw, str):
            parts = [p.strip() for p in raw.split(",") if p.strip()]
        else:
            parts = list(raw or [])
        horizons: List[int] = []
        for part in parts:
            try:
                value = int(part)
            except Exception:
                continue
            if value > 0 and value not in horizons:
                horizons.append(value)
        return horizons or [4, 12, 24]

    def _build_decision_outcome_summary(self, ticker: str) -> Dict[str, Any]:
        if not getattr(self.cfg, "enable_decision_outcome_tracking", True):
            return {
                "enabled": False,
                "ticker": ticker,
                "count": 0,
                "summary": "Decision outcome tracking disabled by config.",
                "learning_policy": "No decision outcome context used.",
            }
        try:
            return self.decision_outcome_store.summary(
                ticker=ticker,
                limit=getattr(self.cfg, "decision_outcome_summary_limit", 100),
            )
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "decision_outcome_tracker",
                    "error_type": "decision_outcome_summary_failed",
                    "error": str(e),
                },
            )
            return {
                "enabled": True,
                "ticker": ticker,
                "count": 0,
                "summary": "Decision outcome context unavailable; continuing safely.",
                "learning_policy": "Failure is non-fatal and never blocks trading.",
            }

    def _record_decision_outcome_snapshot(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        cycle_result: Optional[Dict[str, Any]] = None,
        feature_pack: Optional[Dict[str, Any]] = None,
        source: str = "strategy_engine",
    ) -> List[Dict[str, Any]]:
        if not getattr(self.cfg, "enable_decision_outcome_tracking", True):
            return []
        try:
            added = self.decision_outcome_store.record_analysis_decision(
                ticker=ticker,
                analysis=analysis or {},
                cycle_result=cycle_result or {},
                feature_pack=feature_pack or (analysis or {}).get("feature_pack") or {},
                horizons_hours=self._decision_outcome_horizons(),
            )
            if added:
                self._write_jsonl(
                    "decision_outcomes.jsonl",
                    {
                        "generated_at": self._now_iso(),
                        "event": "decision_outcome_snapshots_stored_by_engine",
                        "ticker": ticker,
                        "source": source,
                        "count": len(added),
                    },
                )
            return added
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "decision_outcome_tracker",
                    "error_type": "decision_outcome_snapshot_failed",
                    "error": str(e),
                },
            )
            return []

    def _evaluate_due_decision_outcomes(self, feature_packs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        if not getattr(self.cfg, "enable_decision_outcome_tracking", True):
            return {
                "enabled": False,
                "resolved_count": 0,
                "summary": "Decision outcome tracking disabled by config.",
            }
        try:
            resolved = self.decision_outcome_store.evaluate_due(feature_packs=feature_packs)
            summary = self.decision_outcome_store.summary(
                limit=getattr(self.cfg, "decision_outcome_summary_limit", 100),
            )
            compact = {
                "enabled": True,
                "resolved_count": len(resolved),
                "overall": summary.get("overall", {}),
                "missed_opportunities": summary.get("missed_opportunities", [])[:5],
                "false_positive_plans": summary.get("false_positive_plans", [])[:5],
                "correct_avoids": summary.get("correct_avoids", [])[:5],
                "learning_policy": summary.get("learning_policy"),
            }
            if resolved:
                self._write_jsonl(
                    "decision_outcomes.jsonl",
                    {
                        "generated_at": self._now_iso(),
                        "event": "decision_outcomes_resolved_by_engine",
                        "count": len(resolved),
                    },
                )
            return compact
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "module": "decision_outcome_tracker",
                    "error_type": "decision_outcome_evaluation_failed",
                    "error": str(e),
                },
            )
            return {
                "enabled": True,
                "resolved_count": 0,
                "summary": "Decision outcome evaluation failed safely; continuing.",
                "learning_policy": "Failure is non-fatal and never blocks trading.",
            }

    def _record_shadow_decision(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        cycle_result: Optional[Dict[str, Any]] = None,
        feature_pack: Optional[Dict[str, Any]] = None,
        source: str = "strategy_engine",
    ) -> None:
        """Record a shadow decision for the Shadow Outcome Accelerator.

        Fail-open: errors are logged but never propagate to the trading flow.
        No Coinbase calls. No live orders. No parameter mutation.
        """
        if not getattr(self.cfg, "enable_shadow_outcome_accelerator", True):
            return
        try:
            self.shadow_outcome_store.record_decision(
                ticker=ticker,
                analysis=analysis or {},
                cycle_result=cycle_result or {},
                feature_pack=feature_pack or (analysis or {}).get("feature_pack") or {},
            )
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "shadow_outcome_accelerator",
                    "error_type": "shadow_decision_record_failed",
                    "error": str(e),
                    "source": source,
                },
            )

    def _evaluate_due_shadow_outcomes(self, feature_packs: Dict[str, Dict[str, Any]]) -> None:
        """Evaluate pending shadow outcome slots using local feature_pack data.

        Fail-open: errors are logged but never propagate to the trading flow.
        No Coinbase calls. No live orders. No parameter mutation.
        """
        if not getattr(self.cfg, "enable_shadow_outcome_accelerator", True):
            return
        try:
            self.shadow_outcome_store.evaluate_due(feature_packs=feature_packs)
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "module": "shadow_outcome_accelerator",
                    "error_type": "shadow_outcome_evaluation_failed",
                    "error": str(e),
                },
            )

    def _record_trade_reflection(
        self,
        *,
        ticker: str,
        position_before: Dict[str, Any],
        closed_position: Optional[Dict[str, Any]] = None,
        action: Optional[Dict[str, Any]] = None,
        feature_pack: Optional[Dict[str, Any]] = None,
        chart_patterns: Optional[Dict[str, Any]] = None,
        trade_plan: Optional[Dict[str, Any]] = None,
        judge: Optional[Dict[str, Any]] = None,
        execution_record: Optional[Dict[str, Any]] = None,
        realized_pnl: Any = None,
        exit_price: Any = None,
        source: str = "strategy_engine",
    ) -> Optional[Dict[str, Any]]:
        if not getattr(self.cfg, "enable_trade_reflection_memory", True):
            return None
        try:
            reflection = build_trade_reflection_input(
                ticker=ticker,
                position_before=position_before or {},
                closed_position=closed_position or {},
                action=action or {},
                feature_pack=feature_pack or {},
                chart_patterns=chart_patterns or {},
                trade_plan=trade_plan or {},
                judge=judge or {},
                execution_record=execution_record or {},
                realized_pnl=realized_pnl,
                exit_price=exit_price,
                source=source,
            )
            saved = self.reflection_store.append(reflection)
            self._write_jsonl(
                "trade_reflections.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "status": "stored",
                    "reflection": saved,
                },
            )
            return saved
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "trade_reflection",
                    "error_type": "reflection_store_failed",
                    "error": str(e),
                },
            )
            return None


    def _build_pending_trade_plan_context(
        self,
        ticker: str,
        feature_pack: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not getattr(self.cfg, "enable_pending_trade_plans", True):
            ctx = build_default_pending_context(ticker, reason="pending_trade_plans_disabled")
            ctx["enabled"] = False
            return ctx
        try:
            return self.pending_plan_store.evaluate_ticker(
                ticker=ticker,
                feature_pack=feature_pack or {},
                max_chase_distance_pct=getattr(self.cfg, "pending_trade_plan_max_chase_distance_pct", Decimal("0.0200")),
            )
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "pending_trade_plans",
                    "error_type": "pending_plan_evaluation_failed",
                    "error": str(e),
                },
            )
            return build_default_pending_context(ticker, reason="pending_plan_evaluation_failed_continue_without_plan")

    def _maybe_store_pending_trade_plan(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        execution: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not getattr(self.cfg, "enable_pending_trade_plans", True):
            return None
        if not isinstance(analysis, dict):
            return None

        trade_plan = analysis.get("trade_plan") or {}
        judge = analysis.get("judge") or {}
        decision = str(judge.get("decision", "wait")).strip().lower()
        side = str(judge.get("side", "NONE")).strip().upper()
        if decision == "approve_trade" or side == "BUY":
            return None

        if execution and str(execution.get("status", "")).lower() in {"executed", "paper_executed", "live_executed"}:
            return None

        action = str(trade_plan.get("plan_action", "no_plan")).strip().lower()
        if action not in {"prepare_buy", "prepare_reclaim", "prepare_breakout", "prepare_mean_reversion"}:
            # Cancel stale active plan if the latest fresh full analysis says there is no plan.
            if action == "no_plan":
                try:
                    self.pending_plan_store.cancel_plan(ticker, reason="fresh_analysis_returned_no_plan")
                except Exception:
                    pass
            return None

        confidence = int(float(trade_plan.get("confidence") or 0))
        min_conf = int(getattr(self.cfg, "pending_trade_plan_min_confidence", 60))
        if confidence < min_conf:
            return None

        try:
            stored = self.pending_plan_store.store_plan(
                ticker=ticker,
                trade_plan=trade_plan,
                judge=judge,
                chart_patterns=analysis.get("chart_patterns") or {},
                recent_reflections=analysis.get("recent_reflections") or {},
                source="strategy_engine_full_analysis",
            )
            if stored:
                self._write_jsonl(
                    "pending_trade_plans.jsonl",
                    {
                        "generated_at": self._now_iso(),
                        "ticker": ticker,
                        "event": "stored_pending_trade_plan",
                        "plan_id": stored.get("plan_id"),
                        "plan_action": (stored.get("trade_plan") or {}).get("plan_action"),
                        "expires_at": stored.get("expires_at"),
                        "safety_policy": stored.get("safety_policy"),
                    },
                )
            return stored
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "pending_trade_plans",
                    "error_type": "pending_plan_store_failed",
                    "error": str(e),
                },
            )
            return None

    def _apply_pending_plan_to_prefilter(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        prefilter: Dict[str, Any],
    ) -> Dict[str, Any]:
        pending_ctx = ((feature_pack or {}).get("decision_context") or {}).get("pending_trade_plan") or {}
        if not isinstance(prefilter, dict) or not isinstance(pending_ctx, dict):
            return prefilter

        prefilter.setdefault("reasons", [])
        prefilter.setdefault("warnings", [])
        if pending_ctx.get("has_active_plan"):
            prefilter["reasons"].append("pending_trade_plan_active_for_ticker")

        if pending_ctx.get("should_force_full_analysis") or pending_ctx.get("trigger_ready"):
            prefilter["prefilter_decision"] = "consider_high"
            prefilter["prefilter_score"] = max(int(prefilter.get("prefilter_score", 0)), int(getattr(self.cfg, "pending_trade_plan_trigger_score", 88)))
            prefilter["setup_guess"] = (pending_ctx.get("plan") or {}).get("trade_plan", {}).get("setup_type", prefilter.get("setup_guess", "unclear"))
            prefilter["reasons"].append("pending_trade_plan_trigger_ready_promoted_for_fresh_full_analysis")
            prefilter["warnings"].append("pending_plan_trigger_is_not_execution_permission_requires_new_judge_and_risk_check")
        return prefilter

    def _build_pending_order_intent_context(
        self,
        ticker: str,
    ) -> Dict[str, Any]:
        if not bool(getattr(self.cfg, "enable_paper_pending_order_intents", True)):
            return {
                "enabled": False,
                "ticker": str(ticker or "").upper(),
                "has_active_intent": False,
                "trigger_ready": False,
                "should_force_full_analysis": False,
                "status": "disabled",
                "reason": "paper_pending_order_intents_disabled",
                "safety_policy": "pending_intent_context_never_authorizes_execution",
            }
        try:
            return self.pending_order_intent_store.context_for_ticker(ticker)
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "paper_pending_order_intent_context",
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "safety_policy": "non_fatal_phase_b7_no_live_order_side_effects",
                },
            )
            return {
                "enabled": True,
                "ticker": str(ticker or "").upper(),
                "has_active_intent": False,
                "trigger_ready": False,
                "should_force_full_analysis": False,
                "status": "error",
                "reason": "pending_order_intent_context_failed_continue_without_promotion",
                "safety_policy": "pending_intent_context_never_authorizes_execution",
            }

    def _apply_pending_order_intent_to_prefilter(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        prefilter: Dict[str, Any],
    ) -> Dict[str, Any]:
        ctx = ((feature_pack or {}).get("decision_context") or {}).get("pending_order_intent") or {}
        if not isinstance(prefilter, dict) or not isinstance(ctx, dict):
            return prefilter

        prefilter.setdefault("reasons", [])
        prefilter.setdefault("warnings", [])
        if ctx.get("has_active_intent"):
            prefilter["reasons"].append("paper_pending_order_intent_active_for_ticker")

        if ctx.get("should_force_full_analysis") or ctx.get("trigger_ready"):
            prefilter["prefilter_decision"] = "consider_high"
            prefilter["prefilter_score"] = max(
                int(prefilter.get("prefilter_score", 0)),
                int(getattr(self.cfg, "pending_trade_plan_trigger_score", 88)),
            )
            prefilter["setup_guess"] = ctx.get("setup_type") or prefilter.get("setup_guess", "unclear")
            prefilter["reasons"].append("paper_pending_order_intent_needs_fresh_analysis_promoted")
            prefilter["warnings"].append("paper_pending_order_intent_is_not_execution_permission_requires_new_judge_and_risk_check")
        return prefilter

    def _log_error(self, ticker: str, error: Exception) -> Dict[str, Any]:
        payload = {
            "ticker": ticker,
            "error": str(error),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_jsonl("errors.jsonl", payload)
        return payload

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


    def _load_runtime_state(self) -> Dict[str, Any]:
        try:
            if not self.runtime_state_file.exists():
                return {}
            raw = self.runtime_state_file.read_text(encoding="utf-8").strip()
            if not raw:
                return {}
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_runtime_state(self, payload: Dict[str, Any]) -> None:
        try:
            from bot.atomic_io import atomic_write_json

            atomic_write_json(self.runtime_state_file, self._json_safe(payload), sort_keys=False)
        except Exception:
            pass

    def _get_watch_memory(self) -> Dict[str, Any]:
        state = self._load_runtime_state()
        memory = state.get("watch_memory", {})
        return memory if isinstance(memory, dict) else {}

    def _update_watch_memory(
        self,
        ticker: str,
        prefilter: Dict[str, Any],
        entry_gate: Dict[str, Any],
    ) -> None:
        state = self._load_runtime_state()
        memory = state.get("watch_memory", {})
        if not isinstance(memory, dict):
            memory = {}

        current = memory.get(ticker, {})
        if not isinstance(current, dict):
            current = {}

        decision = str(entry_gate.get("decision", "skip")).lower()
        pre_score = int(prefilter.get("prefilter_score", 0))
        setup_guess = str(prefilter.get("setup_guess", "unclear")).lower()
        reasons = [str(x) for x in entry_gate.get("reasons", [])]

        constructive_watch = (
            decision == "watch"
            and (
                pre_score >= 35
                or setup_guess in {"trend_continuation", "reclaim_reversal"}
                or any("compression" in r for r in reasons)
            )
        )

        if constructive_watch:
            consecutive = int(current.get("consecutive_constructive_watches", 0)) + 1
        elif decision in {"analyze", "priority_analyze"}:
            consecutive = 0
        else:
            consecutive = 0

        current.update({
            "ticker": ticker,
            "last_gate_decision": decision,
            "last_prefilter_score": pre_score,
            "last_setup_guess": setup_guess,
            "last_updated_at": self._now_iso(),
            "consecutive_constructive_watches": consecutive,
        })
        memory[ticker] = current
        state["watch_memory"] = memory
        self._save_runtime_state(state)

    def _build_market_breadth_context(
        self,
        feature_packs: Dict[str, Dict[str, Any]],
        tickers: List[str],
    ) -> Dict[str, Any]:
        constructive_count = 0
        compression_pressure_count = 0
        breakout_ready_count = 0
        tickers_considered = 0

        for ticker in tickers:
            feature_pack = feature_packs.get(ticker)
            if not isinstance(feature_pack, dict):
                continue

            tickers_considered += 1
            indicators = feature_pack.get("indicators", {})
            micro = feature_pack.get("microstructure", {})
            structure = feature_pack.get("structure", {})
            market = feature_pack.get("market", {})

            i15 = indicators.get("15m", {})
            i1h = indicators.get("1h", {})
            price = self._to_float(market.get("mid_price"), 0.0)
            ema20_15m = self._to_float(i15.get("ema_20"), 0.0)
            donch_low_1h = self._to_float(i1h.get("donchian_20_low"), 0.0)
            donch_high_1h = self._to_float(i1h.get("donchian_20_high"), 0.0)
            vol_15m = self._to_float(micro.get("15m", {}).get("volume_vs_avg"), 0.0)
            vol_1h = self._to_float(micro.get("1h", {}).get("volume_vs_avg"), 0.0)

            higher_lows_1h = bool(structure.get("higher_lows_1h", False))
            higher_highs_1h = bool(structure.get("higher_highs_1h", False))
            compression_detected = bool(structure.get("compression_detected", False))

            constructive = (higher_lows_1h or higher_highs_1h) and ema20_15m > 0 and price >= ema20_15m
            if constructive:
                constructive_count += 1

            range_pos = 0.5
            if donch_high_1h > donch_low_1h > 0 and price > 0:
                width = max(donch_high_1h - donch_low_1h, 1e-9)
                range_pos = (price - donch_low_1h) / width

            volume_ok = vol_15m >= 0.9 or vol_1h >= 0.85
            pressure = compression_detected and range_pos >= 0.60 and volume_ok
            breakout_ready = constructive and range_pos >= 0.68 and volume_ok

            if pressure:
                compression_pressure_count += 1
            if breakout_ready:
                breakout_ready_count += 1

        min_tickers = max(1, int(getattr(self.cfg, "breadth_relaxation_min_tickers", 3)))
        risk_on = bool(
            getattr(self.cfg, "enable_market_breadth_relaxation", True)
            and constructive_count >= min_tickers
            and (compression_pressure_count >= 2 or breakout_ready_count >= 2)
        )

        return {
            "risk_on": risk_on,
            "tickers_considered": tickers_considered,
            "constructive_count": constructive_count,
            "compression_pressure_count": compression_pressure_count,
            "breakout_ready_count": breakout_ready_count,
        }

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        ticker = str(ticker or "").upper().strip()
        if not ticker or "-" not in ticker:
            raise ValueError("ticker moet formaat BASE-QUOTE hebben")
        return ticker

    def _closed_position_has_unmanaged_legacy_inventory(
        self,
        existing_position: Optional[Dict[str, Any]],
        live_base_size: Decimal,
    ) -> bool:
        """Return True when live base should not be re-imported as bot-managed.

        Scenario this protects against:
        - user/legacy inventory existed before a bot trade;
        - the bot buys an additional bot-managed position;
        - the bot later closes only the bot-managed part;
        - Coinbase still shows the pre-existing legacy inventory;
        - inventory sync must NOT reopen that legacy inventory as a new bot position.

        This is intentionally conservative: it only skips when the local position is
        closed, bot-managed base is zero, and the live balance is explained by the
        recorded baseline/legacy inventory.
        """
        if not existing_position:
            return False
        if str(existing_position.get("status", "")).strip().lower() == "open":
            return False

        bot_managed_base = self._to_decimal(
            existing_position.get("bot_managed_base"),
            str(existing_position.get("position_size_base", "0")),
        )
        if bot_managed_base > self.position_epsilon_base:
            return False

        baseline_inventory_base = self._to_decimal(existing_position.get("baseline_inventory_base"), "0")
        legacy_inventory_base = self._to_decimal(existing_position.get("legacy_inventory_base"), "0")
        known_unmanaged_base = max(baseline_inventory_base, legacy_inventory_base)

        if known_unmanaged_base <= self.position_epsilon_base:
            return False

        return live_base_size <= known_unmanaged_base + self.position_epsilon_base

    def _build_inventory_sync_plan_snapshot(
        self,
        ticker: str,
        entry_price: Decimal,
        current_price: Decimal,
        live_base_size: Decimal,
    ) -> Dict[str, Any]:
        return {
            "created_at": self._now_iso(),
            "ticker": ticker,
            "setup_type": "inventory_sync",
            "strategy": "inventory_sync",
            "judge_confidence": 0,
            "entry_gate_decision": "inventory_sync",
            "entry_gate_confidence": 100,
            "primary_thesis": "Lokale positie hersteld vanuit bestaande live exchange-holding.",
            "why_now": "De holding bestaat op Coinbase maar ontbrak of was gesloten in de lokale state, waardoor monitoring anders zou uitvallen.",
            "key_trigger": "Bestaande live inventory monitoren alsof dit een open spotpositie is.",
            "invalidation": "Geen synthetische entry-trigger; beheer volgt vanuit latere position reviews en live balance-sync.",
            "risk_reward_comment": "Deze positie is niet als nieuwe trade geopend maar uit live inventory gesynchroniseerd. Gebruik conservatief beheer.",
            "entry_mid_price": str(entry_price if entry_price > Decimal("0") else current_price),
            "live_inventory_base": str(live_base_size),
        }

    def _sync_exchange_inventory_positions(self) -> Dict[str, Any]:
        if not bool(getattr(self.cfg, "enable_exchange_inventory_sync", False)):
            return {
                "enabled": False,
                "reason": "exchange_inventory_sync_disabled_requires_explicit_authority",
                "synced": [],
                "closed": [],
                "skipped_dust": [],
                "skipped_legacy": [],
                "errors": [],
                "coinbase_call_attempted": False,
                "state_write_performed": False,
            }

        synced: List[str] = []
        closed: List[str] = []
        skipped_dust: List[Dict[str, Any]] = []
        skipped_legacy: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        try:
            accounts_payload = self.client.get_accounts()
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "scope": "inventory_sync",
                    "error": str(e),
                },
            )
            return {"synced": [], "closed": [], "skipped_dust": [], "skipped_legacy": [], "errors": [str(e)]}

        account_map: Dict[str, Dict[str, Any]] = {}
        for acc in accounts_payload.get("accounts", []):
            symbol = str(acc.get("currency", "")).upper().strip()
            if symbol:
                account_map[symbol] = acc

        for ticker in self.cfg.allowed_tickers:
            try:
                ticker = self._normalize_ticker(ticker)
                base_symbol, _quote_symbol = ticker.split("-", 1)
                base_acc = account_map.get(base_symbol, {})
                live_base_size = self._to_decimal(
                    (base_acc or {}).get("available_balance", {}).get("value"),
                    "0",
                )
                existing_position = self.state.get_position(ticker)

                is_existing_open = bool(existing_position) and str(existing_position.get("status", "")).lower() == "open"
                is_synthetic_inventory = bool(existing_position) and (
                    str(existing_position.get("entry_reason", "")).strip().lower() == "inventory_sync"
                    or bool(existing_position.get("synced_from_exchange", False))
                )

                if live_base_size <= self.position_epsilon_base:
                    if is_existing_open and is_synthetic_inventory:
                        close_price = existing_position.get("entry_price", "0") if existing_position else "0"
                        try:
                            snap = self.client.get_public_ticker(ticker)
                            bid = self._to_decimal(snap.get("best_bid"), "0")
                            ask = self._to_decimal(snap.get("best_ask"), "0")
                            if bid > 0 and ask > 0:
                                close_price = str((bid + ask) / Decimal("2"))
                        except Exception:
                            pass
                        closed_position = self.state.mark_position_closed(
                            ticker=ticker,
                            close_reason="inventory_sync_no_live_base",
                            close_price=str(close_price),
                            realized_pnl=None,
                        )
                        if str(closed_position.get("status") or "").strip().lower() == "closed":
                            closed.append(ticker)
                        else:
                            synced.append(ticker)
                    continue

                if is_existing_open and not is_synthetic_inventory:
                    continue

                ticker_snapshot = self.client.get_public_ticker(ticker)
                best_bid = self._to_decimal(ticker_snapshot.get("best_bid"), "0")
                best_ask = self._to_decimal(ticker_snapshot.get("best_ask"), "0")
                current_price = (
                    (best_bid + best_ask) / Decimal("2")
                    if best_bid > 0 and best_ask > 0
                    else self._to_decimal(existing_position.get("entry_price") if existing_position else "0", "0")
                )

                live_quote_notional = live_base_size * current_price if current_price > Decimal("0") else Decimal("0")

                if self._closed_position_has_unmanaged_legacy_inventory(existing_position, live_base_size):
                    skipped_legacy.append({
                        "ticker": ticker,
                        "reason": "closed_legacy_inventory_not_reimported_as_bot_managed",
                        "live_base_size": str(live_base_size),
                        "reference_price": str(current_price),
                        "live_quote_notional": str(live_quote_notional),
                        "baseline_inventory_base": str((existing_position or {}).get("baseline_inventory_base", "0")),
                        "legacy_inventory_base": str((existing_position or {}).get("legacy_inventory_base", "0")),
                    })
                    continue

                if Decimal("0") < live_quote_notional < self.min_trade_quote_usdc:
                    # Do not re-import tiny exchange residuals as active positions.
                    # They are below the practical Coinbase/order minimum for this bot
                    # and would otherwise keep consuming position-management reviews
                    # and expensive judge calls every cycle.
                    if is_existing_open and is_synthetic_inventory:
                        if self._should_skip_tiny_residual_close_for_phase_c43_pilot_review(
                            ticker=ticker,
                            position=existing_position,
                            live_base_size=live_base_size,
                            live_quote_notional=live_quote_notional,
                        ):
                            self._keep_phase_c43_pilot_position_open_for_governance_review(
                                ticker=ticker,
                                position=existing_position,
                                live_base_size=live_base_size,
                                live_quote_notional=live_quote_notional,
                                current_price=current_price,
                                note="inventory_sync_live_balance_refresh",
                            )
                            synced.append(ticker)
                            continue

                        closed_position = self.state.mark_position_closed_tiny_residual(
                            ticker=ticker,
                            close_reason="inventory_sync_live_notional_below_min_trade_quote",
                            close_price=str(current_price),
                            residual_base=str(live_base_size),
                            residual_quote=str(live_quote_notional),
                            extra={
                                "notes": "synced_from_live_exchange_inventory | inventory_sync_ignored_dust_below_min_trade_quote",
                                "monitoring_enabled": False,
                                "opened_via_strategy": False,
                                "synced_from_exchange": True,
                                "last_position_risk_state": "closed_dust_cleanup",
                            },
                        )
                        if str(closed_position.get("status") or "").strip().lower() == "closed":
                            closed.append(ticker)
                        else:
                            synced.append(ticker)
                    else:
                        skipped_dust.append({
                            "ticker": ticker,
                            "live_base_size": str(live_base_size),
                            "reference_price": str(current_price),
                            "live_quote_notional": str(live_quote_notional),
                            "min_trade_quote_usdc": str(self.min_trade_quote_usdc),
                        })
                    continue

                if is_existing_open and is_synthetic_inventory and existing_position:
                    # Refresh live balance/quote value without reinitializing the
                    # position plan. This preserves management state such as
                    # partial_take_profit_taken, trailing flags, highest price,
                    # and bot_managed_base. Without this, inventory sync can
                    # make the bot repeatedly take the same partial profit.
                    self._sync_local_position_to_live_balance(
                        ticker=ticker,
                        position=existing_position,
                        live_available_base=live_base_size,
                        current_price=current_price,
                        note="inventory_sync_live_balance_refresh",
                    )
                    synced.append(ticker)
                    continue

                extra = {
                    "notes": "synced_from_live_exchange_inventory",
                    "monitoring_enabled": True,
                    "opened_via_strategy": False,
                    "setup_type": "inventory_sync",
                    "invalidation_mode": "exchange_inventory_sync",
                    "position_plan_snapshot": self._build_inventory_sync_plan_snapshot(
                        ticker=ticker,
                        entry_price=self._to_decimal(existing_position.get("entry_price") if existing_position else "0", "0"),
                        current_price=current_price,
                        live_base_size=live_base_size,
                    ),
                }
                self.state.sync_live_inventory_position(
                    ticker=ticker,
                    live_base_size=str(live_base_size),
                    reference_price=str(current_price),
                    entry_reason="inventory_sync",
                    extra=extra,
                )
                synced.append(ticker)
            except Exception as e:
                errors.append({"ticker": ticker, "error": str(e)})
                self._write_jsonl(
                    "errors.jsonl",
                    {
                        "generated_at": self._now_iso(),
                        "ticker": ticker,
                        "scope": "inventory_sync",
                        "error": str(e),
                    },
                )

        self._write_jsonl(
            "inventory_sync.jsonl",
            {
                "generated_at": self._now_iso(),
                "synced": synced,
                "closed": closed,
                "skipped_dust": skipped_dust,
                "skipped_legacy": skipped_legacy,
                "errors": errors,
            },
        )
        return {"synced": synced, "closed": closed, "skipped_dust": skipped_dust, "skipped_legacy": skipped_legacy, "errors": errors}

    @staticmethod
    def _normalize_decision(judge: Dict[str, Any]) -> str:
        return str(judge.get("decision", "")).strip().lower()

    @staticmethod
    def _normalize_side(judge: Dict[str, Any]) -> str:
        return str(judge.get("side", "")).strip().upper()

    def _parse_size_quote(
        self,
        judge: Dict[str, Any],
        default_value: Optional[Decimal] = None,
    ) -> Decimal:
        if default_value is None:
            default_value = self.cfg.default_quote_size_usdc
        raw_size = judge.get("size_quote", default_value)
        return Decimal(str(raw_size))

    @staticmethod
    def _to_decimal(value: Any, default: str = "0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal(default)

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _quantize_quote(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    @staticmethod
    def _extract_score(value: Any, default: int = 0) -> int:
        try:
            score = float(value)
            if score <= 1:
                score *= 100.0
            return max(0, min(100, int(round(score))))
        except Exception:
            return default

    def _judge_summary(self, judge: Dict[str, Any]) -> Dict[str, Any]:
        try:
            size_quote = float(self._parse_size_quote(judge, Decimal("0")))
        except Exception:
            size_quote = 0.0

        return {
            "decision": self._normalize_decision(judge),
            "side": self._normalize_side(judge),
            "size_quote": size_quote,
            "strategy": judge.get("strategy"),
            "confidence": judge.get("confidence"),
            "setup_type": judge.get("setup_type"),
        }

    def _is_no_trade_decision(self, judge: Dict[str, Any]) -> bool:
        decision = self._normalize_decision(judge)
        side = self._normalize_side(judge)

        try:
            size_quote = self._parse_size_quote(judge, Decimal("0"))
        except (InvalidOperation, ValueError, TypeError):
            return False

        return decision in {"wait", "reject", "no_trade"} and side == "NONE" and size_quote == Decimal("0")

    def _build_risk_state(self, ticker: str) -> Dict[str, Any]:
        positions = self.state.get_positions()
        daily = self.state.get_daily_pnl()

        open_positions = [
            p for p in positions.values()
            if str(p.get("status", "open")).lower() == "open"
        ]

        total_open_quote_exposure = Decimal("0")
        largest_position_quote = Decimal("0")
        exposure_by_ticker: Dict[str, str] = {}

        for pos in open_positions:
            pos_ticker = str(pos.get("ticker", "")).upper().strip()
            pos_quote = self._to_decimal(pos.get("position_size_quote"), "0")
            total_open_quote_exposure += pos_quote
            if pos_quote > largest_position_quote:
                largest_position_quote = pos_quote
            if pos_ticker:
                exposure_by_ticker[pos_ticker] = str(pos_quote)

        daily_realized_pnl = Decimal(str(daily.get("realized_pnl", 0.0)))
        remaining_daily_loss_buffer = self.cfg.max_daily_loss_usdc + daily_realized_pnl

        return {
            "ticker": ticker,
            "cooldown_active": self.state.cooldown_active(ticker),
            "open_positions_count": len(open_positions),
            "daily_realized_pnl": float(daily_realized_pnl),
            "remaining_daily_loss_buffer_usdc": str(remaining_daily_loss_buffer),
            "max_open_positions": self.cfg.max_open_positions,
            "max_daily_loss_usdc": str(self.cfg.max_daily_loss_usdc),
            "default_quote_size_usdc": str(self.cfg.default_quote_size_usdc),
            "min_trade_quote_usdc": str(self.min_trade_quote_usdc),
            "max_trade_quote_usdc": str(self.max_trade_quote_usdc),
            "execution_mode": self.cfg.execution_mode,
            "open_positions_quote_exposure": str(total_open_quote_exposure),
            "largest_position_quote_usdc": str(largest_position_quote),
            "exposure_by_ticker": exposure_by_ticker,
            "positions": positions,
        }

    @staticmethod
    def _build_spot_constraints() -> Dict[str, Any]:
        return {
            "spot_only": True,
            "allow_naked_shorts": False,
            "allow_buy": True,
            "allow_sell_only_if_base_balance_gt_zero": True,
        }

    @staticmethod
    def _normalize_setup_type(raw_value: Any) -> str:
        value = str(raw_value or "").strip().lower()
        aliases = {
            "trend": "trend_continuation",
            "trend_continuation": "trend_continuation",
            "continuation": "trend_continuation",
            "momentum": "trend_continuation",
            "reclaim": "reclaim_reversal",
            "reversal": "reclaim_reversal",
            "reclaim_reversal": "reclaim_reversal",
            "mean_reversion": "mean_reversion",
            "meanrev": "mean_reversion",
            "mean reversion": "mean_reversion",
        }
        return aliases.get(value, "unclear")

    def _setup_type_cap(self, setup_type: Any) -> Decimal:
        normalized = self._normalize_setup_type(setup_type)
        if normalized == "trend_continuation":
            return Decimal("200")
        if normalized == "reclaim_reversal":
            return Decimal("120")
        if normalized == "mean_reversion":
            return Decimal("60")
        return Decimal("60")

    def _default_size_for_setup(self, setup_type: Any, confidence: Any) -> Decimal:
        normalized = self._normalize_setup_type(setup_type)
        conf = self._extract_score(confidence, 55)
        ratio = Decimal(str(max(0.0, min(1.0, (conf - 55) / 35.0))))

        if normalized == "trend_continuation":
            floor = Decimal("30")
            ceiling = Decimal("100")
        elif normalized == "reclaim_reversal":
            floor = Decimal("20")
            ceiling = Decimal("60")
        elif normalized == "mean_reversion":
            floor = Decimal("10")
            ceiling = Decimal("30")
        else:
            floor = Decimal("10")
            ceiling = Decimal("30")

        size = floor + ((ceiling - floor) * ratio)
        return self._quantize_quote(size)

    def _build_default_entry_gate(self, ticker: str, reason: str) -> Dict[str, Any]:
        return {
            "generated_at": self._now_iso(),
            "ticker": ticker,
            "decision": "analyze",
            "priority": "normal",
            "setup_type": "unclear",
            "confidence": 25,
            "reasons": [reason],
            "warnings": [],
        }

    def _normalize_entry_gate(self, ticker: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return self._build_default_entry_gate(ticker, "entry_gate_payload_not_dict")

        decision = str(payload.get("decision", "analyze")).strip().lower()
        if decision not in {"skip", "watch", "analyze", "priority_analyze"}:
            decision = "analyze"

        priority = str(payload.get("priority", "normal")).strip().lower()
        if priority not in {"low", "normal", "high"}:
            priority = "normal"

        try:
            confidence = int(float(payload.get("confidence", 25)))
        except Exception:
            confidence = 25
        confidence = max(0, min(100, confidence))

        reasons = payload.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = [str(reasons)]

        warnings = payload.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = [str(warnings)]

        setup_type = self._normalize_setup_type(payload.get("setup_type"))

        return {
            "generated_at": payload.get("generated_at", self._now_iso()),
            "ticker": payload.get("ticker", ticker),
            "decision": decision,
            "priority": priority,
            "setup_type": setup_type,
            "confidence": confidence,
            "reasons": [str(r) for r in reasons],
            "warnings": [str(w) for w in warnings],
        }

    def _normalize_position_watch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "decision": "watch_closer",
                "confidence": 0,
                "reasons": ["position_watch_payload_not_dict"],
                "warnings": ["position_watch_used_safe_fallback"],
            }

        decision = str(payload.get("decision", "watch_closer")).strip().lower()
        if decision not in {"hold_ok", "watch_closer", "tighten_risk", "escalate_full_review"}:
            decision = "watch_closer"

        try:
            confidence = int(float(payload.get("confidence", 0)))
        except Exception:
            confidence = 0
        confidence = max(0, min(100, confidence))

        reasons = payload.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = [str(reasons)]

        warnings = payload.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = [str(warnings)]

        return {
            "decision": decision,
            "confidence": confidence,
            "reasons": [str(r) for r in reasons],
            "warnings": [str(w) for w in warnings],
        }

    def _postfilter_entry_gate(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        deepseek_pack: Dict[str, Any],
        entry_gate: Dict[str, Any],
    ) -> Dict[str, Any]:
        market = feature_pack.get("market", {})
        micro = feature_pack.get("microstructure", {})
        indicators = feature_pack.get("indicators", {})
        structure = feature_pack.get("structure", {})
        regime_hints = deepseek_pack.get("regime_hints", {})

        price = self._to_float(market.get("mid_price"), 0.0)
        key_levels = regime_hints.get("key_levels", {}) if isinstance(regime_hints, dict) else {}
        range_low = self._to_float(key_levels.get("range_low"), 0.0)
        range_high = self._to_float(key_levels.get("range_high"), 0.0)

        volume_vs_avg_15m = self._to_float(micro.get("15m", {}).get("volume_vs_avg"), 0.0)
        volume_vs_avg_1h = self._to_float(micro.get("1h", {}).get("volume_vs_avg"), 0.0)
        latest_volume_15m = self._to_float(micro.get("15m", {}).get("latest_volume"), 0.0)
        avg_volume_15m = self._to_float(micro.get("15m", {}).get("avg_volume"), 0.0)

        rsi_15m = self._to_float(indicators.get("15m", {}).get("rsi_14"), 50.0)
        rsi_1h = self._to_float(indicators.get("1h", {}).get("rsi_14"), 50.0)
        rsi_4h = self._to_float(indicators.get("4h", {}).get("rsi_14"), 50.0)

        ema20_1h = self._to_float(indicators.get("1h", {}).get("ema_20"), 0.0)
        ema50_1h = self._to_float(indicators.get("1h", {}).get("ema_50"), 0.0)
        ema200_1h = self._to_float(indicators.get("1h", {}).get("ema_200"), 0.0)
        ema50_4h = self._to_float(indicators.get("4h", {}).get("ema_50"), 0.0)
        ema200_4h = self._to_float(indicators.get("4h", {}).get("ema_200"), 0.0)

        higher_lows_1h = bool(structure.get("higher_lows_1h", False))
        higher_highs_1h = bool(structure.get("higher_highs_1h", False))
        lower_highs_1h = bool(structure.get("lower_highs_1h", False))
        lower_lows_1h = bool(structure.get("lower_lows_1h", False))
        compression_detected = bool(structure.get("compression_detected", False))

        setup_type = self._normalize_setup_type(entry_gate.get("setup_type"))
        decision = str(entry_gate.get("decision", "analyze")).lower()
        breadth_risk_on = bool(
            feature_pack.get("decision_context", {}).get("market_breadth", {}).get("risk_on", False)
        )

        bullish_1h_alignment = ema20_1h > 0 and ema50_1h > 0 and ema20_1h >= ema50_1h
        price_above_fast_emas = (ema20_1h > 0 and price >= ema20_1h) or (ema50_1h > 0 and price >= ema50_1h)
        bearish_htf = (
            ema50_4h > 0 and ema200_4h > 0 and ema50_4h < ema200_4h
        ) or (
            ema20_1h > 0 and ema50_1h > 0 and ema20_1h < ema50_1h
        )

        constructive_short_term = (
            (higher_lows_1h or higher_highs_1h)
            and (volume_vs_avg_15m >= 0.9 or breadth_risk_on)
            and price_above_fast_emas
        )
        compression_with_pressure = (
            compression_detected
            and price_above_fast_emas
            and (higher_lows_1h or higher_highs_1h)
            and (volume_vs_avg_15m >= 0.95 or volume_vs_avg_1h >= 0.85 or breadth_risk_on)
        )

        if setup_type in {"trend_continuation", "reclaim_reversal"}:
            if decision == "watch" and (constructive_short_term or compression_with_pressure):
                entry_gate["decision"] = "analyze"
                entry_gate["priority"] = "normal"
                entry_gate["reasons"].append(
                    "postfilter_upgrade: constructive short-term structure deserves full analysis"
                )
                if breadth_risk_on:
                    entry_gate["reasons"].append("postfilter_note: market breadth supports tactical long attempts")

            if (
                decision == "analyze"
                and lower_highs_1h
                and lower_lows_1h
                and volume_vs_avg_15m < 0.8
                and volume_vs_avg_1h < 0.8
            ):
                entry_gate["decision"] = "watch"
                entry_gate["priority"] = "low"
                entry_gate["reasons"].append(
                    "postfilter_downgrade: weak follow-through despite nominal trend/reclaim label"
                )

            return entry_gate

        if setup_type != "mean_reversion":
            return entry_gate

        if not range_low or not range_high or range_high <= range_low:
            return entry_gate

        range_pos = (price - range_low) / max(range_high - range_low, 1e-9)
        near_support = range_pos <= 0.25
        very_near_support = range_pos <= 0.16
        mid_range = 0.35 <= range_pos <= 0.65

        oversold_enough = rsi_1h <= 38 or rsi_4h <= 35
        very_oversold = rsi_15m <= 28 or rsi_1h <= 32 or rsi_4h <= 33
        weak_volume = volume_vs_avg_15m < 0.9 and volume_vs_avg_1h < 0.7
        non_collapsing_volume = volume_vs_avg_15m >= 0.85 or volume_vs_avg_1h >= 0.65
        capitulation_like = avg_volume_15m > 0 and latest_volume_15m >= (avg_volume_15m * 1.8)
        no_stab = not higher_lows_1h and not higher_highs_1h

        if decision in {"analyze", "priority_analyze"} and mid_range and bearish_htf and weak_volume and not breadth_risk_on:
            entry_gate["decision"] = "watch"
            entry_gate["priority"] = "low"
            entry_gate["reasons"].append(
                "postfilter_downgrade: mean_reversion is mid-range with bearish HTF and weak volume"
            )

        if decision in {"analyze", "priority_analyze"} and (not near_support) and no_stab:
            entry_gate["decision"] = "watch"
            entry_gate["priority"] = "low"
            entry_gate["reasons"].append(
                "postfilter_downgrade: mean_reversion lacks support proximity and stabilization"
            )

        if decision == "watch":
            strong_mr_case = (
                near_support
                and oversold_enough
                and non_collapsing_volume
                and (higher_lows_1h or constructive_short_term or compression_detected)
            )
            aggressive_but_still_reasonable_mr_case = (
                very_near_support
                and very_oversold
                and capitulation_like
                and not mid_range
            )

            if strong_mr_case or aggressive_but_still_reasonable_mr_case:
                entry_gate["decision"] = "analyze"
                entry_gate["priority"] = "normal"
                entry_gate["reasons"].append(
                    "postfilter_upgrade: mean_reversion has enough support/oversold/stabilization evidence"
                )

        if decision == "analyze":
            if bearish_htf and lower_highs_1h and lower_lows_1h and weak_volume and not very_oversold and not breadth_risk_on:
                entry_gate["decision"] = "watch"
                entry_gate["priority"] = "low"
                entry_gate["reasons"].append(
                    "postfilter_downgrade: trend conflict too strong for mean_reversion analysis"
                )

        if entry_gate["decision"] == "analyze" and entry_gate.get("priority") == "high":
            entry_gate["priority"] = "normal"

        return entry_gate

    def _run_entry_gate(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        deepseek_pack: Dict[str, Any],
    ) -> Dict[str, Any]:
        gate_input = {
            "feature_pack": feature_pack,
            "deepseek_pack": deepseek_pack,
            "task": {
                "objective": "Filter duidelijk zinloze nieuwe entries weg en laat plausibele setups door.",
                "allowed_setup_types": [
                    "trend_continuation",
                    "reclaim_reversal",
                    "mean_reversion",
                ],
                "allowed_decisions": ["skip", "watch", "analyze", "priority_analyze"],
                "high_recall": True,
            },
        }

        try:
            gate_payload = self.openai.json_response(
                GPT_NANO_GATE_PROMPT,
                gate_input,
                model=self.entry_gate_model,
                ticker=ticker,
                stage="entry_gate",
                allowed_keys=MODULE_ALLOWED_KEYS["entry_gate"],
                require_all_keys=True,
                drop_unknown_keys=True,
            )
            normalized = self._normalize_entry_gate(ticker, gate_payload)
            normalized = self._postfilter_entry_gate(
                ticker=ticker,
                feature_pack=feature_pack,
                deepseek_pack=deepseek_pack,
                entry_gate=normalized,
            )
        except Exception as e:
            normalized = self._build_default_entry_gate(ticker, f"entry_gate_nano_fallback_after_error: {e}")
            normalized["warnings"].append(str(e))

        feature_pack["entry_gate"] = normalized
        feature_pack["risk_context"]["entry_gate"] = normalized
        return normalized

    def _build_skip_analysis_result(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        deepseek_pack: Dict[str, Any],
        entry_gate: Dict[str, Any],
    ) -> Dict[str, Any]:
        judge = {
            "decision": "wait",
            "ticker": ticker,
            "side": "NONE",
            "strategy": f"entry_gate_{entry_gate.get('decision', 'skip')}",
            "confidence": int(entry_gate.get("confidence", 0)),
            "size_quote": 0.0,
            "reasons": [
                "new_entry_filtered_by_deepseek_gate",
                *entry_gate.get("reasons", []),
            ],
            "must_reject_if": [],
        }

        result = {
            "ticker": ticker,
            "generated_at": self._now_iso(),
            "feature_pack": feature_pack,
            "deepseek_pack": deepseek_pack,
            "entry_gate": entry_gate,
            "regime": {"skipped": True, "reason": "entry_gate_filtered_new_entry"},
            "trend": {"skipped": True, "reason": "entry_gate_filtered_new_entry"},
            "breakout": {"skipped": True, "reason": "entry_gate_filtered_new_entry"},
            "meanrev": {"skipped": True, "reason": "entry_gate_filtered_new_entry"},
            "bull": {"skipped": True, "reason": "entry_gate_filtered_new_entry"},
            "bear": {"skipped": True, "reason": "entry_gate_filtered_new_entry"},
            "synth": {
                "skipped": True,
                "reason": "entry_gate_filtered_new_entry",
                "setup_type": entry_gate.get("setup_type", "unclear"),
                "composite_confidence": entry_gate.get("confidence", 0),
            },
            "judge": judge,
        }

        self._write_jsonl("analysis.jsonl", result)
        return result

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> int:
        mapping = {
            "15m": 15 * 60,
            "1h": 60 * 60,
            "4h": 4 * 60 * 60,
            "1d": 24 * 60 * 60,
        }
        return mapping.get(timeframe, 0)

    def _slice_to_closed_candles(
        self,
        timeframe: str,
        raw_context_tf: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool]:
        if not isinstance(raw_context_tf, dict):
            return raw_context_tf, False

        starts = raw_context_tf.get("starts", [])
        if not isinstance(starts, list) or not starts:
            return raw_context_tf, False

        interval = self._timeframe_to_seconds(timeframe)
        if interval <= 0:
            return raw_context_tf, False

        try:
            last_start = int(starts[-1])
        except Exception:
            return raw_context_tf, False

        now_ts = int(datetime.now(timezone.utc).timestamp())
        is_open_bar = (last_start + interval) > now_ts

        if not is_open_bar or len(starts) <= 1:
            return raw_context_tf, False

        sliced: Dict[str, Any] = {}
        for key, value in raw_context_tf.items():
            if isinstance(value, list):
                sliced[key] = value[:-1]
            else:
                sliced[key] = value

        return sliced, True

    @staticmethod
    def _mean(values: List[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _rebuild_raw_context_summary(self, raw_context_tf: Dict[str, Any]) -> Dict[str, Any]:
        closes = raw_context_tf.get("closes", [])
        highs = raw_context_tf.get("highs", [])
        lows = raw_context_tf.get("lows", [])
        volumes = raw_context_tf.get("volumes", [])

        if not closes:
            return raw_context_tf

        raw_context_tf["count"] = len(closes)
        raw_context_tf["latest_close"] = closes[-1]
        raw_context_tf["latest_volume"] = volumes[-1] if volumes else 0
        raw_context_tf["highest_in_slice"] = max(highs) if highs else closes[-1]
        raw_context_tf["lowest_in_slice"] = min(lows) if lows else closes[-1]

        returns: List[float] = []
        for i in range(1, len(closes)):
            prev_close = self._to_float(closes[i - 1], 0.0)
            cur_close = self._to_float(closes[i], 0.0)
            if prev_close > 0:
                returns.append((cur_close - prev_close) / prev_close)
            else:
                returns.append(0.0)

        raw_context_tf["returns"] = returns
        return raw_context_tf

    def _rebuild_microstructure_for_tf(self, raw_context_tf: Dict[str, Any]) -> Dict[str, Any]:
        closes = [self._to_float(v, 0.0) for v in raw_context_tf.get("closes", [])]
        highs = [self._to_float(v, 0.0) for v in raw_context_tf.get("highs", [])]
        lows = [self._to_float(v, 0.0) for v in raw_context_tf.get("lows", [])]
        volumes = [self._to_float(v, 0.0) for v in raw_context_tf.get("volumes", [])]

        if not closes or not highs or not lows:
            return {
                "up_closes": 0,
                "down_closes": 0,
                "net_close_direction": "flat",
                "recent_high": 0.0,
                "recent_low": 0.0,
                "range_pct": 0.0,
                "avg_volume": 0.0,
                "latest_volume": 0.0,
                "volume_vs_avg": 0.0,
            }

        window_bars = min(12, len(closes))
        recent_closes = closes[-window_bars:]
        recent_highs = highs[-window_bars:]
        recent_lows = lows[-window_bars:]

        up_closes = 0
        down_closes = 0
        for i in range(1, len(recent_closes)):
            if recent_closes[i] > recent_closes[i - 1]:
                up_closes += 1
            elif recent_closes[i] < recent_closes[i - 1]:
                down_closes += 1

        if up_closes > down_closes:
            net_close_direction = "up"
        elif down_closes > up_closes:
            net_close_direction = "down"
        else:
            net_close_direction = "flat"

        recent_high = max(recent_highs) if recent_highs else 0.0
        recent_low = min(recent_lows) if recent_lows else 0.0
        range_pct = ((recent_high - recent_low) / recent_low) if recent_low > 0 else 0.0

        avg_volume = self._mean(volumes)
        latest_volume = volumes[-1] if volumes else 0.0
        volume_vs_avg = (latest_volume / avg_volume) if avg_volume > 0 else 0.0

        return {
            "up_closes": up_closes,
            "down_closes": down_closes,
            "net_close_direction": net_close_direction,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "range_pct": range_pct,
            "avg_volume": avg_volume,
            "latest_volume": latest_volume,
            "volume_vs_avg": volume_vs_avg,
        }

    def _apply_closed_candle_sanitization(self, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        pack = deepcopy(feature_pack)
        raw_context = pack.get("raw_context", {})
        indicators = pack.get("indicators", {})
        microstructure = pack.get("microstructure", {})

        decision_context = pack.setdefault("decision_context", {})
        decision_context["closed_candle_sanitized"] = False
        decision_context["sanitized_timeframes"] = []

        if not isinstance(raw_context, dict):
            return pack

        for timeframe, raw_context_tf in raw_context.items():
            if not isinstance(raw_context_tf, dict):
                continue

            sanitized_raw, changed = self._slice_to_closed_candles(timeframe, raw_context_tf)
            if not changed:
                continue

            sanitized_raw = self._rebuild_raw_context_summary(sanitized_raw)
            raw_context[timeframe] = sanitized_raw
            microstructure[timeframe] = self._rebuild_microstructure_for_tf(sanitized_raw)

            if timeframe in indicators and isinstance(indicators[timeframe], dict):
                last_close = self._to_float(sanitized_raw.get("latest_close"), 0.0)
                indicators[timeframe]["close"] = last_close

                ema20 = self._to_float(indicators[timeframe].get("ema_20"), 0.0)
                if ema20 > 0:
                    indicators[timeframe]["distance_to_ema20_pct"] = (last_close - ema20) / ema20

            decision_context["closed_candle_sanitized"] = True
            decision_context["sanitized_timeframes"].append(timeframe)

        pack["raw_context"] = raw_context
        pack["microstructure"] = microstructure
        pack["indicators"] = indicators
        return pack

    def _estimate_base_size_from_quote(self, quote_size: Decimal, price: Decimal) -> Decimal:
        if quote_size <= Decimal("0") or price <= Decimal("0"):
            return Decimal("0")
        return quote_size / price

    def _compute_realized_pnl(
        self,
        position: Dict[str, Any],
        exit_base_size: Decimal,
        exit_price: Decimal,
    ) -> float:
        entry_price = self._to_decimal(position.get("entry_price"), "0")
        if entry_price <= Decimal("0") or exit_base_size <= Decimal("0") or exit_price <= Decimal("0"):
            return 0.0

        pnl = (exit_price - entry_price) * exit_base_size
        return float(pnl)

    def _reconcile_order_fill(
        self,
        order_id: str,
    ) -> Dict[str, Any]:
        order_data = self.client.get_order(order_id)
        fill_summary = self.client.summarize_fills_for_order(order_id)
        return {
            "order": order_data,
            "fills": fill_summary,
        }

    def _get_live_spot_position(self, ticker: str) -> Dict[str, Any]:
        try:
            return self.client.get_spot_position(ticker)
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "error_type": "live_spot_position_fetch_failed",
                    "error": str(e),
                },
            )
            return {
                "product_id": ticker,
                "available_base_balance": "0",
                "available_quote_balance": "0",
            }

    def _get_live_available_base(self, ticker: str) -> Decimal:
        live = self._get_live_spot_position(ticker)
        return self._to_decimal(live.get("available_base_balance"), "0")

    def _cfg_inventory_sell_enabled(self) -> bool:
        return bool(getattr(self.cfg, "inventory_sell_enabled", False))

    def _cfg_inventory_sell_mode(self) -> str:
        return str(getattr(self.cfg, "inventory_sell_mode", "bot_only") or "bot_only").strip().lower()

    def _cfg_inventory_max_extra_sell_fraction(self) -> Decimal:
        return self._to_decimal(getattr(self.cfg, "inventory_max_extra_sell_fraction", "0.33"), "0.33")

    def _cfg_inventory_severe_risk_only(self) -> bool:
        return bool(getattr(self.cfg, "inventory_severe_risk_only", True))

    def _cfg_inventory_min_residual_base(self) -> Decimal:
        return self._to_decimal(getattr(self.cfg, "inventory_min_residual_base", "0"), "0")

    def _current_inventory_policy_payload(self) -> Dict[str, Any]:
        """Return the authoritative runtime inventory policy from BotConfig.

        Existing positions may contain old inventory policy snapshots from a previous
        .env. Those snapshots are useful for audit history, but they must not keep
        controlling live sell behaviour after the .env has changed.
        """
        return {
            "inventory_sell_enabled": self._cfg_inventory_sell_enabled(),
            "inventory_sell_mode": self._cfg_inventory_sell_mode(),
            "inventory_max_extra_sell_fraction": str(self._cfg_inventory_max_extra_sell_fraction()),
            "inventory_severe_risk_only": self._cfg_inventory_severe_risk_only(),
            "inventory_min_residual_base": str(self._cfg_inventory_min_residual_base()),
        }

    def _apply_current_inventory_policy_to_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        policy = self._current_inventory_policy_payload()
        payload.update(policy)
        payload["inventory_policy_snapshot"] = dict(policy)
        return payload

    def _capture_pre_entry_inventory_base(self, ticker: str) -> Decimal:
        try:
            return self._get_live_available_base(ticker)
        except Exception:
            return Decimal("0")

    def _extract_position_inventory_state(self, position: Optional[Dict[str, Any]]) -> Dict[str, Decimal]:
        pos = dict(position or {})
        bot_managed_base = self._to_decimal(
            pos.get("bot_managed_base"),
            str(pos.get("position_size_base", "0")),
        )
        legacy_inventory_base = self._to_decimal(
            pos.get("legacy_inventory_base"),
            str(pos.get("baseline_inventory_base", "0")),
        )
        baseline_inventory_base = self._to_decimal(
            pos.get("baseline_inventory_base"),
            str(legacy_inventory_base),
        )
        return {
            "bot_managed_base": bot_managed_base,
            "legacy_inventory_base": legacy_inventory_base,
            "baseline_inventory_base": baseline_inventory_base,
        }

    def _build_inventory_policy_snapshot(self, position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # Runtime config is authoritative. The optional position argument is kept
        # for backward-compatible callers, but intentionally not used for policy.
        return self._current_inventory_policy_payload()

    def _initialize_inventory_tracking_after_entry(
        self,
        ticker: str,
        entry_base_size: Decimal,
        baseline_inventory_base: Decimal,
        existing_position: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "baseline_inventory_base": str(baseline_inventory_base),
            "bot_managed_base": str(entry_base_size),
            "legacy_inventory_base": str(baseline_inventory_base),
            "inventory_sell_enabled": self._cfg_inventory_sell_enabled(),
            "inventory_sell_mode": self._cfg_inventory_sell_mode(),
            "inventory_max_extra_sell_fraction": str(self._cfg_inventory_max_extra_sell_fraction()),
            "inventory_severe_risk_only": self._cfg_inventory_severe_risk_only(),
            "inventory_min_residual_base": str(self._cfg_inventory_min_residual_base()),
            "inventory_last_sell_scope": "bot_only",
            "inventory_last_extra_sell_base": "0",
            "inventory_policy_snapshot": self._build_inventory_policy_snapshot(),
        }
        return self.state.upsert_position(ticker, payload)

    def _compute_inventory_sell_plan(
        self,
        ticker: str,
        position: Dict[str, Any],
        action_type: str,
        requested_bot_sell_base: Decimal,
        live_available_base: Decimal,
    ) -> Dict[str, Any]:
        inventory_state = self._extract_position_inventory_state(position)
        bot_managed_base = inventory_state["bot_managed_base"]
        legacy_inventory_base = inventory_state["legacy_inventory_base"]

        # Runtime .env/config is authoritative for sell policy. Do not let stale
        # per-position snapshots from earlier runs re-enable inventory overlays.
        inventory_sell_enabled = self._cfg_inventory_sell_enabled()
        inventory_sell_mode = self._cfg_inventory_sell_mode()
        inventory_max_extra_sell_fraction = self._cfg_inventory_max_extra_sell_fraction()
        inventory_severe_risk_only = self._cfg_inventory_severe_risk_only()
        inventory_min_residual_base = self._cfg_inventory_min_residual_base()

        sell_headroom_total = max(Decimal("0"), live_available_base - inventory_min_residual_base)
        bot_sell_target = min(max(Decimal("0"), requested_bot_sell_base), bot_managed_base, sell_headroom_total)
        sell_headroom_after_bot = max(Decimal("0"), sell_headroom_total - bot_sell_target)

        legacy_sell_target = Decimal("0")
        sell_scope = "bot_only"

        allow_inventory_overlay = (
            inventory_sell_enabled
            and action_type == "close"
            and inventory_sell_mode in {"bot_plus_inventory_partial", "full_inventory_allowed"}
            and (not inventory_severe_risk_only or action_type == "close")
        )

        if allow_inventory_overlay and sell_headroom_after_bot > Decimal("0"):
            if inventory_sell_mode == "full_inventory_allowed":
                legacy_sell_target = min(legacy_inventory_base, sell_headroom_after_bot)
                if legacy_sell_target > Decimal("0"):
                    sell_scope = "full_inventory_allowed"
            else:
                partial_cap = legacy_inventory_base * inventory_max_extra_sell_fraction
                legacy_sell_target = min(legacy_inventory_base, partial_cap, sell_headroom_after_bot)
                if legacy_sell_target > Decimal("0"):
                    sell_scope = "bot_plus_inventory_partial"

        total_sell_base = bot_sell_target + legacy_sell_target
        remaining_bot_managed_base = max(Decimal("0"), bot_managed_base - bot_sell_target)
        remaining_legacy_inventory_base = max(Decimal("0"), legacy_inventory_base - legacy_sell_target)

        return {
            "ticker": ticker,
            "sell_total_base": total_sell_base,
            "sell_bot_base": bot_sell_target,
            "sell_legacy_base": legacy_sell_target,
            "remaining_bot_managed_base": remaining_bot_managed_base,
            "remaining_legacy_inventory_base": remaining_legacy_inventory_base,
            "sell_scope": sell_scope,
            "inventory_min_residual_base": inventory_min_residual_base,
            "inventory_state_before": {
                "bot_managed_base": str(bot_managed_base),
                "legacy_inventory_base": str(legacy_inventory_base),
                "baseline_inventory_base": str(inventory_state["baseline_inventory_base"]),
            },
            "inventory_policy": {
                "inventory_sell_enabled": inventory_sell_enabled,
                "inventory_sell_mode": inventory_sell_mode,
                "inventory_max_extra_sell_fraction": str(inventory_max_extra_sell_fraction),
                "inventory_severe_risk_only": inventory_severe_risk_only,
                "inventory_min_residual_base": str(inventory_min_residual_base),
            },
        }

    def _sync_inventory_after_exit(
        self,
        ticker: str,
        position: Dict[str, Any],
        inventory_plan: Dict[str, Any],
        live_available_base_after: Decimal,
        current_price: Decimal,
    ) -> Dict[str, Any]:
        remaining_bot_managed_base = self._to_decimal(
            inventory_plan.get("remaining_bot_managed_base"),
            str(position.get("bot_managed_base") or position.get("position_size_base") or "0"),
        )
        remaining_legacy_inventory_base = self._to_decimal(
            inventory_plan.get("remaining_legacy_inventory_base"),
            str(position.get("legacy_inventory_base") or position.get("baseline_inventory_base") or "0"),
        )

        total_remaining_from_tracking = remaining_bot_managed_base + remaining_legacy_inventory_base
        if live_available_base_after < total_remaining_from_tracking:
            residual_after_bot = max(Decimal("0"), live_available_base_after - remaining_bot_managed_base)
            remaining_legacy_inventory_base = min(remaining_legacy_inventory_base, residual_after_bot)

        payload = dict(position)
        payload.update({
            "bot_managed_base": str(remaining_bot_managed_base),
            "legacy_inventory_base": str(remaining_legacy_inventory_base),
            "baseline_inventory_base": str(remaining_legacy_inventory_base),
            "inventory_last_sell_scope": str(inventory_plan.get("sell_scope", "bot_only")),
            "inventory_last_extra_sell_base": str(inventory_plan.get("sell_legacy_base", "0")),
            "position_size_base": str(remaining_bot_managed_base),
            "position_size_quote": str(remaining_bot_managed_base * current_price),
            "updated_at": self._now_iso(),
        })
        self._apply_current_inventory_policy_to_payload(payload)
        return self.state.upsert_position(ticker, payload)

    def _sync_local_position_to_live_balance(
        self,
        ticker: str,
        position: Dict[str, Any],
        live_available_base: Decimal,
        current_price: Decimal,
        note: str,
    ) -> Dict[str, Any]:
        if live_available_base <= self.position_epsilon_base:
            return self.state.mark_position_closed(
                ticker=ticker,
                close_reason=note,
                close_price=str(current_price),
                realized_pnl=None,
            )

        live_quote_notional = live_available_base * current_price if current_price > Decimal("0") else Decimal("0")
        if Decimal("0") < live_quote_notional < self.min_trade_quote_usdc:
            if self._should_skip_tiny_residual_close_for_phase_c43_pilot_review(
                ticker=ticker,
                position=position,
                live_base_size=live_available_base,
                live_quote_notional=live_quote_notional,
            ):
                return self._keep_phase_c43_pilot_position_open_for_governance_review(
                    ticker=ticker,
                    position=position,
                    live_base_size=live_available_base,
                    live_quote_notional=live_quote_notional,
                    current_price=current_price,
                    note=note,
                )
            return self.state.mark_position_closed_tiny_residual(
                ticker=ticker,
                close_reason="inventory_sync_live_notional_below_min_trade_quote",
                close_price=str(current_price),
                residual_base=str(live_available_base),
                residual_quote=str(live_quote_notional),
                extra={
                    "notes": "synced_from_live_exchange_inventory | inventory_sync_ignored_dust_below_min_trade_quote",
                    "monitoring_enabled": False,
                    "opened_via_strategy": False,
                    "synced_from_exchange": True,
                    "last_position_risk_state": "closed_dust_cleanup",
                },
            )

        updated_position = dict(position)
        bot_managed_base = self._to_decimal(
            updated_position.get("bot_managed_base"),
            str(updated_position.get("position_size_base", "0")),
        )
        legacy_inventory_base = self._to_decimal(
            updated_position.get("legacy_inventory_base"),
            "0",
        )

        synced_bot_managed_base = min(bot_managed_base, live_available_base)
        inferred_legacy_from_live = max(Decimal("0"), live_available_base - synced_bot_managed_base)
        synced_legacy_inventory_base = max(legacy_inventory_base, inferred_legacy_from_live)

        updated_position["bot_managed_base"] = str(synced_bot_managed_base)
        updated_position["legacy_inventory_base"] = str(synced_legacy_inventory_base)
        updated_position["baseline_inventory_base"] = str(synced_legacy_inventory_base)
        updated_position["position_size_base"] = str(synced_bot_managed_base)
        updated_position["position_size_quote"] = str(synced_bot_managed_base * current_price)
        updated_position["updated_at"] = self._now_iso()
        updated_position["notes"] = str(updated_position.get("notes", "") or "")
        if note not in updated_position["notes"]:
            updated_position["notes"] = (updated_position["notes"] + f" | {note}").strip(" |")

        self._apply_current_inventory_policy_to_payload(updated_position)

        if synced_bot_managed_base <= self.position_epsilon_base:
            closed = self.state.upsert_position(ticker, updated_position)
            return self.state.mark_position_closed(
                ticker=ticker,
                close_reason=note,
                close_price=str(current_price),
                realized_pnl=None,
            )

        return self.state.upsert_position(ticker, updated_position)

    def _should_skip_tiny_residual_close_for_phase_c43_pilot_review(
        self,
        *,
        ticker: str,
        position: Optional[Dict[str, Any]],
        live_base_size: Decimal,
        live_quote_notional: Decimal,
    ) -> bool:
        return bool(
            self._tiny_residual_keep_open_reason(
                ticker=ticker,
                position=position,
                live_base_size=live_base_size,
                live_quote_notional=live_quote_notional,
            )
        )

    def _matching_open_d3_live_exit_order_for_position(
        self,
        *,
        ticker: str,
        position: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        row = dict(position or {})
        if not row:
            return None
        selected_ticker = str(ticker or "").strip().upper()
        candidates = logical_position_id_candidates(row)
        if not selected_ticker or not candidates:
            return None
        matches: List[Dict[str, Any]] = []
        for order in iter_matching_open_d3_orders(
            self.order_store,
            ticker=selected_ticker,
            position=row,
        ):
            exchange_order_id = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
            if not exchange_order_id:
                continue
            matches.append(dict(order))
        if len(matches) != 1:
            return None
        return matches[0]

    def _tiny_residual_keep_open_reason(
        self,
        *,
        ticker: str,
        position: Optional[Dict[str, Any]],
        live_base_size: Decimal,
        live_quote_notional: Decimal,
    ) -> str:
        row = dict(position or {})
        if not row:
            return ""
        if not (Decimal("0") < live_quote_notional < self.min_trade_quote_usdc):
            return ""

        status = str(row.get("status") or "").strip().lower()
        if status not in {"open", "active"}:
            return ""

        matching_open_d3 = self._matching_open_d3_live_exit_order_for_position(
            ticker=ticker,
            position=row,
        )
        if matching_open_d3 is not None:
            return "inventory_sync_position_kept_open_due_to_open_d3_exit_order"

        if str(row.get("opened_via_phase_c43_live_order") or "").strip().lower() not in {"1", "true", "yes", "on"}:
            return ""
        if not str(row.get("phase_c43_client_order_id") or "").strip():
            return ""
        if not str(row.get("phase_c43_exchange_order_id") or row.get("order_id") or "").strip():
            return ""

        managed_base = self._to_decimal(
            row.get("bot_managed_base"),
            str(row.get("position_size_base", "0")),
        )
        position_base = self._to_decimal(
            row.get("position_size_base"),
            str(row.get("bot_managed_base", "0")),
        )
        if max(managed_base, position_base, live_base_size) <= self.position_epsilon_base:
            return ""

        # Keep this exception narrow: only fresh Phase-C pilot positions with no
        # real close markers and no open D.3 exit reservations remain reviewable.
        if any(str(row.get(field) or "").strip() for field in ("closed_at", "close_time", "close_order_id")):
            return ""
        if any(str(row.get(field) or "").strip() for field in ("close_reason", "synthetic_close_reason")):
            return ""
        if iter_matching_open_d3_orders(self.order_store, ticker=ticker, position=row):
            return ""
        return "phase_c43_pilot_position_kept_open_for_d2_d3_governance_review"

    def _keep_phase_c43_pilot_position_open_for_governance_review(
        self,
        *,
        ticker: str,
        position: Dict[str, Any],
        live_base_size: Decimal,
        live_quote_notional: Decimal,
        current_price: Decimal,
        note: str,
        keep_open_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        updated_position = dict(position)
        bot_managed_base = self._to_decimal(
            updated_position.get("bot_managed_base"),
            str(updated_position.get("position_size_base", "0")),
        )
        reason_marker = str(
            keep_open_reason
            or self._tiny_residual_keep_open_reason(
                ticker=ticker,
                position=position,
                live_base_size=live_base_size,
                live_quote_notional=live_quote_notional,
            )
            or "phase_c43_pilot_position_kept_open_for_d2_d3_governance_review"
        ).strip()
        live_base_str = str(live_available := max(live_base_size, self.position_epsilon_base))
        synced_bot_managed_base = max(bot_managed_base, live_available)

        updated_position["status"] = str(updated_position.get("status") or "open")
        updated_position["position_size_base"] = live_base_str
        updated_position["position_size_quote"] = str(live_quote_notional)
        updated_position["bot_managed_base"] = str(synced_bot_managed_base)
        updated_position["updated_at"] = self._now_iso()
        updated_position["monitoring_enabled"] = True
        updated_position["last_heartbeat_status"] = "open_tiny_phase_c43_governance_review"
        updated_position["last_heartbeat_reason"] = reason_marker
        updated_position["tiny_residual_close_skipped_for_phase_c43_pilot_review"] = True
        updated_position["tiny_residual_close_skip_reason"] = reason_marker
        updated_position["notes"] = str(updated_position.get("notes", "") or "")
        for marker in (
            note,
            reason_marker,
        ):
            if marker and marker not in updated_position["notes"]:
                updated_position["notes"] = (updated_position["notes"] + f" | {marker}").strip(" |")
        self._apply_current_inventory_policy_to_payload(updated_position)
        return self.state.upsert_position(ticker, updated_position)

    def _infer_setup_type_from_analysis(self, analysis_input: Dict[str, Any]) -> str:
        feature_pack = analysis_input.get("feature_pack", {})
        entry_gate = feature_pack.get("entry_gate", {})
        entry_gate_setup = self._normalize_setup_type(entry_gate.get("setup_type"))
        if entry_gate_setup != "unclear":
            return entry_gate_setup

        meanrev = analysis_input.get("meanrev", {})
        breakout = analysis_input.get("breakout", {})
        trend = analysis_input.get("trend", {})

        meanrev_direction = str(meanrev.get("meanrev_direction", "")).strip().lower()
        oversold_score = self._extract_score(meanrev.get("oversold_score"))
        meanrev_quality = self._extract_score(meanrev.get("reversal_quality_score"))
        if meanrev_direction in {"up", "long", "long_bias_with_low_confidence"} or (oversold_score >= 55 and meanrev_quality >= 30):
            return "mean_reversion"

        breakout_confirmation = self._extract_score(breakout.get("breakout_confirmation_score"))
        if breakout_confirmation >= 55:
            return "trend_continuation"

        trend_direction = str(trend.get("trend_direction", "")).strip().lower()
        trend_strength = self._extract_score(trend.get("trend_strength_score"))
        if trend_direction in {"bullish", "up", "long"} and trend_strength >= 55:
            return "trend_continuation"

        return "reclaim_reversal"

    def _clamp_judge_buy_size_quote(
        self,
        judge: Dict[str, Any],
        feature_pack: Dict[str, Any],
    ) -> Decimal:
        decision = self._normalize_decision(judge)
        side = self._normalize_side(judge)

        if decision != "approve_trade" or side != "BUY":
            return Decimal("0")

        raw_size = self._parse_size_quote(judge, Decimal("0"))
        available_quote = self._to_decimal(
            feature_pack["risk_context"].get("available_quote_balance"),
            "0",
        )
        max_notional_limit = self._to_decimal(
            feature_pack["risk_context"].get("max_notional_limit"),
            str(self.max_trade_quote_usdc),
        )

        setup_type = (
            judge.get("setup_type")
            or feature_pack.get("entry_gate", {}).get("setup_type")
            or judge.get("strategy")
        )
        setup_cap = self._setup_type_cap(setup_type)

        if raw_size <= Decimal("0"):
            raw_size = self._default_size_for_setup(
                setup_type=setup_type,
                confidence=judge.get("confidence", 55),
            )

        hard_cap = min(
            self.max_trade_quote_usdc,
            setup_cap,
            max_notional_limit,
            available_quote,
        )

        if hard_cap < self.min_trade_quote_usdc:
            return Decimal("0")

        clamped = raw_size

        if clamped < self.min_trade_quote_usdc:
            clamped = self.min_trade_quote_usdc

        if clamped > hard_cap:
            clamped = hard_cap

        if clamped < self.min_trade_quote_usdc:
            return Decimal("0")

        return self._quantize_quote(clamped)

    def _safe_module_response(
        self,
        prompt: str,
        dossier: Dict[str, Any],
        module_name: str,
        ticker: str,
    ) -> Dict[str, Any]:
        try:
            payload = self.openai.json_response(
                prompt,
                dossier,
                model=self.analyst_model,
                ticker=ticker,
                stage=module_name,
                allowed_keys=MODULE_ALLOWED_KEYS.get(module_name, []),
                require_all_keys=module_name in {"meanrev", "bull", "bear", "synth"},
                drop_unknown_keys=True,
            )
            if isinstance(payload, dict):
                return payload
            return {
                "module": module_name,
                "fallback": True,
                "fallback_reason": f"{module_name}_payload_not_dict",
            }
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": module_name,
                    "error_type": "llm_output_corrupt",
                    "error": str(e),
                },
            )
            return {
                "module": module_name,
                "fallback": True,
                "fallback_reason": f"{module_name}_failed: {e}",
            }


    def _should_call_expensive_judge(
        self,
        judge_input: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        """
        Decide whether the expensive GPT-5.5 judge should be called.

        Existing open positions always get the judge because position-risk management
        is more important than saving one model call. New entries must first pass the
        cheaper nano/deepseek/mini stack with a clearly constructive setup.
        """
        if not getattr(self.cfg, "enable_expensive_judge_gate", True):
            return True, ["expensive_judge_gate_disabled"], {"escalate_to_final_judge": True}

        if existing_position and str(existing_position.get("status", "open")).lower() == "open":
            return True, ["existing_position_requires_final_judge"], {"escalate_to_final_judge": True}

        feature_pack = judge_input.get("feature_pack", {}) or {}
        risk_context = feature_pack.get("risk_context", {}) or {}
        market = feature_pack.get("market", {}) or {}
        entry_gate = feature_pack.get("entry_gate", {}) or {}
        synth = judge_input.get("synth", {}) or {}
        bull = judge_input.get("bull", {}) or {}
        bear = judge_input.get("bear", {}) or {}
        breakout = judge_input.get("breakout", {}) or {}
        trend = judge_input.get("trend", {}) or {}
        meanrev = judge_input.get("meanrev", {}) or {}

        reasons: List[str] = []
        warnings: List[str] = []
        decision = str(entry_gate.get("decision", "")).strip().lower()
        priority = str(entry_gate.get("priority", "normal")).strip().lower()
        setup_type = self._infer_setup_type_from_analysis(judge_input)

        gate_conf = self._extract_score(entry_gate.get("confidence"), 0)
        synth_conf = self._extract_score(synth.get("composite_confidence"), 0)
        bull_score = self._extract_score(bull.get("bull_case_score"), 0)
        bear_score = self._extract_score(bear.get("bear_case_score"), 0)
        breakout_quality = self._extract_score(breakout.get("breakout_quality_score"), 0)
        breakout_confirmation = self._extract_score(breakout.get("breakout_confirmation_score"), 0)
        trend_strength = self._extract_score(trend.get("trend_strength_score"), 0)
        trend_alignment = self._extract_score(trend.get("trend_alignment_score"), 0)

        min_gate_conf = int(getattr(self.cfg, "judge_min_gate_confidence", 62))
        min_synth_conf = int(getattr(self.cfg, "judge_min_synth_confidence", 60))
        min_bull_score = int(getattr(self.cfg, "judge_min_bull_score", 56))
        max_bear_score = int(getattr(self.cfg, "judge_max_bear_score", 72))
        metrics: Dict[str, Any] = {
            "preselection_stage": "expensive_judge_gate",
            "setup_type": setup_type,
            "gate_decision": decision,
            "gate_priority": priority,
            "gate_confidence": gate_conf,
            "synth_confidence": synth_conf,
            "bull_score": bull_score,
            "bear_score": bear_score,
            "breakout_quality": breakout_quality,
            "breakout_confirmation": breakout_confirmation,
            "trend_strength": trend_strength,
            "trend_alignment": trend_alignment,
            "liquidity_quality": 0,
            "invalidation_quality": 0,
            "entry_zone_quality": 0,
            "trigger_freshness": 0,
            "setup_potential": 0,
            "risk_defined_bonus": 0,
            "hard_blocker_penalty": 0,
            "stale_data_penalty": 0,
            "chase_penalty": 0,
            "escalation_score": 0,
            "escalate_to_final_judge": False,
            "would_have_been_candidate_if_preselection_relaxed": False,
            "warnings": warnings,
        }

        def block(reason: str) -> Tuple[bool, List[str], Dict[str, Any]]:
            reasons.append(reason)
            metrics["top_blocker"] = reason
            metrics["hard_blocker_penalty"] = max(int(metrics.get("hard_blocker_penalty") or 0), 100)
            return False, reasons, metrics

        if decision not in {"analyze", "priority_analyze", "position_management_bypass"}:
            if decision != "watch":
                return block(f"entry_gate_decision_not_judge_worthy:{decision or 'missing'}")
            warnings.append("entry_gate_watch_candidate_can_escalate_if_context_quality_is_high")

        if market.get("trading_disabled") is True or market.get("cancel_only") is True:
            return block("market_not_tradeable")

        if risk_context.get("engine_state", {}).get("cooldown_active"):
            return block("cooldown_active")

        spread_pct = self._to_decimal(market.get("spread_pct"), "1")
        max_spread_pct = self._to_decimal(market.get("max_spread_pct"), str(self.cfg.max_spread_pct))
        if spread_pct > max_spread_pct:
            return block(f"spread_too_wide_for_expensive_judge:{spread_pct}>{max_spread_pct}")
        metrics["liquidity_quality"] = 25 if spread_pct <= (max_spread_pct * Decimal("0.50")) else 15

        available_quote = self._to_decimal(risk_context.get("available_quote_balance"), "0")
        if available_quote < self.min_trade_quote_usdc:
            return block("available_quote_below_min_trade")

        invalidation_present = bool(
            str(synth.get("invalidation") or "").strip()
            or str(breakout.get("breakout_invalidation_level") or "").strip()
            or str(meanrev.get("meanrev_stop_logic") or "").strip()
            or str(trend.get("trend_stop_logic") or "").strip()
        )
        metrics["invalidation_quality"] = 22 if invalidation_present else 0
        metrics["risk_defined_bonus"] = 12 if invalidation_present else 0
        entry_zone_present = any(
            str(value or "").strip()
            for value in (
                trend.get("entry_zone_low"),
                trend.get("entry_zone_high"),
                meanrev.get("entry_zone_low"),
                meanrev.get("entry_zone_high"),
                breakout.get("breakout_trigger_level"),
            )
        )
        metrics["entry_zone_quality"] = 18 if entry_zone_present else 0
        metrics["trigger_freshness"] = 15 if str(synth.get("key_trigger") or breakout.get("breakout_trigger_level") or "").strip() else 5

        if gate_conf < min_gate_conf and priority != "high":
            warnings.append(f"gate_confidence_below_threshold_warning:{gate_conf}<{min_gate_conf}")

        if synth_conf < min_synth_conf:
            warnings.append(f"synth_confidence_below_threshold_warning:{synth_conf}<{min_synth_conf}")

        if bull_score < min_bull_score:
            warnings.append(f"bull_score_below_threshold_warning:{bull_score}<{min_bull_score}")

        if bear_score > max_bear_score and bear_score >= bull_score:
            warnings.append(f"bear_score_dominant_warning:{bear_score}>={bull_score}")

        local_structure_bonus = 0
        if priority == "high":
            local_structure_bonus += 14
        if decision in {"analyze", "priority_analyze"}:
            local_structure_bonus += 12
        if breakout_quality >= 55 or breakout_confirmation >= 45:
            local_structure_bonus += 10
        if trend_strength >= 50 or trend_alignment >= 50:
            local_structure_bonus += 8
        metrics["setup_potential"] = max(0, min(30, local_structure_bonus + max(0, bull_score - 45) // 2 + max(0, synth_conf - 50) // 2))

        if setup_type == "trend_continuation":
            trend_ok = (
                trend_strength >= 55
                or trend_alignment >= 55
                or breakout_confirmation >= 55
                or priority == "high"
            )
            if not trend_ok:
                warnings.append(
                    "trend_setup_not_confirmed_enough_for_gpt55_judge:"
                    f"trend_strength={trend_strength},trend_alignment={trend_alignment},"
                    f"breakout_confirmation={breakout_confirmation}"
                )
        elif setup_type == "reclaim_reversal":
            reclaim_ok = (
                synth_conf >= max(min_synth_conf - 4, 56)
                and bull_score >= max(min_bull_score - 4, 52)
                and bear_score <= max(max_bear_score, bull_score + 8)
            )
            if not reclaim_ok:
                warnings.append(
                    "reclaim_setup_not_confirmed_enough_for_gpt55_judge:"
                    f"synth_conf={synth_conf},bull_score={bull_score},bear_score={bear_score}"
                )
        elif setup_type == "mean_reversion":
            meanrev_ok = (
                (priority == "high" or entry_zone_present)
                and synth_conf >= max(min_synth_conf - 4, 56)
                and bull_score >= max(min_bull_score - 6, 50)
            )
            if not meanrev_ok:
                warnings.append(
                    "mean_reversion_requires_high_priority_and_stronger_confirmation_for_gpt55_judge:"
                    f"priority={priority},synth_conf={synth_conf},bull_score={bull_score},bear_score={bear_score}"
                )
        else:
            generic_ok = (
                priority == "high"
                or (synth_conf >= max(min_synth_conf - 2, 58) and bull_score >= max(min_bull_score - 2, 54))
                or breakout_quality >= 65
            )
            if not generic_ok:
                warnings.append(
                    "unclear_setup_not_strong_enough_for_gpt55_judge:"
                    f"priority={priority},synth_conf={synth_conf},bull_score={bull_score},breakout_quality={breakout_quality}"
                )

        bearish_penalty = 10 if bear_score > max_bear_score and bear_score >= bull_score else 0
        confidence_penalty = 0
        if gate_conf < min_gate_conf and priority != "high":
            confidence_penalty += min(12, min_gate_conf - gate_conf)
        if synth_conf < min_synth_conf:
            confidence_penalty += min(12, min_synth_conf - synth_conf)
        if bull_score < min_bull_score:
            confidence_penalty += min(10, min_bull_score - bull_score)
        metrics["escalation_score"] = int(
            metrics["liquidity_quality"]
            + metrics["invalidation_quality"]
            + metrics["entry_zone_quality"]
            + metrics["trigger_freshness"]
            + metrics["setup_potential"]
            + metrics["risk_defined_bonus"]
            - bearish_penalty
            - confidence_penalty
        )
        min_escalation = 68 if decision == "watch" else 58
        if not invalidation_present:
            return block("defined_invalidation_missing_for_final_judge_escalation")
        if metrics["escalation_score"] < min_escalation:
            reason = f"escalation_score_below_threshold:{metrics['escalation_score']}<{min_escalation}"
            reasons.append(reason)
            metrics["top_blocker"] = reason
            metrics["would_have_been_candidate_if_preselection_relaxed"] = bool(
                metrics["liquidity_quality"] and metrics["entry_zone_quality"] and metrics["invalidation_quality"]
            )
            return False, reasons + warnings, metrics

        reasons.append(
            "expensive_judge_allowed:"
            f"setup_type={setup_type},gate_conf={gate_conf},synth_conf={synth_conf},"
            f"bull_score={bull_score},bear_score={bear_score},escalation_score={metrics['escalation_score']}"
        )
        metrics["escalate_to_final_judge"] = True
        return True, reasons + warnings, metrics

    def _enforce_bull_bear_confidence_gate(
        self,
        judge: Dict[str, Any],
        judge_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Deterministic fail-closed re-check of approve_trade/BUY judge decisions.

        JUDGE_MIN_BULL_SCORE / JUDGE_MAX_BEAR_SCORE / JUDGE_MIN_SYNTH_CONFIDENCE are
        consulted in _should_call_expensive_judge only to decide whether the expensive
        judge gets *called* at all (existing open positions and a disabled gate always
        escalate regardless of these scores). They must also hold for the judge's own
        approve_trade output, otherwise a call that reached the judge via one of those
        other escalation paths could approve a trade the thresholds were meant to block.
        """
        if judge.get("decision") != "approve_trade" or judge.get("side") != "BUY":
            return judge

        bull = judge_input.get("bull", {}) or {}
        bear = judge_input.get("bear", {}) or {}
        synth = judge_input.get("synth", {}) or {}
        bull_score = self._extract_score(bull.get("bull_case_score"), 0)
        bear_score = self._extract_score(bear.get("bear_case_score"), 0)
        synth_conf = self._extract_score(synth.get("composite_confidence"), 0)

        min_bull_score = int(getattr(self.cfg, "judge_min_bull_score", 56))
        max_bear_score = int(getattr(self.cfg, "judge_max_bear_score", 72))
        min_synth_conf = int(getattr(self.cfg, "judge_min_synth_confidence", 60))

        violations: List[str] = []
        if bull_score < min_bull_score:
            violations.append(f"bull_score_below_min:{bull_score}<{min_bull_score}")
        if bear_score > max_bear_score:
            violations.append(f"bear_score_above_max:{bear_score}>{max_bear_score}")
        if synth_conf < min_synth_conf:
            violations.append(f"synth_confidence_below_min:{synth_conf}<{min_synth_conf}")

        if violations:
            judge["decision"] = "wait"
            judge["side"] = "NONE"
            judge["size_quote"] = 0.0
            judge.setdefault("reasons", []).append(
                "approve_trade_blocked_fail_closed_bull_bear_confidence_gate:" + ",".join(violations)
            )
        return judge

    def _build_expensive_judge_skipped_result(
        self,
        judge_input: Dict[str, Any],
        skip_reasons: List[str],
    ) -> Dict[str, Any]:
        feature_pack = judge_input.get("feature_pack", {}) or {}
        entry_gate = feature_pack.get("entry_gate", {}) or {}
        synth = judge_input.get("synth", {}) or {}
        ticker = feature_pack.get("ticker")
        setup_type = self._infer_setup_type_from_analysis(judge_input)
        synth_conf = self._extract_score(synth.get("composite_confidence"), 0)
        gate_conf = self._extract_score(entry_gate.get("confidence"), 0)

        return {
            "decision": "wait",
            "ticker": ticker,
            "side": "NONE",
            "strategy": "mini_analysis_screened_no_expensive_judge",
            "confidence": max(0, min(100, min(synth_conf, gate_conf))),
            "size_quote": 0.0,
            "setup_type": setup_type,
            "reasons": [
                "gpt55_judge_not_called_because_setup_not_good_enough_after_mini_analysis",
                *[str(r) for r in skip_reasons],
            ],
            "must_reject_if": [
                "Setup does not pass cost-aware final judge threshold",
                "No GPT-5.5 judge approval was produced",
            ],
            "position_action": "none",
            "soft_rule_override": False,
            "override_rules": [],
            "runner_plan": {},
            "entry_mode": "none",
            "trigger": "",
        }

    def _run_trade_planner_with_fallback(
        self,
        planner_input: Dict[str, Any],
        ticker: str,
    ) -> Dict[str, Any]:
        """
        Ask GPT-5.5 for a concrete trade plan before the final judge.

        The planner never authorizes execution. Malformed output, provider errors,
        ticker mismatch or unsafe/incomplete plans normalize to no_plan.
        """
        planner_errors: List[str] = []

        try:
            raw_plan = self.openai.json_response(
                TRADE_PLANNER_PROMPT,
                planner_input,
                model=self.trade_planner_model,
                ticker=ticker,
                stage="trade_planner_gpt_5_5",
                allowed_keys=MODULE_ALLOWED_KEYS["trade_planner"],
                require_all_keys=False,
                drop_unknown_keys=True,
            )
            plan = normalize_trade_plan(
                raw_plan,
                ticker=ticker,
                max_size_quote=self.max_trade_quote_usdc,
                min_size_quote=self.min_trade_quote_usdc,
                source=f"openai:{self.trade_planner_model}",
            )
            plan.setdefault("reason", "")
            if plan.get("plan_action") == "no_plan":
                plan["reason"] = plan.get("reason") or "planner_returned_no_plan"
                starter = build_starter_probe_plan_from_context(
                    planner_input,
                    ticker=ticker,
                    max_size_quote=self.max_trade_quote_usdc,
                    min_size_quote=self.min_trade_quote_usdc,
                    source="deterministic_starter_probe_after_llm_no_plan",
                )
                if starter.get("plan_action") != "no_plan":
                    starter["llm_no_plan_reason"] = plan.get("reason")
                    return starter
                starter["llm_no_plan_reason"] = plan.get("reason")
                return starter
            return plan
        except Exception as e:
            planner_errors.append(f"openai_trade_planner_failed: {e}")
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "trade_planner",
                    "error_type": "llm_output_corrupt_or_provider_failure",
                    "error": str(e),
                },
            )

        starter = build_starter_probe_plan_from_context(
            planner_input,
            ticker=ticker,
            max_size_quote=self.max_trade_quote_usdc,
            min_size_quote=self.min_trade_quote_usdc,
            source="deterministic_starter_probe_after_planner_failure",
        )
        if starter.get("plan_action") != "no_plan":
            starter["planner_errors"] = planner_errors
            return starter
        starter["planner_errors"] = planner_errors
        starter["reason"] = "Trade planner failed and deterministic starter/probe conditions were not met. " + "; ".join(planner_errors)
        starter["no_plan_reason"] = starter["reason"]
        return starter

    def _judge_with_fallback(self, judge_input: Dict[str, Any]) -> Dict[str, Any]:
        def _normalize_judge_payload(payload: Dict[str, Any], source: str) -> Dict[str, Any]:
            if not isinstance(payload, dict):
                raise ValueError(f"{source} judge payload is geen dict")

            decision = str(payload.get("decision", "wait")).strip().lower()
            side = str(payload.get("side", "NONE")).strip().upper()

            allowed_decisions = {
                "approve_trade",
                "wait",
                "reject",
                "no_trade",
                "reduce_size",
                "close_position",
            }
            if decision not in allowed_decisions:
                decision = "wait"

            allowed_sides = {"BUY", "SELL", "NONE"}
            if side not in allowed_sides:
                side = "NONE"

            try:
                size_quote = Decimal(str(payload.get("size_quote", "0")))
            except Exception:
                size_quote = Decimal("0")

            if size_quote < Decimal("0"):
                size_quote = Decimal("0")

            raw_confidence = payload.get("confidence", None)
            try:
                if raw_confidence is None or raw_confidence == "":
                    raise ValueError("missing confidence")
                confidence = int(float(raw_confidence))
            except Exception:
                synth_conf = judge_input.get("synth", {}).get("composite_confidence")
                regime_conf = judge_input.get("regime", {}).get("regime_confidence")

                fallback_conf = None
                for candidate in (synth_conf, regime_conf):
                    try:
                        if candidate is not None:
                            c = float(candidate)
                            if c <= 1:
                                c = c * 100
                            fallback_conf = int(round(c))
                            break
                    except Exception:
                        pass

                confidence = fallback_conf if fallback_conf is not None else 25

            confidence = max(0, min(100, confidence))

            reasons = payload.get("judge_reasons", payload.get("reasons", []))
            if not isinstance(reasons, list):
                reasons = [str(reasons)]

            must_reject_if = payload.get("must_reject_if", [])
            if not isinstance(must_reject_if, list):
                must_reject_if = [str(must_reject_if)]

            inferred_setup_type = self._infer_setup_type_from_analysis(judge_input)

            expected_ticker = judge_input.get("feature_pack", {}).get("ticker")
            payload_ticker = str(payload.get("ticker", expected_ticker)).strip()
            if expected_ticker and payload_ticker and payload_ticker != expected_ticker:
                raise ValueError(
                    f"{source} judge returned mismatched ticker: expected={expected_ticker}, got={payload_ticker}"
                )

            position_action = str(payload.get("position_action", "none")).strip().lower() or "none"
            if position_action not in {"none", "hold", "hold_runner", "reduce", "close"}:
                position_action = "none"

            override_rules = payload.get("override_rules", [])
            if not isinstance(override_rules, list):
                override_rules = [str(override_rules)]

            runner_plan = payload.get("runner_plan", {})
            if not isinstance(runner_plan, dict):
                runner_plan = {}

            entry_mode = str(payload.get("entry_mode", "none")).strip().lower() or "none"
            if entry_mode not in {
                "none",
                "starter_position",
                "normal_entry",
                "wait_for_pullback",
                "wait_for_breakout_confirmation",
            }:
                entry_mode = "none"

            normalized = {
                "decision": decision,
                "ticker": payload_ticker or expected_ticker,
                "side": side,
                "strategy": str(payload.get("strategy", "fallback_judge")).strip() or "fallback_judge",
                "objective_score": self._to_float(payload.get("objective_score"), None),
                "expected_edge_score": self._to_float(payload.get("expected_edge_score"), None),
                "risk_penalty": self._to_float(payload.get("risk_penalty"), None),
                "cost_penalty": self._to_float(payload.get("cost_penalty"), None),
                "drawdown_risk": self._to_float(payload.get("drawdown_risk"), None),
                "execution_friction_penalty": self._to_float(payload.get("execution_friction_penalty"), None),
                "post_trigger_objective_score": self._to_float(payload.get("post_trigger_objective_score"), None),
                "confidence": confidence,
                "size_quote": float(size_quote),
                "reasons": [str(r) for r in reasons],
                "judge_reasons": [str(r) for r in reasons],
                "must_reject_if": [str(r) for r in must_reject_if],
                "valid_trade_plan": self._boolish(payload.get("valid_trade_plan"), False),
                "judge_response_valid_trade_plan": self._boolish(payload.get("valid_trade_plan"), False),
                "plan_type": str(payload.get("plan_type", "")).strip(),
                "setup_type": self._normalize_setup_type(
                    payload.get("setup_type") or inferred_setup_type
                ),
                "position_action": position_action,
                "soft_rule_override": self._boolish(payload.get("soft_rule_override"), False),
                "override_rules": [str(r) for r in override_rules],
                "runner_plan": runner_plan,
                "entry_mode": entry_mode,
                "trigger": str(payload.get("trigger", "")).strip(),
                "trigger_wait_reason": str(payload.get("trigger_wait_reason", "")).strip(),
            }
            if isinstance(payload.get("normalized_aliases"), list):
                normalized["normalized_aliases"] = [str(a) for a in payload.get("normalized_aliases", [])]
            if normalized["objective_score"] is None and normalized["expected_edge_score"] is not None:
                normalized["objective_score"] = float(normalized["expected_edge_score"]) - float(normalized["risk_penalty"] or 0) - float(normalized["cost_penalty"] or 0) - float(normalized["drawdown_risk"] or 0) - float(normalized["execution_friction_penalty"] or 0)
            normalized["missing_objective_score"] = normalized["objective_score"] is None

            if decision in {"wait", "reject", "no_trade"}:
                normalized["side"] = "NONE"
                normalized["size_quote"] = 0.0

            if decision == "approve_trade" and normalized["side"] != "BUY":
                normalized["decision"] = "wait"
                normalized["side"] = "NONE"
                normalized["size_quote"] = 0.0
                normalized["reasons"].append("approve_trade_without_buy_side_normalized_to_wait")

            if decision in {"reduce_size", "close_position"} and normalized["side"] not in {"SELL", "NONE"}:
                normalized["decision"] = "wait"
                normalized["side"] = "NONE"
                normalized["size_quote"] = 0.0
                normalized["reasons"].append("invalid_position_management_side_normalized_to_wait")

            return normalized

        judge_errors: List[str] = []


        try:
            openai_judge = self.openai.json_response(
                CLAUDE_JUDGE_PROMPT,
                judge_input,
                model=self.judge_model,
                ticker=judge_input.get("feature_pack", {}).get("ticker", "UNKNOWN"),
                stage="judge_gpt_5_5",
                allowed_keys=MODULE_ALLOWED_KEYS["judge"],
                require_all_keys=True,
                required_keys=FINAL_JUDGE_REQUIRED_KEYS,
                drop_unknown_keys=True,
                normalize_final_judge_aliases=True,
            )
            normalized = _normalize_judge_payload(openai_judge, "openai_gpt_5_5")
            normalized["reasons"].append(f"judge_provider=openai:{self.judge_model}")
            return normalized
        except Exception as e:
            judge_errors.append(f"openai_gpt_5_5_failed: {e}")

        if self.anthropic is not None:
            try:
                anthropic_judge = self.anthropic.json_message(
                    CLAUDE_JUDGE_PROMPT,
                    judge_input,
                    ticker=judge_input.get("feature_pack", {}).get("ticker", "UNKNOWN"),
                    stage="judge_anthropic_fallback",
                    allowed_keys=MODULE_ALLOWED_KEYS["judge"],
                    require_all_keys=True,
                    required_keys=FINAL_JUDGE_REQUIRED_KEYS,
                    drop_unknown_keys=True,
                    normalize_final_judge_aliases=True,
                )
                normalized = _normalize_judge_payload(anthropic_judge, "anthropic_fallback")
                normalized["reasons"].append("fallback_used_anthropic_after_openai_judge_failure")
                normalized["reasons"].extend(judge_errors)
                return normalized
            except Exception as e:
                judge_errors.append(f"anthropic_fallback_failed: {e}")
        else:
            judge_errors.append("anthropic_fallback_disabled")

        return {
            "decision": "wait",
            "ticker": judge_input.get("feature_pack", {}).get("ticker"),
            "side": "NONE",
            "strategy": "judge_fallback_safe_wait",
            "objective_score": None,
            "expected_edge_score": None,
            "risk_penalty": None,
            "cost_penalty": None,
            "drawdown_risk": None,
            "execution_friction_penalty": None,
            "confidence": 0,
            "size_quote": 0.0,
            "setup_type": self._infer_setup_type_from_analysis(judge_input),
            "reasons": [
                "judge_schema_failure",
                "Judge providers failed or were disabled; defaulting to safe no-trade.",
                *judge_errors,
            ],
            "judge_reasons": [
                "judge_schema_failure",
                "Judge providers failed or were disabled; defaulting to safe no-trade.",
                *judge_errors,
            ],
            "must_reject_if": [
                "Judge providers unavailable",
                "No validated judge response",
            ],
            "valid_trade_plan": False,
            "plan_type": "",
            "position_action": "none",
            "soft_rule_override": False,
            "override_rules": [],
            "runner_plan": {},
            "entry_mode": "none",
            "trigger": "",
        }

    def _maybe_promote_wait_to_small_probe(
        self,
        judge_input: Dict[str, Any],
        judge: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if existing_position and str(existing_position.get("status", "open")).lower() == "open":
            return judge

        trade_plan = judge_input.get("trade_plan") if isinstance(judge_input.get("trade_plan"), dict) else {}
        if not is_valid_entry_trade_plan(trade_plan):
            return judge

        if not self._is_no_trade_decision(judge):
            return judge

        feature_pack = judge_input.get("feature_pack", {})
        market = feature_pack.get("market", {})
        risk_context = feature_pack.get("risk_context", {})
        engine_state = risk_context.get("engine_state", {})
        entry_gate = feature_pack.get("entry_gate", {})
        micro = feature_pack.get("microstructure", {})
        indicators = feature_pack.get("indicators", {})
        structure = feature_pack.get("structure", {})
        synth = judge_input.get("synth", {})
        bull = judge_input.get("bull", {})
        bear = judge_input.get("bear", {})
        breakout = judge_input.get("breakout", {})

        entry_gate_decision = str(entry_gate.get("decision", "")).strip().lower()
        if entry_gate_decision not in {"analyze", "priority_analyze"}:
            return judge

        if engine_state.get("cooldown_active"):
            return judge

        if market.get("trading_disabled") is True or market.get("cancel_only") is True:
            return judge

        available_quote = self._to_decimal(risk_context.get("available_quote_balance"), "0")
        if available_quote < self.min_trade_quote_usdc:
            return judge

        spread_pct = self._to_decimal(market.get("spread_pct"), "1")
        max_spread_pct = self._to_decimal(market.get("max_spread_pct"), "0.0100")
        if spread_pct > max_spread_pct:
            return judge

        setup_type = self._infer_setup_type_from_analysis(judge_input)
        if setup_type == "mean_reversion":
            return judge

        synth_conf = self._extract_score(synth.get("composite_confidence"), 0)
        bull_score = self._extract_score(bull.get("bull_case_score"), 0)
        bear_score = self._extract_score(bear.get("bear_case_score"), 0)
        breakout_confirmation = self._extract_score(breakout.get("breakout_confirmation_score"), 0)

        close_15m = self._to_decimal(indicators.get("15m", {}).get("close"), "0")
        ema20_15m = self._to_decimal(indicators.get("15m", {}).get("ema_20"), "0")
        rsi_1h = self._to_float(indicators.get("1h", {}).get("rsi_14"), 50.0)
        rsi_4h = self._to_float(indicators.get("4h", {}).get("rsi_14"), 50.0)
        close_1h = self._to_decimal(indicators.get("1h", {}).get("close"), "0")
        ema20_1h = self._to_decimal(indicators.get("1h", {}).get("ema_20"), "0")
        ema50_1h = self._to_decimal(indicators.get("1h", {}).get("ema_50"), "0")
        ema50_4h = self._to_decimal(indicators.get("4h", {}).get("ema_50"), "0")
        ema200_4h = self._to_decimal(indicators.get("4h", {}).get("ema_200"), "0")
        bb_mid_1h = self._to_decimal(indicators.get("1h", {}).get("bb_mid"), "0")

        vol_15m = self._to_float(micro.get("15m", {}).get("volume_vs_avg"), 0.0)
        vol_1h = self._to_float(micro.get("1h", {}).get("volume_vs_avg"), 0.0)

        higher_lows_1h = bool(structure.get("higher_lows_1h", False))
        higher_highs_1h = bool(structure.get("higher_highs_1h", False))
        lower_highs_1h = bool(structure.get("lower_highs_1h", False))
        lower_lows_1h = bool(structure.get("lower_lows_1h", False))
        compression_detected = bool(structure.get("compression_detected", False))

        price_near_15m_ema = bool(ema20_15m > 0 and close_15m >= (ema20_15m * Decimal("0.999")))
        holding_1h_mid = bool(bb_mid_1h <= 0 or close_1h >= bb_mid_1h)
        # Recalibrated 2026-07-02: the 4h/1h HTF check used OR semantics, so a
        # lagging 4h EMA50/EMA200 cross alone (normal for the first 1-2 weeks of a
        # fresh reversal) blocked candidates even when the faster 1h structure was
        # clearly bullish. Live data (72h, 8 tickers, all trending +2%..+8%) showed
        # this OR-leg alone caused 46/64 of all blocks with zero 1h-only blocks.
        # Require BOTH timeframes to agree before treating the setup as bearish.
        bearish_htf_4h = (
            ema50_4h > Decimal("0")
            and ema200_4h > Decimal("0")
            and ema50_4h < ema200_4h
        )
        bearish_htf_1h = (
            ema20_1h > Decimal("0")
            and ema50_1h > Decimal("0")
            and ema20_1h < ema50_1h
        )
        if self.cfg.small_probe_require_htf_both_timeframes:
            bearish_htf = bearish_htf_4h and bearish_htf_1h
        else:
            bearish_htf = bearish_htf_4h or bearish_htf_1h

        # Recalibrated 2026-07-02: the analyst bear-case prompt is structurally more
        # pessimistic than the bull-case prompt (median bear_score - bull_score gap
        # was +29 across 64 valid plans in a 72h uptrend, and NEVER negative), so the
        # old absolute veto (bear_score >= max(40, bull_score-4)) vetoed every single
        # candidate. Gate on a wide relative gap instead of an near-always-true one.
        mixed_context = (bear_score - bull_score) >= self.cfg.small_probe_max_bear_bull_gap

        if mixed_context:
            return judge

        probe_ok = False

        if setup_type == "trend_continuation":
            probe_ok = (
                not bearish_htf
                and synth_conf >= self.cfg.small_probe_tc_synth_min
                and bull_score >= self.cfg.small_probe_tc_bull_min
                and breakout_confirmation >= self.cfg.small_probe_tc_breakout_confirmation_min
                and vol_15m >= float(self.cfg.small_probe_tc_vol_15m_min)
                and vol_1h >= float(self.cfg.small_probe_tc_vol_1h_min)
                and rsi_1h <= 72.0
                and rsi_4h <= 75.0
                and ema20_1h > 0
                and ema50_1h > 0
                and close_1h >= ema20_1h
                and close_1h >= ema50_1h
                and (higher_lows_1h or higher_highs_1h or compression_detected)
                and not (lower_highs_1h and lower_lows_1h)
            )
        elif setup_type == "reclaim_reversal":
            probe_ok = (
                not bearish_htf
                and synth_conf >= self.cfg.small_probe_rc_synth_min
                and bull_score >= self.cfg.small_probe_rc_bull_min
                and breakout_confirmation >= self.cfg.small_probe_rc_breakout_confirmation_min
                and vol_15m >= float(self.cfg.small_probe_rc_vol_15m_min)
                and vol_1h >= float(self.cfg.small_probe_rc_vol_1h_min)
                and rsi_1h <= 70.0
                and rsi_4h <= 74.0
                and price_near_15m_ema
                and holding_1h_mid
                and ema20_1h > 0
                and close_1h >= ema20_1h
                and (higher_lows_1h or compression_detected)
                and not lower_lows_1h
            )

        if not probe_ok:
            return judge

        probe_size = min(
            Decimal("25") if setup_type == "trend_continuation" else Decimal("20"),
            self._default_size_for_setup(
                setup_type=setup_type,
                confidence=max(synth_conf, bull_score, 60),
            ),
        )

        promoted = {
            **judge,
            "decision": "approve_trade",
            "ticker": feature_pack.get("ticker", judge.get("ticker")),
            "side": "BUY",
            "strategy": f"tactical_{setup_type}_probe",
            "objective_score": judge.get("objective_score"),
            "expected_edge_score": judge.get("expected_edge_score"),
            "risk_penalty": judge.get("risk_penalty"),
            "cost_penalty": judge.get("cost_penalty"),
            "drawdown_risk": judge.get("drawdown_risk"),
            "execution_friction_penalty": judge.get("execution_friction_penalty"),
            "valid_trade_plan": True,
            "plan_type": trade_plan.get("plan_type"),
            "confidence": max(55, min(82, int(round((synth_conf + bull_score) / 2)))),
            "size_quote": float(probe_size),
            "setup_type": setup_type,
            "reasons": [
                "wait_upgraded_to_small_probe_based_on_tactical_setup",
                f"setup_type={setup_type}",
                f"synth_conf={synth_conf}",
                f"bull_score={bull_score}",
                f"bear_score={bear_score}",
                f"vol_15m={vol_15m:.2f}",
                f"vol_1h={vol_1h:.2f}",
                f"rsi_1h={rsi_1h:.2f}",
                f"rsi_4h={rsi_4h:.2f}",
                "probe_is_small_and_requires_cleaner_confirmation_than_before",
            ],
            "must_reject_if": [
                "hard risk gate rejects size or balance",
                "price loses key range floor before execution",
                "market becomes trading_disabled or cancel_only",
            ],
        }
        promoted["judge_decision"] = promoted["decision"]
        promoted["judge_reasons"] = list(promoted["reasons"])
        return promoted

    def _run_deepseek_preprocess(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.deepseek is None:
            return {
                "generated_at": self._now_iso(),
                "fallback": True,
                "fallback_reason": "deepseek_preprocess_disabled_gpt_nano_gate_primary",
                "regime_hints": {},
                "trend_hints": {},
                "breakout_hints": {},
                "meanrev_hints": {},
                "risk_hints": {},
                "concise_evidence": {},
                "raw_pattern_hints": {},
                "news_sentiment_hints": {},
                "uncertainties": {
                    "deepseek_disabled": True,
                    "primary_gate_model": getattr(self, "entry_gate_model", "gpt_nano"),
                },
            }

        try:
            return self.deepseek.json_chat(
                DEEPSEEK_PREPROCESS_PROMPT,
                feature_pack,
                ticker=ticker,
                stage="deepseek_preprocess",
                allowed_keys=MODULE_ALLOWED_KEYS["deepseek_preprocess"],
                require_all_keys=True,
                max_retries=1,
            )
        except Exception as e:
            return {
                "generated_at": self._now_iso(),
                "fallback": True,
                "fallback_reason": f"deepseek_failed: {e}",
                "regime_hints": {},
                "trend_hints": {},
                "breakout_hints": {},
                "meanrev_hints": {},
                "risk_hints": {},
                "concise_evidence": {},
                "raw_pattern_hints": {},
                "news_sentiment_hints": {},
                "uncertainties": {
                    "deepseek_error": str(e)
                },
            }

    def _build_position_plan_snapshot_from_analysis(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        synth = analysis.get("synth", {})
        judge = analysis.get("judge", {})
        feature_pack = analysis.get("feature_pack", {})
        entry_gate = analysis.get("entry_gate", {})

        return {
            "created_at": self._now_iso(),
            "ticker": analysis.get("ticker"),
            "setup_type": judge.get("setup_type") or entry_gate.get("setup_type") or "unclear",
            "strategy": judge.get("strategy"),
            "judge_confidence": judge.get("confidence"),
            "entry_gate_decision": entry_gate.get("decision"),
            "entry_gate_confidence": entry_gate.get("confidence"),
            "primary_thesis": synth.get("primary_thesis"),
            "why_now": synth.get("why_now"),
            "key_trigger": synth.get("key_trigger"),
            "invalidation": synth.get("invalidation"),
            "risk_reward_comment": synth.get("risk_reward_comment"),
            "entry_mid_price": feature_pack.get("market", {}).get("mid_price"),
        }

    def _risk_profile_for_setup(self, setup_type: str) -> Dict[str, Any]:
        normalized = self._normalize_setup_type(setup_type)
        if normalized == "trend_continuation":
            return {
                "stop_mult": Decimal("0.97"),
                "reward_mult": Decimal("2.0"),
                "trailing_trigger_pct": Decimal("0.025"),
                "trailing_distance_pct": Decimal("0.035"),
                "invalidation_mode": "ema20_break",
            }
        if normalized == "reclaim_reversal":
            return {
                "stop_mult": Decimal("0.975"),
                "reward_mult": Decimal("1.6"),
                "trailing_trigger_pct": Decimal("0.018"),
                "trailing_distance_pct": Decimal("0.03"),
                "invalidation_mode": "ema20_break",
            }
        return {
            "stop_mult": Decimal("0.982"),
            "reward_mult": Decimal("1.25"),
            "trailing_trigger_pct": Decimal("0.012"),
            "trailing_distance_pct": Decimal("0.022"),
            "invalidation_mode": "range_low_break",
        }

    def _build_initial_position_risk_fields(
        self,
        analysis: Dict[str, Any],
        entry_price: Decimal,
    ) -> Dict[str, Any]:
        if entry_price <= Decimal("0"):
            return {}

        feature_pack = analysis.get("feature_pack", {})
        indicators = feature_pack.get("indicators", {})
        i1h = indicators.get("1h", {})
        structure = feature_pack.get("structure", {}) or {}
        entry_gate = analysis.get("entry_gate", {})
        judge = analysis.get("judge", {})

        setup_type = judge.get("setup_type") or entry_gate.get("setup_type") or "trend_continuation"
        profile = self._risk_profile_for_setup(str(setup_type))

        atr_1h = self._to_decimal(i1h.get("atr_14"), "0")
        ema20_1h = self._to_decimal(i1h.get("ema_20"), "0")
        ema50_1h = self._to_decimal(i1h.get("ema_50"), "0")
        bb_mid_1h = self._to_decimal(i1h.get("bb_mid"), "0")

        support_candidates = []
        for key in ["support_1h", "nearest_support", "range_low", "swing_low_1h", "last_higher_low_1h"]:
            value = self._to_decimal(structure.get(key), "0")
            if value > Decimal("0") and value < entry_price:
                support_candidates.append(value)

        for value in [ema20_1h, ema50_1h]:
            if value > Decimal("0") and value < entry_price:
                support_candidates.append(value)

        if atr_1h > Decimal("0"):
            atr_floor = entry_price - (atr_1h * Decimal("1.2"))
            if atr_floor > Decimal("0") and atr_floor < entry_price:
                support_candidates.append(atr_floor)

        fallback_stop = entry_price * profile["stop_mult"]
        support_candidates.append(fallback_stop)
        stop_price = max(support_candidates) if support_candidates else fallback_stop
        if stop_price >= entry_price:
            stop_price = fallback_stop
        stop_price = max(stop_price, fallback_stop)

        risk_distance = entry_price - stop_price
        if risk_distance <= Decimal("0"):
            risk_distance = entry_price * (Decimal("1") - profile["stop_mult"])

        take_profit_price = entry_price + (risk_distance * profile["reward_mult"])
        if self._normalize_setup_type(setup_type) == "mean_reversion" and bb_mid_1h > entry_price:
            take_profit_price = min(take_profit_price, bb_mid_1h)

        return {
            "stop_price": str(stop_price),
            "take_profit_price": str(take_profit_price),
            "trailing_trigger_pct": str(profile["trailing_trigger_pct"]),
            "trailing_distance_pct": str(profile["trailing_distance_pct"]),
            "invalidation_mode": str(profile["invalidation_mode"]),
            "position_plan_status": "initialized_from_analysis",
            "position_plan_version": 2,
        }

    def _run_full_analysis_stack(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        deepseek_pack: Dict[str, Any],
        entry_gate: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
        pending_trade_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        feature_pack = self._inject_execution_context(ticker, feature_pack)
        chart_patterns = build_chart_pattern_context(feature_pack)
        recent_reflections = self._build_recent_reflection_summary(ticker)
        decision_outcomes = self._build_decision_outcome_summary(ticker)
        pending_trade_plan = pending_trade_plan or self._build_pending_trade_plan_context(ticker, feature_pack)

        dossier = {
            "feature_pack": feature_pack,
            "deepseek_pack": deepseek_pack,
            "chart_patterns": chart_patterns,
            "recent_reflections": recent_reflections,
            "decision_outcomes": decision_outcomes,
            "pending_trade_plan": pending_trade_plan,
        }

        regime = self._safe_module_response(REGIME_PROMPT, dossier, "regime", ticker)
        trend = self._safe_module_response(TREND_PROMPT, dossier, "trend", ticker)
        breakout = self._safe_module_response(BREAKOUT_PROMPT, dossier, "breakout", ticker)
        meanrev = self._safe_module_response(MEANREV_PROMPT, dossier, "meanrev", ticker)
        bull = self._safe_module_response(BULL_PROMPT, dossier, "bull", ticker)
        bear = self._safe_module_response(BEAR_PROMPT, dossier, "bear", ticker)

        synth = self._safe_module_response(
            SYNTH_PROMPT,
            {
                **dossier,
                "regime": regime,
                "trend": trend,
                "breakout": breakout,
                "meanrev": meanrev,
                "bull": bull,
                "bear": bear,
            },
            "synth",
            ticker,
        )

        judge_base_input = {
            **dossier,
            "regime": regime,
            "trend": trend,
            "breakout": breakout,
            "meanrev": meanrev,
            "bull": bull,
            "bear": bear,
            "synth": synth,
            "existing_position": existing_position or {},
        }

        should_call_judge, judge_gate_reasons, judge_gate_metrics = self._should_call_expensive_judge(
            judge_input=judge_base_input,
            existing_position=existing_position,
        )

        if should_call_judge:
            planner_input = build_trade_planner_input(
                ticker=ticker,
                feature_pack=feature_pack,
                deepseek_pack=deepseek_pack,
                chart_patterns=chart_patterns,
                regime=regime,
                trend=trend,
                breakout=breakout,
                meanrev=meanrev,
                bull=bull,
                bear=bear,
                synth=synth,
                existing_position=existing_position,
                recent_reflections=recent_reflections,
                decision_outcomes=decision_outcomes,
                pending_trade_plan=pending_trade_plan,
            )
            trade_plan = self._run_trade_planner_with_fallback(planner_input, ticker)
            plan_quote = (
                trade_plan.get("max_quote_size")
                or trade_plan.get("max_size_quote")
                or trade_plan.get("size_quote")
                or feature_pack.get("decision_context", {}).get("execution_feasibility", {}).get("estimated_quote")
            )
            plan_price = (
                trade_plan.get("preferred_limit_price")
                or trade_plan.get("entry_price")
                or trade_plan.get("trigger_price")
                or feature_pack.get("decision_context", {}).get("execution_feasibility", {}).get("normalized_price")
            )
            feature_pack.setdefault("decision_context", {})["execution_feasibility"] = execution_feasibility_context(
                ticker,
                plan_quote,
                plan_price,
                self._feature_pack_exchange_rules(feature_pack),
                max_quote_size=getattr(self.cfg, "phase_c_max_order_quote", self.max_trade_quote_usdc),
            )
            judge_input = {
                **judge_base_input,
                "feature_pack": feature_pack,
                "trade_plan": trade_plan,
                "product_rules": feature_pack.get("decision_context", {}).get("product_rules", {}),
                "recent_exchange_rejections": feature_pack.get("decision_context", {}).get("recent_exchange_rejections", []),
                "execution_feasibility": feature_pack.get("decision_context", {}).get("execution_feasibility", {}),
            }
            judge = self._judge_with_fallback(judge_input)
            judge.setdefault("reasons", [])
            judge["reasons"].extend(judge_gate_reasons)
            judge["expensive_judge_called"] = True
            judge["judge_decision"] = judge.get("decision")
            judge["judge_reasons"] = list(judge.get("reasons") or [])
            valid_trade_plan = is_valid_entry_trade_plan(trade_plan)
            trade_plan["valid_trade_plan"] = valid_trade_plan
            judge["valid_trade_plan"] = valid_trade_plan
            judge["plan_type"] = trade_plan.get("plan_type")
            judge["setup_type"] = judge.get("setup_type") or trade_plan.get("setup_type")
            for objective_key in (
                "objective_score",
                "expected_edge_score",
                "risk_penalty",
                "cost_penalty",
                "drawdown_risk",
                "execution_friction_penalty",
            ):
                judge.setdefault(objective_key, None)
            judge["missing_objective_score"] = judge.get("objective_score") is None
            judge["preselection"] = judge_gate_metrics
            if not valid_trade_plan and judge.get("decision") == "approve_trade":
                judge["decision"] = "wait"
                judge["side"] = "NONE"
                judge["size_quote"] = 0.0
                judge.setdefault("reasons", []).append("approve_trade_blocked_because_trade_plan_is_invalid")
            if not judge.get("judge_response_valid_trade_plan", False) and judge.get("decision") == "approve_trade":
                judge["decision"] = "wait"
                judge["side"] = "NONE"
                judge["size_quote"] = 0.0
                judge.setdefault("reasons", []).append("approve_trade_blocked_because_judge_response_valid_trade_plan_false")
            judge = self._enforce_bull_bear_confidence_gate(judge, judge_input)
            judge["judge_decision"] = judge.get("decision")
            judge["judge_reasons"] = list(judge.get("reasons") or [])
            judge = self._maybe_promote_wait_to_small_probe(
                judge_input=judge_input,
                judge=judge,
                existing_position=existing_position,
            )
        else:
            trade_plan = build_default_no_plan(
                ticker=ticker,
                reason="Trade planner skipped because expensive judge gate skipped this setup: " + "; ".join(judge_gate_reasons),
                source="trade_planner_skipped_by_expensive_judge_gate",
            )
            trade_plan["valid_trade_plan"] = False
            trade_plan["preselection_stage"] = judge_gate_metrics.get("preselection_stage", "expensive_judge_gate")
            trade_plan["judge_skip_reason"] = "; ".join(judge_gate_reasons)
            judge_input = {
                **judge_base_input,
                "trade_plan": trade_plan,
            }
            judge = self._build_expensive_judge_skipped_result(
                judge_input=judge_input,
                skip_reasons=judge_gate_reasons,
            )
            judge["expensive_judge_called"] = False
            judge["judge_skip_reason"] = "; ".join(judge_gate_reasons)
            judge["preselection_stage"] = judge_gate_metrics.get("preselection_stage", "expensive_judge_gate")
            judge["top_blocker"] = judge_gate_metrics.get("top_blocker") or (judge_gate_reasons[0] if judge_gate_reasons else "")
            judge["would_have_been_candidate_if_preselection_relaxed"] = bool(judge_gate_metrics.get("would_have_been_candidate_if_preselection_relaxed"))
            judge["valid_trade_plan"] = False
            judge["missing_objective_score"] = True
            judge["preselection"] = judge_gate_metrics

        result = {
            "ticker": ticker,
            "generated_at": self._now_iso(),
            "feature_pack": feature_pack,
            "deepseek_pack": deepseek_pack,
            "entry_gate": entry_gate,
            "chart_patterns": chart_patterns,
            "recent_reflections": recent_reflections,
            "decision_outcomes": decision_outcomes,
            "pending_trade_plan": pending_trade_plan,
            "regime": regime,
            "trend": trend,
            "breakout": breakout,
            "meanrev": meanrev,
            "bull": bull,
            "bear": bear,
            "synth": synth,
            "trade_plan": trade_plan,
            "judge": judge,
        }

        self._write_jsonl("analysis.jsonl", result)
        return result

    def analyze_ticker(
        self,
        ticker: str,
        feature_pack_override: Optional[Dict[str, Any]] = None,
        existing_position: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raw_feature_pack = feature_pack_override or self.market.build_feature_pack(ticker)
        feature_pack = self._apply_closed_candle_sanitization(raw_feature_pack)

        feature_pack.setdefault("decision_context", {})["live_learning"] = self.learning_context
        feature_pack = self._inject_execution_context(ticker, feature_pack)
        feature_pack = self._inject_market_intelligence_context(feature_pack)
        feature_pack = self._inject_neural_shadow_context(ticker, feature_pack)
        feature_pack.setdefault("risk_context", {})["engine_state"] = self._build_risk_state(ticker)
        feature_pack.setdefault("risk_context", {})["spot_constraints"] = self._build_spot_constraints()

        deepseek_pack = self._run_deepseek_preprocess(ticker, feature_pack)

        has_open_position = bool(existing_position) and str(existing_position.get("status", "open")).lower() == "open"

        if not has_open_position:
            entry_gate = self._run_entry_gate(ticker, feature_pack, deepseek_pack)
            if entry_gate["decision"] in {"skip", "watch"}:
                return self._build_skip_analysis_result(ticker, feature_pack, deepseek_pack, entry_gate)
        else:
            entry_gate = {
                "generated_at": self._now_iso(),
                "ticker": ticker,
                "decision": "position_management_bypass",
                "priority": "high",
                "setup_type": "unclear",
                "confidence": 100,
                "reasons": ["existing_open_position_bypasses_entry_gate"],
                "warnings": [],
            }
            feature_pack["entry_gate"] = entry_gate
            feature_pack["risk_context"]["entry_gate"] = entry_gate

        return self._run_full_analysis_stack(
            ticker=ticker,
            feature_pack=feature_pack,
            deepseek_pack=deepseek_pack,
            entry_gate=entry_gate,
            existing_position=existing_position,
        )

    def _unique_tickers(self, values: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for value in values:
            t = str(value or "").upper().strip()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out

    def _cheap_prefilter_candidate(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        breadth_context: Optional[Dict[str, Any]] = None,
        watch_memory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        market = feature_pack.get("market", {})
        indicators = feature_pack.get("indicators", {})
        structure = feature_pack.get("structure", {})
        micro = feature_pack.get("microstructure", {})

        price = self._to_float(market.get("mid_price"), 0.0)

        i15 = indicators.get("15m", {})
        i1h = indicators.get("1h", {})
        i4h = indicators.get("4h", {})
        i1d = indicators.get("1d", {})

        rsi_15m = self._to_float(i15.get("rsi_14"), 50.0)
        rsi_1h = self._to_float(i1h.get("rsi_14"), 50.0)
        rsi_4h = self._to_float(i4h.get("rsi_14"), 50.0)
        rsi_1d = self._to_float(i1d.get("rsi_14"), 50.0)

        ema20_1h = self._to_float(i1h.get("ema_20"), 0.0)
        ema50_1h = self._to_float(i1h.get("ema_50"), 0.0)
        ema50_4h = self._to_float(i4h.get("ema_50"), 0.0)
        ema200_4h = self._to_float(i4h.get("ema_200"), 0.0)
        ema50_1d = self._to_float(i1d.get("ema_50"), 0.0)
        ema200_1d = self._to_float(i1d.get("ema_200"), 0.0)

        donch_low_1h = self._to_float(i1h.get("donchian_20_low"), 0.0)
        donch_high_1h = self._to_float(i1h.get("donchian_20_high"), 0.0)

        vol_15m = self._to_float(micro.get("15m", {}).get("volume_vs_avg"), 0.0)
        vol_1h = self._to_float(micro.get("1h", {}).get("volume_vs_avg"), 0.0)
        latest_volume_15m = self._to_float(micro.get("15m", {}).get("latest_volume"), 0.0)
        avg_volume_15m = self._to_float(micro.get("15m", {}).get("avg_volume"), 0.0)

        higher_highs_1h = bool(structure.get("higher_highs_1h", False))
        higher_lows_1h = bool(structure.get("higher_lows_1h", False))
        lower_highs_1h = bool(structure.get("lower_highs_1h", False))
        lower_lows_1h = bool(structure.get("lower_lows_1h", False))
        compression_detected = bool(structure.get("compression_detected", False))

        setup_guess = "unclear"
        score = 0
        reasons: List[str] = []
        warnings: List[str] = []

        breadth_context = breadth_context if isinstance(breadth_context, dict) else {}
        watch_memory = watch_memory if isinstance(watch_memory, dict) else {}
        breadth_risk_on = bool(breadth_context.get("risk_on", False))
        consecutive_constructive_watches = int(watch_memory.get(ticker, {}).get("consecutive_constructive_watches", 0)) if isinstance(watch_memory.get(ticker, {}), dict) else 0

        bearish_htf = (
            ema50_4h > 0 and ema200_4h > 0 and ema50_4h < ema200_4h
        ) or (
            ema50_1d > 0 and ema200_1d > 0 and ema50_1d < ema200_1d
        )

        bullish_continuation = (
            ema20_1h > 0
            and ema50_1h > 0
            and price > ema20_1h >= ema50_1h
            and higher_lows_1h
        )

        if bullish_continuation:
            setup_guess = "trend_continuation"
            score += 70
            reasons.append("cheap_prefilter: bullish continuation structure detected")

        price_above_1h_ema20 = ema20_1h > 0 and price >= ema20_1h
        compression_with_pressure = False

        if compression_detected:
            score += 10
            reasons.append("cheap_prefilter: compression detected")

        near_support = False
        range_pos = 0.5
        if donch_low_1h > 0 and donch_high_1h > donch_low_1h:
            width = max(donch_high_1h - donch_low_1h, 1e-9)
            range_pos = (price - donch_low_1h) / width
            near_support = range_pos <= 0.22

        oversold = rsi_15m <= 35 or rsi_1h <= 35 or rsi_4h <= 38
        very_oversold = rsi_15m <= 28 or rsi_1h <= 30 or rsi_4h <= 34
        weak_volume = vol_15m < 0.9 and vol_1h < 0.75
        capitulation_like = avg_volume_15m > 0 and latest_volume_15m >= (avg_volume_15m * 1.8)

        if near_support and oversold:
            score += 18
            reasons.append("cheap_prefilter: near support with oversold context")

        if very_oversold:
            score += 8
            reasons.append("cheap_prefilter: very oversold short-term conditions")

        if capitulation_like:
            score += 6
            reasons.append("cheap_prefilter: local volume spike may indicate exhaustion")

        if near_support and oversold and compression_detected:
            setup_guess = "mean_reversion"

        compression_with_pressure = (
            compression_detected
            and range_pos >= 0.62
            and (vol_15m >= 0.95 or vol_1h >= 0.85)
            and (higher_lows_1h or higher_highs_1h or price_above_1h_ema20)
        )
        if compression_with_pressure:
            setup_guess = "trend_continuation" if not bearish_htf else "reclaim_reversal"
            score += 18
            reasons.append("cheap_prefilter: compression with pressure near range highs")

        if higher_lows_1h and not bearish_htf and vol_15m >= 0.9:
            score += 12
            reasons.append("cheap_prefilter: constructive stabilization")

        if breadth_risk_on and compression_detected and (higher_lows_1h or higher_highs_1h or price_above_1h_ema20):
            score += 10
            reasons.append("cheap_prefilter: market breadth supports tactical long scan")

        if consecutive_constructive_watches > 0 and (compression_detected or higher_lows_1h or higher_highs_1h):
            score += min(12, consecutive_constructive_watches * 6)
            reasons.append("cheap_prefilter: prior constructive watch memory boosts candidate")

        if lower_highs_1h and lower_lows_1h:
            score -= 20
            warnings.append("cheap_prefilter: active 1h downtrend structure")

        if bearish_htf:
            htf_penalty = 10 if (compression_with_pressure or breadth_risk_on) else 15
            score -= htf_penalty
            warnings.append("cheap_prefilter: bearish higher timeframe structure")
            if compression_with_pressure or breadth_risk_on:
                reasons.append("cheap_prefilter: bearish HTF downgraded to size/risk warning due to local strength")

        if weak_volume:
            weak_volume_penalty = 4 if compression_with_pressure else 10
            score -= weak_volume_penalty
            warnings.append("cheap_prefilter: weak participation")

        if 0.35 <= range_pos <= 0.65 and setup_guess == "mean_reversion":
            score -= 14
            warnings.append("cheap_prefilter: mean reversion is mid-range")

        if not near_support and setup_guess == "mean_reversion":
            score -= 8
            warnings.append("cheap_prefilter: mean reversion not close enough to support")

        if setup_guess == "unclear" and near_support and oversold:
            setup_guess = "mean_reversion"

        if score >= 60:
            prefilter_decision = "consider_high"
        elif score >= 40:
            prefilter_decision = "consider"
        elif score >= 22:
            prefilter_decision = "watchlist"
        else:
            prefilter_decision = "skip"

        return {
            "ticker": ticker,
            "prefilter_score": int(score),
            "prefilter_decision": prefilter_decision,
            "setup_guess": setup_guess,
            "near_support": near_support,
            "range_pos": round(range_pos, 4),
            "bearish_htf": bearish_htf,
            "oversold": oversold,
            "very_oversold": very_oversold,
            "weak_volume": weak_volume,
            "compression_with_pressure": compression_with_pressure,
            "breadth_risk_on": breadth_risk_on,
            "consecutive_constructive_watches": consecutive_constructive_watches,
            "reasons": reasons,
            "warnings": warnings,
        }

    def _gate_rank_score(
        self,
        prefilter: Dict[str, Any],
        entry_gate: Dict[str, Any],
    ) -> int:
        score = int(prefilter.get("prefilter_score", 0))

        decision = str(entry_gate.get("decision", "watch")).lower()
        priority = str(entry_gate.get("priority", "normal")).lower()
        confidence = self._extract_score(entry_gate.get("confidence"), 0)
        setup_type = self._normalize_setup_type(entry_gate.get("setup_type"))

        if decision == "priority_analyze":
            score += 40
        elif decision == "analyze":
            score += 25
        elif decision == "watch":
            score += 5
        elif decision == "skip":
            score -= 25

        if priority == "high":
            score += 12
        elif priority == "low":
            score -= 5

        if setup_type == "trend_continuation":
            score += 20
        elif setup_type == "reclaim_reversal":
            score += 10
        elif setup_type == "mean_reversion":
            score += 2

        score += min(confidence // 5, 15)
        return int(score)

    def _watch_candidate_is_strong_enough_for_full_analysis(
        self,
        feature_pack: Dict[str, Any],
        prefilter: Dict[str, Any],
        entry_gate: Dict[str, Any],
        gate_rank: int,
    ) -> bool:
        decision = str(entry_gate.get("decision", "watch")).lower()
        if decision != "watch":
            return False

        setup_type = self._normalize_setup_type(entry_gate.get("setup_type"))
        confidence = self._extract_score(entry_gate.get("confidence"), 0)
        prefilter_score = int(prefilter.get("prefilter_score", 0))
        breadth_risk_on = bool(feature_pack.get("decision_context", {}).get("market_breadth", {}).get("risk_on", False))
        consecutive_constructive_watches = int(prefilter.get("consecutive_constructive_watches", 0))

        indicators = feature_pack.get("indicators", {})
        structure = feature_pack.get("structure", {})
        micro = feature_pack.get("microstructure", {})
        market = feature_pack.get("market", {})

        i15 = indicators.get("15m", {})
        i1h = indicators.get("1h", {})
        i4h = indicators.get("4h", {})

        price = self._to_float(market.get("mid_price"), 0.0)
        donch_low_1h = self._to_float(i1h.get("donchian_20_low"), 0.0)
        donch_high_1h = self._to_float(i1h.get("donchian_20_high"), 0.0)

        rsi_15m = self._to_float(i15.get("rsi_14"), 50.0)
        rsi_1h = self._to_float(i1h.get("rsi_14"), 50.0)
        rsi_4h = self._to_float(i4h.get("rsi_14"), 50.0)

        ema20_15m = self._to_float(i15.get("ema_20"), 0.0)
        ema20_1h = self._to_float(i1h.get("ema_20"), 0.0)
        ema50_1h = self._to_float(i1h.get("ema_50"), 0.0)

        vol_15m = self._to_float(micro.get("15m", {}).get("volume_vs_avg"), 0.0)
        vol_1h = self._to_float(micro.get("1h", {}).get("volume_vs_avg"), 0.0)

        higher_lows_1h = bool(structure.get("higher_lows_1h", False))
        higher_highs_1h = bool(structure.get("higher_highs_1h", False))
        compression_detected = bool(structure.get("compression_detected", False))

        near_support = False
        range_pos = 0.5
        if donch_low_1h > 0 and donch_high_1h > donch_low_1h and price > 0:
            width = max(donch_high_1h - donch_low_1h, 1e-9)
            range_pos = (price - donch_low_1h) / width
            near_support = range_pos <= 0.28

        price_above_15m_ema = ema20_15m > 0 and price >= ema20_15m
        recovering_on_short_tf = price_above_15m_ema or vol_15m >= 1.0
        oversold_context = rsi_15m <= 34 or rsi_1h <= 38 or rsi_4h <= 35

        if setup_type == "trend_continuation":
            return (
                gate_rank >= (56 if breadth_risk_on else 60)
                and confidence >= 35
                and prefilter_score >= (36 if breadth_risk_on else 40)
                and higher_lows_1h
                and (higher_highs_1h or price >= ema20_1h > 0)
                and (vol_15m >= 0.8 or breadth_risk_on)
            )

        if setup_type == "reclaim_reversal":
            return (
                gate_rank >= (54 if breadth_risk_on else 58)
                and confidence >= 33
                and prefilter_score >= (34 if breadth_risk_on else 38)
                and (higher_lows_1h or consecutive_constructive_watches >= 1)
                and recovering_on_short_tf
                and compression_detected
            )

        if setup_type == "mean_reversion":
            return (
                gate_rank >= 55
                and confidence >= 30
                and prefilter_score >= 35
                and near_support
                and oversold_context
                and compression_detected
                and recovering_on_short_tf
                and (higher_lows_1h or vol_15m >= 1.1 or vol_1h >= 0.7)
                and range_pos <= 0.42
            )

        return False

    def _scan_market_universe(
        self,
        tickers: List[str],
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        feature_packs: Dict[str, Dict[str, Any]] = {}
        errors: List[Dict[str, Any]] = []

        for ticker in tickers:
            try:
                raw_feature_pack = self.market.build_feature_pack(ticker)
                feature_pack = self._apply_closed_candle_sanitization(raw_feature_pack)
                feature_pack = self._inject_market_intelligence_context(feature_pack)
                feature_pack.setdefault("risk_context", {})["engine_state"] = self._build_risk_state(ticker)
                feature_pack.setdefault("risk_context", {})["spot_constraints"] = self._build_spot_constraints()
                feature_pack = self._inject_neural_shadow_context(ticker, feature_pack)
                feature_packs[ticker] = feature_pack
            except Exception as e:
                errors.append(self._log_error(ticker, e))

        return feature_packs, errors

    def _suppress_repeated_partial_take_profit_action(
        self,
        ticker: str,
        position: Dict[str, Any],
        action: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Prevent repeated partial profit-taking on the same residual position.

        PositionManager can correctly emit a reduce/take_profit_hit action when TP
        is reached. The state flag partial_take_profit_taken must then survive
        later inventory refreshes. This guard is a second line of defense: if the
        flag is already true, convert another normal take-profit reduce into hold.
        Risk-driven closes/reduces are not suppressed.
        """
        if not isinstance(action, dict):
            return action

        action_type = str(action.get("action", "hold")).strip().lower()
        reason = str(action.get("reason", "")).strip().lower()
        already_taken = bool(position.get("partial_take_profit_taken", False))

        if action_type == "reduce" and reason == "take_profit_hit" and already_taken:
            return {
                "action": "hold",
                "reason": "partial_take_profit_already_taken",
                "side": "NONE",
                "size_base": "0",
                "size_quote": "0",
                "stop_price": str(position.get("stop_price", "0")),
                "take_profit_price": str(position.get("take_profit_price", "0")),
                "trailing_active": bool(position.get("trailing_active", False)),
                "metadata": {
                    "ticker": ticker,
                    "suppressed_action": action,
                    "updated_position": position,
                },
            }

        return action

    def _boolish(self, value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "y"}
        return default

    def _coerce_list_of_strings(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value]
        return [str(value)]

    def _extract_runner_plan(self, judge: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(judge, dict):
            return {}
        plan = judge.get("runner_plan", {})
        return plan if isinstance(plan, dict) else {}

    def _feature_current_price(self, feature_pack: Dict[str, Any], action: Optional[Dict[str, Any]] = None) -> Decimal:
        metadata = (action or {}).get("metadata", {}) if isinstance(action, dict) else {}
        return self._to_decimal(
            metadata.get("current_price")
            or feature_pack.get("market", {}).get("mid_price")
            or feature_pack.get("market", {}).get("best_bid")
            or feature_pack.get("market", {}).get("best_ask"),
            "0",
        )

    def _position_unrealized_pnl_pct(
        self,
        position: Dict[str, Any],
        current_price: Decimal,
    ) -> Decimal:
        entry_price = self._to_decimal(position.get("entry_price"), "0")
        if entry_price <= Decimal("0") or current_price <= Decimal("0"):
            return Decimal("0")
        return (current_price - entry_price) / entry_price

    def _max_adx_from_feature_pack(self, feature_pack: Dict[str, Any]) -> Decimal:
        indicators = feature_pack.get("indicators", {}) or {}
        values: List[Decimal] = []
        for timeframe in ("15m", "1h", "4h"):
            tf = indicators.get(timeframe, {}) or {}
            for key in ("adx_14", "adx", "adx14"):
                value = self._to_decimal(tf.get(key), "0")
                if value > Decimal("0"):
                    values.append(value)
        return max(values) if values else Decimal("0")

    def _trend_context_supports_runner(
        self,
        feature_pack: Dict[str, Any],
        current_price: Decimal,
    ) -> Tuple[bool, Dict[str, Any]]:
        indicators = feature_pack.get("indicators", {}) or {}
        structure = feature_pack.get("structure", {}) or {}
        i1h = indicators.get("1h", {}) or {}
        i4h = indicators.get("4h", {}) or {}

        ema20_1h = self._to_decimal(i1h.get("ema_20"), "0")
        ema50_1h = self._to_decimal(i1h.get("ema_50"), "0")
        ema20_4h = self._to_decimal(i4h.get("ema_20"), "0")
        ema50_4h = self._to_decimal(i4h.get("ema_50"), "0")
        adx = self._max_adx_from_feature_pack(feature_pack)
        min_adx = self._to_decimal(getattr(self.cfg, "judge_soft_override_min_adx", Decimal("25")), "25")

        above_1h_fast = bool(current_price > Decimal("0") and ema20_1h > Decimal("0") and current_price >= ema20_1h)
        above_1h_mid = bool(current_price > Decimal("0") and ema50_1h > Decimal("0") and current_price >= ema50_1h)
        above_4h_fast = bool(current_price > Decimal("0") and ema20_4h > Decimal("0") and current_price >= ema20_4h)
        above_4h_mid = bool(current_price > Decimal("0") and ema50_4h > Decimal("0") and current_price >= ema50_4h)

        higher_lows_1h = bool(structure.get("higher_lows_1h", False))
        higher_highs_1h = bool(structure.get("higher_highs_1h", False))
        lower_highs_1h = bool(structure.get("lower_highs_1h", False))
        lower_lows_1h = bool(structure.get("lower_lows_1h", False))
        adverse_structure = lower_highs_1h and lower_lows_1h and not higher_lows_1h

        trend_ok = (
            adx >= min_adx
            and not adverse_structure
            and (
                above_1h_fast
                or above_1h_mid
                or above_4h_fast
                or above_4h_mid
                or higher_lows_1h
                or higher_highs_1h
            )
        )

        return trend_ok, {
            "adx_max": str(adx),
            "min_adx": str(min_adx),
            "above_1h_fast": above_1h_fast,
            "above_1h_mid": above_1h_mid,
            "above_4h_fast": above_4h_fast,
            "above_4h_mid": above_4h_mid,
            "higher_lows_1h": higher_lows_1h,
            "higher_highs_1h": higher_highs_1h,
            "adverse_structure": adverse_structure,
        }

    def _judge_supports_runner_hold(
        self,
        judge: Optional[Dict[str, Any]],
        feature_pack: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        if not isinstance(judge, dict):
            return False, {"reason": "judge_missing"}

        decision = self._normalize_decision(judge)
        side = self._normalize_side(judge)
        confidence = self._extract_score(judge.get("confidence"), 0)
        min_confidence = int(getattr(self.cfg, "judge_soft_override_min_confidence", 65))
        setup_type = self._normalize_setup_type(judge.get("setup_type") or feature_pack.get("entry_gate", {}).get("setup_type"))
        strategy = str(judge.get("strategy", "")).strip().lower()
        position_action = str(judge.get("position_action", "")).strip().lower()
        soft_rule_override = self._boolish(judge.get("soft_rule_override"), False)
        override_rules = self._coerce_list_of_strings(judge.get("override_rules", []))

        bullish_decision = (
            decision in {"wait", "approve_trade"}
            and side in {"NONE", "BUY"}
        )
        runner_intent = (
            position_action in {"hold", "hold_runner", "let_runner_run", "none"}
            or soft_rule_override
            or "runner" in strategy
            or "trend" in strategy
            or "continuation" in strategy
        )
        setup_ok = setup_type in {"trend_continuation", "reclaim_reversal", "unclear"}

        ok = bool(
            confidence >= min_confidence
            and bullish_decision
            and runner_intent
            and setup_ok
        )

        return ok, {
            "decision": decision,
            "side": side,
            "confidence": confidence,
            "min_confidence": min_confidence,
            "setup_type": setup_type,
            "strategy": strategy,
            "position_action": position_action,
            "soft_rule_override_requested": soft_rule_override,
            "override_rules": override_rules,
            "bullish_decision": bullish_decision,
            "runner_intent": runner_intent,
            "setup_ok": setup_ok,
        }

    def _is_soft_exit_action(
        self,
        action: Dict[str, Any],
        position: Dict[str, Any],
        pnl_pct: Decimal,
    ) -> Tuple[bool, Dict[str, Any]]:
        action_type = str(action.get("action", "hold")).strip().lower()
        reason = str(action.get("reason", "")).strip().lower()
        trailing_active = bool(action.get("trailing_active") or position.get("trailing_active"))

        always_soft = {
            "take_profit_hit",
            "rsi_overextended_take_partial",
            "meanrev_overextended_take_partial",
            "profit_giveback_reduce_risk",
        }
        soft_if_profitable = {
            "stop_loss_hit",
            "tighten_risk_near_stop",
            "invalidation_ema20_break",
        }
        hard_reasons = {
            "urgent_stop_breached",
            "near_stop_with_bearish_confirmation",
            "repeated_warnings_with_structure_breakdown",
            "profit_giveback_with_bearish_followthrough",
            "structure_breakdown_1h",
            "invalidation_ema50_break",
        }

        if action_type not in {"reduce", "close"}:
            return False, {"reason": "not_a_sell_action", "action_type": action_type}
        if reason in hard_reasons:
            return False, {"reason": "hard_exit_reason", "exit_reason": reason}
        if reason in always_soft:
            return True, {"reason": "soft_profit_rule", "exit_reason": reason}
        if reason in soft_if_profitable and pnl_pct > Decimal("0"):
            # A profitable stop_loss_hit is normally a trailing-profit stop, not a true loss stop.
            return True, {
                "reason": "profitable_soft_or_trailing_exit",
                "exit_reason": reason,
                "trailing_active": trailing_active,
            }
        return False, {"reason": "exit_reason_not_soft", "exit_reason": reason, "pnl_pct": str(pnl_pct)}

    def _log_judge_exit_conflict(
        self,
        *,
        ticker: str,
        judge: Optional[Dict[str, Any]],
        original_action: Dict[str, Any],
        final_action: Dict[str, Any],
        applied: bool,
        reasons: List[str],
        diagnostics: Dict[str, Any],
    ) -> None:
        if not getattr(self.cfg, "judge_conflict_logging_enabled", True):
            return
        try:
            self._write_jsonl(
                "judge_conflicts.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "judge_exit_conflict": True,
                    "soft_override_applied": bool(applied),
                    "reasons": [str(r) for r in reasons],
                    "diagnostics": diagnostics,
                    "judge_summary": self._judge_summary(judge or {}),
                    "judge_position_action": (judge or {}).get("position_action"),
                    "judge_soft_rule_override": (judge or {}).get("soft_rule_override"),
                    "judge_override_rules": (judge or {}).get("override_rules", []),
                    "runner_plan": (judge or {}).get("runner_plan", {}),
                    "risk_rule_wanted": {
                        "action": original_action.get("action"),
                        "reason": original_action.get("reason"),
                        "size_base": original_action.get("size_base"),
                    },
                    "final_action": {
                        "action": final_action.get("action"),
                        "reason": final_action.get("reason"),
                        "size_base": final_action.get("size_base"),
                    },
                },
            )
        except Exception:
            # Conflict logging must never block trading.
            return

    def _apply_judge_soft_override_to_position_action(
        self,
        *,
        ticker: str,
        position: Dict[str, Any],
        action: Dict[str, Any],
        feature_pack: Dict[str, Any],
        judge: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Let GPT-5.5 soften *soft* profit exits, never hard safety exits.

        This is intentionally conservative:
        - Only open profitable positions are eligible by default.
        - Only soft/profit-management rules are eligible.
        - A per-position override counter prevents repeatedly ignoring risk.
        - The widened stop is never moved below break-even when an entry price exists.
        """
        if not isinstance(action, dict):
            return action

        action_type = str(action.get("action", "hold")).strip().lower()
        if action_type not in {"reduce", "close"}:
            return action

        original_action = deepcopy(action)
        diagnostics: Dict[str, Any] = {}
        reasons: List[str] = []

        current_price = self._feature_current_price(feature_pack, action)
        pnl_pct = self._position_unrealized_pnl_pct(position, current_price)
        diagnostics["current_price"] = str(current_price)
        diagnostics["pnl_pct"] = str(pnl_pct)

        soft_ok, soft_diag = self._is_soft_exit_action(action, position, pnl_pct)
        diagnostics["soft_exit_check"] = soft_diag
        if not soft_ok:
            return action

        judge_ok, judge_diag = self._judge_supports_runner_hold(judge, feature_pack)
        diagnostics["judge_runner_check"] = judge_diag
        if not judge_ok:
            self._log_judge_exit_conflict(
                ticker=ticker,
                judge=judge,
                original_action=original_action,
                final_action=action,
                applied=False,
                reasons=["judge_does_not_support_runner_hold"],
                diagnostics=diagnostics,
            )
            return action

        trend_ok, trend_diag = self._trend_context_supports_runner(feature_pack, current_price)
        diagnostics["trend_context_check"] = trend_diag
        if not trend_ok:
            self._log_judge_exit_conflict(
                ticker=ticker,
                judge=judge,
                original_action=original_action,
                final_action=action,
                applied=False,
                reasons=["trend_context_not_strong_enough_for_soft_override"],
                diagnostics=diagnostics,
            )
            return action

        if not getattr(self.cfg, "judge_soft_override_enabled", True):
            self._log_judge_exit_conflict(
                ticker=ticker,
                judge=judge,
                original_action=original_action,
                final_action=action,
                applied=False,
                reasons=["judge_soft_override_disabled"],
                diagnostics=diagnostics,
            )
            return action

        if bool(getattr(self.cfg, "judge_soft_override_require_profit", True)) and pnl_pct <= Decimal("0"):
            self._log_judge_exit_conflict(
                ticker=ticker,
                judge=judge,
                original_action=original_action,
                final_action=action,
                applied=False,
                reasons=["position_not_profitable_enough_for_soft_override"],
                diagnostics=diagnostics,
            )
            return action

        runner_plan = self._extract_runner_plan(judge)
        max_count = int(getattr(self.cfg, "judge_soft_override_max_count", 1))
        try:
            if runner_plan.get("max_soft_override_count") is not None:
                max_count = int(runner_plan.get("max_soft_override_count"))
        except Exception:
            pass

        try:
            current_count = int(position.get("judge_soft_override_count", 0) or 0)
        except Exception:
            current_count = 0
        diagnostics["current_soft_override_count"] = current_count
        diagnostics["max_soft_override_count"] = max_count

        if max_count <= 0 or current_count >= max_count:
            self._log_judge_exit_conflict(
                ticker=ticker,
                judge=judge,
                original_action=original_action,
                final_action=action,
                applied=False,
                reasons=["soft_override_count_limit_reached"],
                diagnostics=diagnostics,
            )
            return action

        position_size_base = self._to_decimal(position.get("position_size_base"), "0")
        if position_size_base <= self.position_epsilon_base:
            return action

        partial_fraction = self._to_decimal(
            runner_plan.get("partial_take_profit_fraction"),
            str(getattr(self.cfg, "judge_runner_partial_fraction", Decimal("0.25"))),
        )
        if partial_fraction <= Decimal("0") or partial_fraction >= Decimal("1"):
            partial_fraction = self._to_decimal(getattr(self.cfg, "judge_runner_partial_fraction", Decimal("0.25")), "0.25")
        if partial_fraction <= Decimal("0") or partial_fraction >= Decimal("1"):
            partial_fraction = Decimal("0.25")

        trailing_distance_pct = self._to_decimal(
            runner_plan.get("trailing_distance_pct"),
            str(getattr(self.cfg, "judge_runner_trailing_distance_pct", Decimal("0.045"))),
        )
        if trailing_distance_pct <= Decimal("0") or trailing_distance_pct > Decimal("0.20"):
            trailing_distance_pct = self._to_decimal(getattr(self.cfg, "judge_runner_trailing_distance_pct", Decimal("0.045")), "0.045")
        if trailing_distance_pct <= Decimal("0") or trailing_distance_pct > Decimal("0.20"):
            trailing_distance_pct = Decimal("0.045")

        metadata = dict(action.get("metadata", {}) or {})
        updated_position = dict(metadata.get("updated_position") or position)
        updated_position["judge_soft_override_count"] = current_count + 1
        updated_position["last_judge_soft_override_at"] = self._now_iso()
        updated_position["last_judge_soft_override_reason"] = str(action.get("reason", ""))
        updated_position["last_judge_soft_override_judge_confidence"] = (judge or {}).get("confidence")
        updated_position["last_judge_soft_override_runner_plan"] = runner_plan
        updated_position["trailing_distance_pct"] = str(max(
            self._to_decimal(updated_position.get("trailing_distance_pct"), "0"),
            trailing_distance_pct,
        ))
        updated_position["trailing_active"] = True

        entry_price = self._to_decimal(updated_position.get("entry_price"), "0")
        highest_price_seen = max(
            self._to_decimal(updated_position.get("highest_price_seen"), "0"),
            current_price,
        )
        widened_stop = highest_price_seen * (Decimal("1") - trailing_distance_pct)
        if entry_price > Decimal("0"):
            widened_stop = max(widened_stop, entry_price)
        diagnostics["widened_runner_stop"] = str(widened_stop)
        diagnostics["trailing_distance_pct"] = str(trailing_distance_pct)
        diagnostics["partial_fraction"] = str(partial_fraction)

        if widened_stop > Decimal("0") and current_price > widened_stop:
            # Deliberately allow a lower stop than the old tight trailing stop, but
            # keep it at/above entry if entry is known. This is what gives the
            # runner room while still protecting the trade from turning into a loser.
            updated_position["stop_price"] = str(widened_stop)
            updated_position["highest_price_seen"] = str(highest_price_seen)
        elif action_type == "close":
            self._log_judge_exit_conflict(
                ticker=ticker,
                judge=judge,
                original_action=original_action,
                final_action=action,
                applied=False,
                reasons=["widened_runner_stop_not_below_current_price"],
                diagnostics=diagnostics,
            )
            return action

        metadata.update({
            "updated_position": updated_position,
            "judge_soft_override": {
                "applied": True,
                "original_action": original_action,
                "pnl_pct": str(pnl_pct),
                "trend_context": trend_diag,
                "judge_runner_check": judge_diag,
                "runner_plan": runner_plan,
                "partial_fraction": str(partial_fraction),
                "trailing_distance_pct": str(trailing_distance_pct),
                "widened_runner_stop": str(updated_position.get("stop_price", "0")),
            },
        })

        reason = str(action.get("reason", "soft_exit"))
        if action_type == "reduce":
            requested_size_base = self._to_decimal(action.get("size_base"), "0")
            max_soft_reduce = position_size_base * partial_fraction
            final_reduce = min(requested_size_base, max_soft_reduce)
            if final_reduce <= self.position_epsilon_base:
                final_action = {
                    "action": "hold",
                    "reason": f"{reason}_judge_soft_override_hold_runner",
                    "side": "NONE",
                    "size_base": "0",
                    "size_quote": "0",
                    "stop_price": str(updated_position.get("stop_price", "0")),
                    "take_profit_price": str(updated_position.get("take_profit_price", "0")),
                    "trailing_active": True,
                    "metadata": metadata,
                }
            else:
                final_action = dict(action)
                final_action["reason"] = f"{reason}_judge_soft_override_reduced_partial"
                final_action["size_base"] = str(final_reduce)
                final_action["size_quote"] = str(final_reduce * current_price)
                final_action["metadata"] = metadata
        else:
            close_reason = str(action.get("reason", "")).strip().lower()
            convert_close_to_partial_reasons = {
                "take_profit_hit",
                "rsi_overextended_take_partial",
                "meanrev_overextended_take_partial",
                "profit_giveback_reduce_risk",
            }
            if close_reason in convert_close_to_partial_reasons:
                final_reduce = position_size_base * partial_fraction
                if final_reduce > self.position_epsilon_base and final_reduce < position_size_base:
                    final_action = dict(action)
                    final_action["action"] = "reduce"
                    final_action["reason"] = f"{reason}_judge_soft_override_reduced_partial"
                    final_action["side"] = "SELL"
                    final_action["size_base"] = str(final_reduce)
                    final_action["size_quote"] = str(final_reduce * current_price)
                    final_action["metadata"] = metadata
                else:
                    final_action = dict(action)
            else:
                final_action = {
                    "action": "hold",
                    "reason": f"{reason}_judge_soft_override_hold_runner",
                    "side": "NONE",
                    "size_base": "0",
                    "size_quote": "0",
                    "stop_price": str(updated_position.get("stop_price", "0")),
                    "take_profit_price": str(updated_position.get("take_profit_price", "0")),
                    "trailing_active": True,
                    "metadata": metadata,
                }

        self._log_judge_exit_conflict(
            ticker=ticker,
            judge=judge,
            original_action=original_action,
            final_action=final_action,
            applied=True,
            reasons=["judge_soft_override_applied"],
            diagnostics=diagnostics,
        )
        return final_action


    def _maybe_store_paper_pending_order_intent(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        execution_plan: Optional[Dict[str, Any]] = None,
        cycle_source: str = "strategy_engine",
    ) -> Optional[Dict[str, Any]]:
        """Phase B.6: store paper pending/watchlist order-intents.

        A pending intent is not an order, reserves no balance and never executes.
        It only preserves useful pending_plan_only/watch context so a later
        trigger can promote the ticker to fresh full analysis. The final judge
        and deterministic risk rails remain mandatory.
        """
        if not bool(getattr(self.cfg, "enable_paper_pending_order_intents", True)):
            return None
        try:
            feature_pack = analysis.get("feature_pack", {}) if isinstance(analysis, dict) else {}
            intent = build_pending_intent_from_execution_plan(
                cfg=self.cfg,
                ticker=ticker,
                analysis=analysis,
                execution_plan=execution_plan or {},
                feature_pack=feature_pack,
                cycle_source=cycle_source,
            )
            if intent is None:
                intent = build_watchlist_intent_from_analysis(
                    cfg=self.cfg,
                    ticker=ticker,
                    analysis=analysis,
                    feature_pack=feature_pack,
                    cycle_source=cycle_source,
                )
            if intent is None:
                entry_gate = analysis.get("entry_gate", {}) if isinstance(analysis, dict) else {}
                decision = str((entry_gate or {}).get("decision") or "").strip().lower()
                if decision in {"watch", "analyze", "priority_analyze"}:
                    diagnostics = _watchlist_candidate_diagnostics(
                        cfg=self.cfg,
                        ticker=ticker,
                        analysis=analysis,
                        feature_pack=feature_pack,
                    )
                    self.pending_order_intent_store.append_event(
                        "paper_pending_order_intent_skipped",
                        {
                            "ticker": ticker,
                            "cycle_source": cycle_source,
                            "reason": diagnostics.get("reason"),
                            "diagnostics": diagnostics,
                            "safety_policy": "pending_intent_skip_has_no_live_order_side_effects",
                        },
                    )
                return None
            stored = self.pending_order_intent_store.store_intent(intent)
            return stored
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "paper_pending_order_intents",
                    "cycle_source": cycle_source,
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "safety_policy": "non_fatal_phase_b6_no_live_order_side_effects",
                },
            )
            return None

    def _review_paper_pending_order_intents_for_feature_packs(
        self,
        feature_packs: Dict[str, Dict[str, Any]],
        *,
        cycle_source: str,
    ) -> Dict[str, Any]:
        """Evaluate paper pending intents once per cycle without touching Coinbase."""
        if not bool(getattr(self.cfg, "enable_paper_pending_order_intents", True)):
            return {"generated_at": self._now_iso(), "enabled": False, "reviewed": 0, "actions": [], "reason": "paper_pending_order_intents_disabled"}
        try:
            review = self.pending_order_intent_store.evaluate_intents(
                feature_packs or {},
                max_chase_distance_pct=getattr(self.cfg, "pending_trade_plan_max_chase_distance_pct", Decimal("0.0200")),
                mark_needs_fresh_analysis=bool(getattr(self.cfg, "paper_pending_intent_mark_needs_fresh_analysis_status", True)),
            )
            review["cycle_source"] = cycle_source
            if review.get("reviewed", 0) or (review.get("summary") or {}).get("active_intents", 0):
                self._write_jsonl("pending_order_intents.jsonl", review)
            return review
        except Exception as e:
            payload = {
                "generated_at": self._now_iso(),
                "module": "paper_pending_order_intents_review",
                "cycle_source": cycle_source,
                "error_type": type(e).__name__,
                "error": str(e),
            }
            self._write_jsonl("errors.jsonl", payload)
            return {"generated_at": self._now_iso(), "enabled": False, "reviewed": 0, "actions": [], "error": str(e)}

    def _maybe_record_phase_c_preflight_guard(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        execution_plan: Optional[Dict[str, Any]],
        paper_order: Optional[Dict[str, Any]] = None,
        cycle_source: str = "strategy_engine",
    ) -> Optional[Dict[str, Any]]:
        """Phase C.0: deterministic preflight logging only; no live submit.

        This guard prepares the next phase by checking whether a candidate would
        be blocked by the future live-entry limit-order rules. It never calls
        Coinbase and never authorizes execution. In the current workflow it is
        an audit/shadow layer next to the existing Phase-B paper manager.
        """
        if not bool(getattr(self.cfg, "phase_c_paper_shadow_log", True)):
            return None
        try:
            live_counts = count_local_phase_c_live_entry_orders(self.order_store)
            product_rules = self._feature_pack_exchange_rules(analysis.get("feature_pack") if isinstance(analysis.get("feature_pack"), dict) else {})
            open_positions = [
                position
                for position in (self.state.get_positions() or {}).values()
                if isinstance(position, dict)
            ]
            result = evaluate_phase_c_live_entry_readiness(
                cfg=self.cfg,
                ticker=ticker,
                analysis=analysis,
                execution_plan=execution_plan or {},
                order_intent=paper_order,
                live_risk_result=None,
                open_live_entry_orders_count=int(live_counts.get("total_open_live_entry_orders") or 0),
                open_live_entry_order_tickers=live_counts.get("tickers") or [],
                open_positions=open_positions,
                new_live_orders_this_cycle=int(getattr(self, "_phase_c43_new_live_orders_this_cycle", 0)),
                product_rules=product_rules,
            )
            result["cycle_source"] = cycle_source
            result["local_phase_c43_live_order_counts"] = live_counts
            self._write_jsonl("phase_c_guard.jsonl", result)
            if bool(getattr(self.cfg, "enable_phase_c_live_submit_infrastructure", True)):
                autonomous_runtime_enabled = (
                    bool(getattr(self.cfg, "enable_phase_c43_autonomous_entry_submitter", True))
                    and bool(getattr(self.cfg, "enable_autonomous_small_live_orderbook_mode", False))
                    and bool(getattr(self.cfg, "enable_phase_c_actual_coinbase_submit", False))
                    and bool(getattr(self.cfg, "enable_live_entry_orders", False))
                    and (
                        not bool(getattr(self.cfg, "enable_live_exit_orders", False))
                        or (
                            bool(getattr(self.cfg, "enable_full_workflow_live_mode", False))
                            and bool(getattr(self.cfg, "autonomous_allow_exits", False))
                            and bool(getattr(self.cfg, "enable_phase_d3_actual_exit_submit", False))
                            and not bool(getattr(self.cfg, "phase_c_disable_exit_limit_orders", True))
                        )
                    )
                )
                judge = analysis.get("judge") if isinstance(analysis.get("judge"), dict) else {}
                trade_plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
                fresh_approve_gate = (
                    str(judge.get("decision") or "").strip().lower() == "approve_trade"
                    and str(judge.get("side") or "").strip().upper() == "BUY"
                    and bool(judge.get("valid_trade_plan") or judge.get("judge_response_valid_trade_plan") or trade_plan.get("valid_trade_plan"))
                    and bool(result.get("guard_allows_live_submit"))
                )
                if autonomous_runtime_enabled:
                    submit_preview = build_phase_c43_guard_and_submit_preparation(
                        cfg=self.cfg,
                        ticker=ticker,
                        analysis=analysis,
                        execution_plan=execution_plan or {},
                        order_intent=paper_order,
                        coinbase_client=self.client,
                        order_store=self.order_store,
                        new_live_orders_this_cycle=int(getattr(self, "_phase_c43_new_live_orders_this_cycle", 0)),
                        submit_live=bool(fresh_approve_gate),
                        product_rules=product_rules,
                        open_positions=open_positions,
                    )
                    if bool(submit_preview.get("live_order_submitted")):
                        self._phase_c43_new_live_orders_this_cycle = int(getattr(self, "_phase_c43_new_live_orders_this_cycle", 0)) + 1
                else:
                    submit_preview = prepare_phase_c_live_entry_submission(
                        cfg=self.cfg,
                        ticker=ticker,
                        order_intent=paper_order,
                        guard_result=result,
                        coinbase_client=None,
                        product_rules=product_rules,
                        submit_live=False,
                    )
                submit_preview["cycle_source"] = f"{cycle_source}_phase_c43_or_c2_submit_preparation"
                self._write_jsonl("phase_c_live_submit.jsonl", submit_preview)
                result["phase_c_live_submit_preparation"] = {
                    "status": submit_preview.get("status"),
                    "live_submission_attempted": submit_preview.get("live_submission_attempted"),
                    "live_order_submitted": submit_preview.get("live_order_submitted"),
                    "hard_block_reasons": submit_preview.get("hard_block_reasons") or ((submit_preview.get("submit_result") or {}).get("hard_block_reasons") if isinstance(submit_preview.get("submit_result"), dict) else None),
                    "client_order_id": (((submit_preview.get("payload") or {}).get("client_order_id")) if isinstance(submit_preview.get("payload"), dict) else (((submit_preview.get("submit_result") or {}).get("payload") or {}).get("client_order_id") if isinstance((submit_preview.get("submit_result") or {}).get("payload"), dict) else None)),
                    "phase": submit_preview.get("phase"),
                }
            return result
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "phase_c_live_guard",
                    "cycle_source": cycle_source,
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "safety_policy": "non_fatal_phase_c0_guard_no_live_order_side_effects",
                },
            )
            return None

    def _maybe_process_phase_c43_live_entry_plan(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        execution_plan: Optional[Dict[str, Any]],
        existing_position: Optional[Dict[str, Any]] = None,
        position_action: Optional[Dict[str, Any]] = None,
        cycle_source: str = "strategy_engine",
    ) -> Optional[Dict[str, Any]]:
        """C.4.3 direct live-entry bridge, independent from the paper manager.

        Phase B's PaperLimitOrderManager deliberately disables itself whenever
        live limit-order flags are enabled. That is correct for paper safety, but
        it also means a genuine approve_trade no longer produced the order_intent
        that C.4.3 needs. This bridge rebuilds the same normalized BUY limit
        intent directly from the read-only execution plan and sends it through
        the C.4.3 deterministic risk + Phase-C guard + submitter path.

        Safety boundaries:
        - new entries only; existing-position SELL/reduce/close actions are not handled here;
        - BUY limit only; live exits remain forbidden by C.4.3 guards;
        - no Coinbase call unless the C.4.3 runtime flags, submit_live=True and
          ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT are all green;
        - submitted orders are stored in OrderStore by
          build_phase_c43_guard_and_submit_preparation for later reconciliation.
        """
        try:
            if existing_position is not None:
                return None
            if not isinstance(execution_plan, dict):
                return None

            judge = analysis.get("judge", {}) if isinstance(analysis, dict) else {}
            decision = str(judge.get("decision") or "").strip().lower()
            judge_side = str(judge.get("side") or "").strip().upper()
            if decision != "approve_trade" or judge_side != "BUY":
                return None

            feature_pack = analysis.get("feature_pack", {}) if isinstance(analysis, dict) else {}
            order_intent = build_order_intent_from_execution_plan(
                cfg=self.cfg,
                ticker=ticker,
                analysis=analysis,
                execution_plan=execution_plan,
                feature_pack=feature_pack if isinstance(feature_pack, dict) else {},
                existing_position=existing_position,
                position_action=position_action,
            )
            order_intent["paper_only"] = False
            order_intent["source_mode"] = "phase_c43_strategy_engine_direct"
            order_intent["strategy_engine_direct_c43_bridge"] = True

            if not is_actionable_order_intent(order_intent):
                result = {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "phase": "C4.3_autonomous_entry_live_activation_fill_to_position_bridge",
                    "status": "c43_direct_order_intent_rejected",
                    "cycle_source": cycle_source,
                    "order_intent": order_intent,
                    "safety_policy": "no_live_submit_when_intent_is_not_actionable",
                }
                self._write_jsonl("phase_c_live_submit.jsonl", result)
                return result

            trade_plan_for_live_gate = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
            autonomous_runtime_enabled = (
                bool(getattr(self.cfg, "enable_phase_c43_autonomous_entry_submitter", True))
                and bool(getattr(self.cfg, "enable_autonomous_small_live_orderbook_mode", False))
                and bool(getattr(self.cfg, "enable_phase_c_actual_coinbase_submit", False))
                and decision == "approve_trade"
                and bool(judge.get("valid_trade_plan") or judge.get("judge_response_valid_trade_plan") or trade_plan_for_live_gate.get("valid_trade_plan"))
                and bool(getattr(self.cfg, "enable_live_entry_orders", False))
                and bool(getattr(self.cfg, "enable_live_limit_orders", False))
                and (
                    (
                        not bool(getattr(self.cfg, "enable_live_exit_orders", False))
                        and not bool(getattr(self.cfg, "autonomous_allow_exits", False))
                    )
                    or (
                        bool(getattr(self.cfg, "enable_full_workflow_live_mode", False))
                        and bool(getattr(self.cfg, "enable_live_exit_orders", False))
                        and bool(getattr(self.cfg, "autonomous_allow_exits", False))
                        and bool(getattr(self.cfg, "enable_phase_d3_actual_exit_submit", False))
                        and not bool(getattr(self.cfg, "phase_c_disable_exit_limit_orders", True))
                        and not bool(getattr(self.cfg, "autonomous_entry_only_first", True))
                    )
                )
            )

            product_rules = self._feature_pack_exchange_rules(analysis.get("feature_pack") if isinstance(analysis.get("feature_pack"), dict) else {})
            open_positions = [
                position
                for position in (self.state.get_positions() or {}).values()
                if isinstance(position, dict)
            ]
            result = build_phase_c43_guard_and_submit_preparation(
                cfg=self.cfg,
                ticker=ticker,
                analysis=analysis,
                execution_plan=execution_plan,
                order_intent=order_intent,
                coinbase_client=self.client,
                order_store=self.order_store,
                new_live_orders_this_cycle=int(getattr(self, "_phase_c43_new_live_orders_this_cycle", 0)),
                submit_live=bool(autonomous_runtime_enabled),
                product_rules=product_rules,
                open_positions=open_positions,
            )
            result["cycle_source"] = f"{cycle_source}_phase_c43_strategy_engine_direct"
            result["strategy_engine_direct_bridge"] = True
            result["order_intent_source"] = "execution_plan_direct_not_paper_manager"
            result["autonomous_runtime_enabled"] = bool(autonomous_runtime_enabled)
            self._write_jsonl("phase_c_live_submit.jsonl", result)
            if bool(result.get("live_order_submitted")):
                self._phase_c43_new_live_orders_this_cycle = int(getattr(self, "_phase_c43_new_live_orders_this_cycle", 0)) + 1
            return result
        except Exception as e:
            payload = {
                "generated_at": self._now_iso(),
                "ticker": ticker,
                "module": "phase_c43_strategy_engine_direct_bridge",
                "cycle_source": cycle_source,
                "error_type": type(e).__name__,
                "error": str(e),
                "safety_policy": "non_fatal_no_live_exit_orders_no_fallback_submit",
            }
            self._write_jsonl("errors.jsonl", payload)
            return {"generated_at": self._now_iso(), "enabled": False, "error": str(e), "cycle_source": cycle_source}

    def _maybe_process_paper_limit_order_plan(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        execution_plan: Optional[Dict[str, Any]],
        existing_position: Optional[Dict[str, Any]] = None,
        position_action: Optional[Dict[str, Any]] = None,
        cycle_source: str = "strategy_engine",
    ) -> Optional[Dict[str, Any]]:
        """Phase B paper limit-order simulation hook.

        This never submits live Coinbase orders. It only stores/simulates paper
        orders when ENABLE_LIMIT_ORDER_MANAGER=true while all live limit-order
        flags remain false. Existing live market execution paths are unchanged.
        """
        try:
            feature_pack = analysis.get("feature_pack", {}) if isinstance(analysis, dict) else {}
            result = self.paper_limit_order_manager.maybe_create_order_from_execution_plan(
                ticker=ticker,
                analysis=analysis,
                execution_plan=execution_plan,
                feature_pack=feature_pack,
                existing_position=existing_position,
                position_action=position_action,
            )
            if result is not None:
                result["cycle_source"] = cycle_source
                self._write_jsonl("paper_order_manager.jsonl", result)
                if bool(getattr(self.cfg, "phase_c_paper_shadow_log", True)):
                    guard = self._maybe_record_phase_c_preflight_guard(
                        ticker=ticker,
                        analysis=analysis,
                        execution_plan=execution_plan,
                        paper_order=((result.get("order") or result.get("intent")) if isinstance(result, dict) else None),
                        cycle_source=f"{cycle_source}_phase_c0_preflight",
                    )
                    if guard is not None:
                        result["phase_c_preflight_guard"] = guard
            return result
        except Exception as e:
            self._write_jsonl(
                "errors.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "module": "paper_limit_order_manager",
                    "cycle_source": cycle_source,
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
            )
            return None

    def _review_phase_c43_live_entry_fills(self, *, cycle_source: str) -> Dict[str, Any]:
        """Retired direct fill route; lifecycle service owns polling and apply.

        Keeping this private method as a no-op avoids accidental reintroduction
        through legacy callers while preserving a diagnostic record for callers
        that have not yet been removed. It must never contact Coinbase or write
        OrderStore/StateStore.
        """
        return {
            "enabled": False,
            "cycle_source": cycle_source,
            "reason": "direct_c43_fill_reconciliation_retired_use_governed_lifecycle_service",
            "coinbase_call_attempted": False,
            "state_write_performed": False,
        }

    def _review_paper_open_orders_for_feature_packs(
        self,
        feature_packs: Dict[str, Dict[str, Any]],
        *,
        cycle_source: str,
    ) -> Dict[str, Any]:
        """Review paper open orders once per cycle without touching Coinbase."""
        try:
            budget_reset = self.paper_limit_order_manager.begin_cycle(cycle_source)
            review = self.paper_limit_order_manager.review_open_orders(feature_packs or {})
            review["cycle_source"] = cycle_source
            review["paper_budget_reset"] = budget_reset

            no_fill_followup = self.paper_limit_order_manager.review_no_fill_followups(
                feature_packs or {},
                cycle_source=f"{cycle_source}_no_fill_followup",
            )
            no_fill_followup["cycle_source"] = cycle_source
            review["no_fill_followup"] = no_fill_followup

            pending_intents = self._review_paper_pending_order_intents_for_feature_packs(
                feature_packs or {},
                cycle_source=f"{cycle_source}_pending_order_intents",
            )
            review["pending_order_intents"] = pending_intents

            if review.get("enabled") or review.get("reviewed", 0) or no_fill_followup.get("reviewed", 0) or pending_intents.get("reviewed", 0):
                self._write_jsonl("paper_order_manager.jsonl", review)
            return review
        except Exception as e:
            payload = {
                "generated_at": self._now_iso(),
                "module": "paper_limit_order_manager_review",
                "cycle_source": cycle_source,
                "error_type": type(e).__name__,
                "error": str(e),
            }
            self._write_jsonl("errors.jsonl", payload)
            return {
                "generated_at": self._now_iso(),
                "enabled": False,
                "reviewed": 0,
                "actions": [],
                "error": str(e),
            }

    def _analysis_to_cycle_result(
        self,
        ticker: str,
        analysis: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if existing_position and str(existing_position.get("status", "open")).lower() == "open":
            judge_decision = self._normalize_decision(analysis["judge"])

            if judge_decision in {"reduce_size", "close_position"}:
                execution_plan = self._maybe_run_read_only_execution_planner(
                    ticker=ticker,
                    analysis=analysis,
                    existing_position=existing_position,
                    position_action=None,
                    cycle_source="existing_position_judge_action",
                )
                if execution_plan is not None:
                    analysis["execution_plan"] = execution_plan
                paper_order = self._maybe_process_paper_limit_order_plan(
                    ticker=ticker,
                    analysis=analysis,
                    execution_plan=execution_plan,
                    existing_position=existing_position,
                    position_action=None,
                    cycle_source="existing_position_judge_action",
                )
                if paper_order is not None:
                    analysis["paper_order"] = paper_order
                pending_order_intent = None
                if paper_order is None:
                    pending_order_intent = self._maybe_store_paper_pending_order_intent(
                        ticker=ticker,
                        analysis=analysis,
                        execution_plan=execution_plan,
                        cycle_source="existing_position_judge_action",
                    )
                    if pending_order_intent is not None:
                        analysis["paper_pending_order_intent"] = pending_order_intent
                execution = self.maybe_execute(analysis, existing_position=existing_position)
                result = {
                    "ticker": ticker,
                    "analysis": analysis["judge"],
                    "entry_gate": analysis.get("entry_gate", {}),
                    "execution": execution,
                }
                if execution_plan is not None:
                    result["execution_plan"] = execution_plan
                if paper_order is not None:
                    result["paper_order"] = paper_order
                if 'pending_order_intent' in locals() and pending_order_intent is not None:
                    result["paper_pending_order_intent"] = pending_order_intent
                return result

            position_action = self.position_manager.evaluate_position(
                ticker=ticker,
                position=existing_position,
                feature_pack=analysis["feature_pack"],
                judge=analysis.get("judge"),
            )
            position_action = self._suppress_repeated_partial_take_profit_action(
                ticker=ticker,
                position=existing_position,
                action=position_action,
            )
            position_action = self._apply_judge_soft_override_to_position_action(
                ticker=ticker,
                position=existing_position,
                action=position_action,
                feature_pack=analysis["feature_pack"],
                judge=analysis.get("judge"),
            )

            execution_plan = self._maybe_run_read_only_execution_planner(
                ticker=ticker,
                analysis=analysis,
                existing_position=existing_position,
                position_action=position_action,
                cycle_source="existing_position_position_manager_action",
            )
            if execution_plan is not None:
                analysis["execution_plan"] = execution_plan
            paper_order = self._maybe_process_paper_limit_order_plan(
                ticker=ticker,
                analysis=analysis,
                execution_plan=execution_plan,
                existing_position=existing_position,
                position_action=position_action,
                cycle_source="existing_position_position_manager_action",
            )
            if paper_order is not None:
                analysis["paper_order"] = paper_order
            pending_order_intent = None
            if paper_order is None:
                pending_order_intent = self._maybe_store_paper_pending_order_intent(
                    ticker=ticker,
                    analysis=analysis,
                    execution_plan=execution_plan,
                    cycle_source="existing_position_position_manager_action",
                )
                if pending_order_intent is not None:
                    analysis["paper_pending_order_intent"] = pending_order_intent

            position_execution = self._handle_position_action(
                ticker=ticker,
                position=existing_position,
                action=position_action,
                feature_pack=analysis["feature_pack"],
            )

            action_type = str(position_action.get("action", "hold")).lower().strip()
            if action_type in {"close", "reduce", "hold"}:
                result = {
                    "ticker": ticker,
                    "analysis": analysis["judge"],
                    "entry_gate": analysis.get("entry_gate", {}),
                    "position_execution": position_execution,
                }
                if execution_plan is not None:
                    result["execution_plan"] = execution_plan
                if paper_order is not None:
                    result["paper_order"] = paper_order
                if 'pending_order_intent' in locals() and pending_order_intent is not None:
                    result["paper_pending_order_intent"] = pending_order_intent
                return result

        execution_plan = self._maybe_run_read_only_execution_planner(
            ticker=ticker,
            analysis=analysis,
            existing_position=existing_position,
            position_action=None,
            cycle_source="new_entry_or_no_position_analysis",
        )
        if execution_plan is not None:
            analysis["execution_plan"] = execution_plan
        paper_order = self._maybe_process_paper_limit_order_plan(
            ticker=ticker,
            analysis=analysis,
            execution_plan=execution_plan,
            existing_position=existing_position,
            position_action=None,
            cycle_source="new_entry_or_no_position_analysis",
        )
        if paper_order is not None:
            analysis["paper_order"] = paper_order

        phase_c43_live_entry = None
        if paper_order is None:
            phase_c43_live_entry = self._maybe_process_phase_c43_live_entry_plan(
                ticker=ticker,
                analysis=analysis,
                execution_plan=execution_plan,
                existing_position=existing_position,
                position_action=None,
                cycle_source="new_entry_or_no_position_analysis",
            )
            if phase_c43_live_entry is not None:
                analysis["phase_c43_live_entry"] = phase_c43_live_entry

        pending_order_intent = None
        if paper_order is None and not bool((phase_c43_live_entry or {}).get("live_order_submitted")):
            pending_order_intent = self._maybe_store_paper_pending_order_intent(
                ticker=ticker,
                analysis=analysis,
                execution_plan=execution_plan,
                cycle_source="new_entry_or_no_position_analysis",
            )
            if pending_order_intent is not None:
                analysis["paper_pending_order_intent"] = pending_order_intent

        execution = self.maybe_execute(analysis, existing_position=existing_position)
        pending_plan = None
        if existing_position is None:
            pending_plan = self._maybe_store_pending_trade_plan(
                ticker=ticker,
                analysis=analysis,
                execution=execution,
            )

        result = {
            "ticker": ticker,
            "analysis": analysis["judge"],
            "entry_gate": analysis.get("entry_gate", {}),
            "execution": execution,
        }
        if execution_plan is not None:
            result["execution_plan"] = execution_plan
        if paper_order is not None:
            result["paper_order"] = paper_order
        if 'phase_c43_live_entry' in locals() and phase_c43_live_entry is not None:
            result["phase_c43_live_entry"] = {
                "status": phase_c43_live_entry.get("status"),
                "live_submission_attempted": phase_c43_live_entry.get("live_submission_attempted"),
                "live_order_submitted": phase_c43_live_entry.get("live_order_submitted"),
                "client_order_id": (((phase_c43_live_entry.get("submit_result") or {}).get("payload") or {}).get("client_order_id") if isinstance((phase_c43_live_entry.get("submit_result") or {}).get("payload"), dict) else None),
                "strategy_engine_direct_bridge": phase_c43_live_entry.get("strategy_engine_direct_bridge"),
            }
        if 'pending_order_intent' in locals() and pending_order_intent is not None:
            result["paper_pending_order_intent"] = pending_order_intent
        if pending_plan:
            result["pending_trade_plan"] = {
                "stored": True,
                "plan_id": pending_plan.get("plan_id"),
                "expires_at": pending_plan.get("expires_at"),
                "safety_policy": pending_plan.get("safety_policy"),
            }
        return result

    def _run_existing_position_cycle(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        existing_position: Dict[str, Any],
    ) -> Dict[str, Any]:
        heartbeat = self._position_heartbeat_prefilter(
            ticker=ticker,
            position=existing_position,
            feature_pack=feature_pack,
        )
        if self._heartbeat_requires_forced_risk_action(heartbeat):
            self.state.mark_position_full_review(
                ticker=ticker,
                result="risk_management_override",
                reason="scheduled_full_position_review_stop_breach",
                extra={
                    "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
                },
            )
            return self._build_risk_override_cycle_result(
                ticker=ticker,
                feature_pack=feature_pack,
                existing_position=existing_position,
                heartbeat=heartbeat,
                source="full_cycle",
            )

        analysis = self.analyze_ticker(
            ticker=ticker,
            feature_pack_override=feature_pack,
            existing_position=existing_position,
        )

        judge_decision = self._normalize_decision(analysis.get("judge", {}))
        self.state.mark_position_full_review(
            ticker=ticker,
            result="position_watch_hold_ok" if judge_decision in {"wait", "reject", "no_trade"} else "escalate_full_review",
            reason="scheduled_full_position_review",
            extra={
                "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
            },
        )

        result = self._analysis_to_cycle_result(
            ticker=ticker,
            analysis=analysis,
            existing_position=existing_position,
        )
        self._record_decision_outcome_snapshot(
            ticker=ticker,
            analysis=analysis,
            cycle_result=result,
            feature_pack=feature_pack,
            source="run_ticker_cycle",
        )
        self._record_shadow_decision(
            ticker=ticker,
            analysis=analysis,
            cycle_result=result,
            feature_pack=feature_pack,
            source="run_cycle_existing_position",
        )
        return result

    def _run_new_entry_candidate(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
    ) -> Dict[str, Any]:
        analysis = self.analyze_ticker(
            ticker=ticker,
            feature_pack_override=feature_pack,
            existing_position=None,
        )
        return self._analysis_to_cycle_result(
            ticker=ticker,
            analysis=analysis,
            existing_position=None,
        )

    def _build_entry_gate_from_prefilter(
        self,
        ticker: str,
        prefilter: Dict[str, Any],
    ) -> Dict[str, Any]:
        decision_map = {
            "skip": "skip",
            "watchlist": "watch",
            "consider": "watch",
            "consider_high": "watch",
        }
        decision = decision_map.get(str(prefilter.get("prefilter_decision", "watch")), "watch")

        return {
            "generated_at": self._now_iso(),
            "ticker": ticker,
            "decision": decision,
            "priority": "normal",
            "setup_type": self._normalize_setup_type(prefilter.get("setup_guess")),
            "confidence": max(10, min(60, int(prefilter.get("prefilter_score", 0)))),
            "reasons": [*prefilter.get("reasons", [])],
            "warnings": [*prefilter.get("warnings", []), "prefilter_only_no_llm_gate_run"],
        }

    def _build_gate_only_skip_result(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        prefilter: Dict[str, Any],
    ) -> Dict[str, Any]:
        entry_gate = self._build_entry_gate_from_prefilter(ticker, prefilter)
        deepseek_pack = {
            "generated_at": self._now_iso(),
            "skipped": True,
            "reason": "prefilter_not_selected_for_deepseek_gate",
        }

        analysis = self._build_skip_analysis_result(
            ticker=ticker,
            feature_pack=feature_pack,
            deepseek_pack=deepseek_pack,
            entry_gate=entry_gate,
        )
        return self._analysis_to_cycle_result(
            ticker=ticker,
            analysis=analysis,
            existing_position=None,
        )

    def _build_gate_watch_result(
        self,
        ticker: str,
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self._analysis_to_cycle_result(
            ticker=ticker,
            analysis=analysis,
            existing_position=None,
        )

    def _position_monitoring_enabled_for(self, position: Dict[str, Any]) -> bool:
        if not position:
            return False
        if str(position.get("status", "open")).lower().strip() != "open":
            return False
        if not bool(position.get("monitoring_enabled", True)):
            return False
        return True

    def _position_watch_requests_full_review(self, watch: Dict[str, Any]) -> bool:
        decision = str(watch.get("decision", "watch_closer")).strip().lower()
        return decision in {"tighten_risk", "escalate_full_review"}

    def _build_position_watch_input(
        self,
        ticker: str,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
        heartbeat: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "ticker": ticker,
            "position": {
                "ticker": position.get("ticker"),
                "entry_time": position.get("entry_time"),
                "entry_price": position.get("entry_price"),
                "position_size_base": position.get("position_size_base"),
                "position_size_quote": position.get("position_size_quote"),
                "stop_price": position.get("stop_price"),
                "take_profit_price": position.get("take_profit_price"),
                "highest_price_seen": position.get("highest_price_seen"),
                "lowest_price_seen": position.get("lowest_price_seen"),
                "trailing_active": position.get("trailing_active"),
                "trailing_distance_pct": position.get("trailing_distance_pct"),
                "trailing_trigger_pct": position.get("trailing_trigger_pct"),
                "invalidation_mode": position.get("invalidation_mode"),
                "setup_type": position.get("setup_type"),
                "position_plan_snapshot": position.get("position_plan_snapshot", {}),
                "heartbeat_warning_count": position.get("heartbeat_warning_count", 0),
                "last_heartbeat_status": position.get("last_heartbeat_status"),
                "last_deepseek_position_result": position.get("last_deepseek_position_result"),
            },
            "feature_pack": feature_pack,
            "heartbeat_prefilter": heartbeat,
            "task": {
                "objective": "Check whether the existing long spot position still broadly follows plan.",
                "allowed_decisions": [
                    "hold_ok",
                    "watch_closer",
                    "tighten_risk",
                    "escalate_full_review",
                ],
                "bias": "conservative",
            },
        }

    def _position_heartbeat_prefilter(
        self,
        ticker: str,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
    ) -> Dict[str, Any]:
        market = feature_pack.get("market", {})
        indicators = feature_pack.get("indicators", {})
        micro = feature_pack.get("microstructure", {})
        structure = feature_pack.get("structure", {})

        current_price = self._to_decimal(market.get("mid_price"), "0")
        entry_price = self._to_decimal(position.get("entry_price"), "0")
        stop_price = self._to_decimal(position.get("stop_price"), "0")
        highest_price_seen = self._to_decimal(position.get("highest_price_seen"), str(entry_price or "0"))
        position_size_base = self._to_decimal(position.get("position_size_base"), "0")

        spread_pct = self._to_decimal(market.get("spread_pct"), "0")
        max_spread_pct = self._to_decimal(
            feature_pack.get("risk_context", {}).get("max_spread_pct"),
            str(self.cfg.max_spread_pct),
        )

        i1h = indicators.get("1h", {})
        i4h = indicators.get("4h", {})

        ema20_1h = self._to_decimal(i1h.get("ema_20"), "0")
        ema50_1h = self._to_decimal(i1h.get("ema_50"), "0")
        ema50_4h = self._to_decimal(i4h.get("ema_50"), "0")
        ema200_4h = self._to_decimal(i4h.get("ema_200"), "0")
        atr_1h = self._to_decimal(i1h.get("atr_14"), "0")

        vol_15m = self._to_float(micro.get("15m", {}).get("volume_vs_avg"), 0.0)
        vol_1h = self._to_float(micro.get("1h", {}).get("volume_vs_avg"), 0.0)

        higher_lows_1h = bool(structure.get("higher_lows_1h", False))
        lower_highs_1h = bool(structure.get("lower_highs_1h", False))
        lower_lows_1h = bool(structure.get("lower_lows_1h", False))

        reasons: List[str] = []
        metrics: Dict[str, Any] = {}

        if current_price <= Decimal("0") or position_size_base <= Decimal("0"):
            return {
                "decision": "full_review",
                "severity": "high",
                "reasons": ["position_or_price_invalid_for_heartbeat"],
                "metrics": {},
            }

        unrealized_pnl_pct = Decimal("0")
        if entry_price > Decimal("0"):
            unrealized_pnl_pct = (current_price - entry_price) / entry_price
        metrics["unrealized_pnl_pct"] = float(unrealized_pnl_pct)

        if highest_price_seen > Decimal("0"):
            drawdown_from_peak_pct = (current_price - highest_price_seen) / highest_price_seen
        else:
            drawdown_from_peak_pct = Decimal("0")
        metrics["drawdown_from_peak_pct"] = float(drawdown_from_peak_pct)

        near_stop = False
        stop_breached = False
        if stop_price > Decimal("0"):
            near_stop = current_price <= (stop_price * Decimal("1.01"))
            stop_breached = current_price <= stop_price
            metrics["distance_to_stop_pct"] = float((current_price - stop_price) / stop_price)
        else:
            metrics["distance_to_stop_pct"] = None

        bearish_htf = (
            ema50_4h > Decimal("0")
            and ema200_4h > Decimal("0")
            and ema50_4h < ema200_4h
        )
        below_fast_1h = (
            ema20_1h > Decimal("0")
            and ema50_1h > Decimal("0")
            and current_price < ema20_1h
            and current_price < ema50_1h
        )
        weak_participation = vol_15m < 0.75 and vol_1h < 0.75
        adverse_structure = lower_highs_1h and lower_lows_1h and not higher_lows_1h

        if stop_breached:
            reasons.append("stop_breached_or_below_invalidation")
            return {
                "decision": "full_review",
                "severity": "high",
                "reasons": reasons,
                "metrics": metrics,
            }

        if spread_pct > max_spread_pct:
            reasons.append("spread_above_allowed_threshold")
            return {
                "decision": "full_review",
                "severity": "high",
                "reasons": reasons,
                "metrics": metrics,
            }

        if near_stop:
            reasons.append("price_near_stop_or_invalidation")
            return {
                "decision": "position_watch",
                "severity": "medium",
                "reasons": reasons,
                "metrics": metrics,
            }

        if atr_1h > Decimal("0") and stop_price > Decimal("0"):
            distance_to_stop_abs = current_price - stop_price
            if distance_to_stop_abs <= atr_1h:
                reasons.append("distance_to_stop_within_one_1h_atr")
                return {
                    "decision": "position_watch",
                    "severity": "medium",
                    "reasons": reasons,
                    "metrics": metrics,
                }

        if unrealized_pnl_pct <= Decimal("-0.03") and bearish_htf and below_fast_1h:
            reasons.append("material_adverse_move_with_bearish_trend_context")
            return {
                "decision": "full_review",
                "severity": "high",
                "reasons": reasons,
                "metrics": metrics,
            }

        if drawdown_from_peak_pct <= Decimal("-0.04") and adverse_structure:
            reasons.append("drawdown_from_peak_and_structure_degraded")
            return {
                "decision": "position_watch",
                "severity": "medium",
                "reasons": reasons,
                "metrics": metrics,
            }

        if below_fast_1h and bearish_htf and weak_participation:
            reasons.append("trade_below_1h_fast_emas_with_weak_participation")
            return {
                "decision": "position_watch",
                "severity": "medium",
                "reasons": reasons,
                "metrics": metrics,
            }

        if adverse_structure and weak_participation:
            reasons.append("structure_softened_and_volume_is_weak")
            return {
                "decision": "position_watch",
                "severity": "medium",
                "reasons": reasons,
                "metrics": metrics,
            }

        reasons.append("position_looks_broadly_intact")
        return {
            "decision": "ok",
            "severity": "low",
            "reasons": reasons,
            "metrics": metrics,
        }

    def _run_position_watch(
        self,
        ticker: str,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
        heartbeat: Dict[str, Any],
    ) -> Dict[str, Any]:
        watch_input = self._build_position_watch_input(
            ticker=ticker,
            position=position,
            feature_pack=feature_pack,
            heartbeat=heartbeat,
        )

        try:
            payload = self.openai.json_response(
                GPT_NANO_POSITION_WATCH_PROMPT,
                watch_input,
                model=self.position_watch_model,
                ticker=ticker,
                stage="position_watch",
                allowed_keys=MODULE_ALLOWED_KEYS["position_watch"],
                require_all_keys=False,
                drop_unknown_keys=True,
            )
            normalized = self._normalize_position_watch(payload)
            self._write_jsonl(
                "heartbeat.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "stage": "position_watch",
                    "heartbeat_prefilter": heartbeat,
                    "position_watch": normalized,
                },
            )
            return normalized
        except Exception as e:
            heartbeat_reasons = [str(r).lower() for r in heartbeat.get("reasons", [])]
            high_attention = any(
                token in " | ".join(heartbeat_reasons)
                for token in ["stop", "drawdown", "structure", "bearish", "spread"]
            )
            normalized = {
                "decision": "watch_closer" if high_attention else "hold_ok",
                "confidence": 0,
                "reasons": [f"position_watch_fallback_after_error: {e}"],
                "warnings": [str(e), "position_watch_used_safe_fallback"],
            }
            self._write_jsonl(
                "heartbeat.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "stage": "position_watch",
                    "heartbeat_prefilter": heartbeat,
                    "position_watch": normalized,
                },
            )
            return normalized

    def _hard_risk_gate(
        self,
        ticker: str,
        judge: Dict[str, Any],
        feature_pack: Dict[str, Any],
        size_quote: Optional[Decimal] = None,
        existing_position: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        reasons: List[str] = []
        risk_state = feature_pack["risk_context"]["engine_state"]

        decision = self._normalize_decision(judge)
        side = self._normalize_side(judge)

        if size_quote is None:
            try:
                size_quote = self._parse_size_quote(judge)
            except (InvalidOperation, ValueError, TypeError):
                reasons.append("invalid_size_quote")
                return reasons

        if self._is_no_trade_decision(judge):
            return reasons

        if feature_pack["market"].get("trading_disabled") is True:
            reasons.append("trading_disabled")

        if feature_pack["market"].get("cancel_only") is True:
            reasons.append("cancel_only")

        if decision in {"wait", "reject", "no_trade"}:
            return reasons

        if decision == "approve_trade":
            if side != "BUY":
                reasons.append("approve_trade_requires_buy_side_for_new_entries")

            if risk_state["cooldown_active"]:
                reasons.append("cooldown_active")

            available_quote = self._to_decimal(
                feature_pack["risk_context"].get("available_quote_balance"),
                "0",
            )
            max_notional_limit = self._to_decimal(
                feature_pack["risk_context"].get("max_notional_limit"),
                str(self.max_trade_quote_usdc),
            )

            if size_quote <= Decimal("0"):
                reasons.append("non_positive_size")
            if size_quote < self.min_trade_quote_usdc:
                reasons.append("size_below_minimum")
            if size_quote > max_notional_limit:
                reasons.append("size_above_product_max_notional")
            if size_quote > available_quote:
                reasons.append("insufficient_quote_balance")

            return reasons

        if decision in {"reduce_size", "close_position"}:
            if existing_position is None:
                reasons.append("no_existing_position_for_position_management")
                return reasons

            position_status = str(existing_position.get("status", "open")).lower().strip()
            if position_status != "open":
                reasons.append("position_not_open")

            position_size_base = self._to_decimal(existing_position.get("position_size_base"), "0")
            if position_size_base <= Decimal("0"):
                reasons.append("no_meaningful_position_to_manage")

            if side not in {"SELL", "NONE"}:
                reasons.append("invalid_side_for_position_management")

            return reasons

        reasons.append(f"unsupported_judge_decision_{decision}")
        return reasons

    def maybe_execute(
        self,
        analysis: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = analysis["ticker"]
        judge = analysis["judge"]
        feature_pack = analysis["feature_pack"]

        decision = self._normalize_decision(judge)
        side = self._normalize_side(judge)

        execution_record: Dict[str, Any] = {
            "ticker": ticker,
            "judge": judge,
            "judge_summary": self._judge_summary(judge),
            "hard_rejects": [],
            "mode": self.cfg.execution_mode,
            "executed": False,
        }

        if self._is_no_trade_decision(judge):
            execution_record["status"] = "no_trade"
            execution_record["reason"] = f"judge_decision_{decision}"
            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        if decision in {"reduce_size", "close_position"}:
            hard_rejects = self._hard_risk_gate(
                ticker=ticker,
                judge=judge,
                feature_pack=feature_pack,
                existing_position=existing_position,
            )
            execution_record["hard_rejects"] = hard_rejects

            if hard_rejects:
                execution_record["status"] = "rejected"
                self._write_jsonl("execution.jsonl", execution_record)
                return execution_record

            judge_action = self._build_judge_position_action(
                ticker=ticker,
                judge=judge,
                position=existing_position or {},
                feature_pack=feature_pack,
            )

            if not judge_action:
                execution_record["status"] = "rejected"
                execution_record["hard_rejects"] = ["invalid_judge_position_action"]
                self._write_jsonl("execution.jsonl", execution_record)
                return execution_record

            position_execution = self._handle_position_action(
                ticker=ticker,
                position=existing_position or {},
                action=judge_action,
                feature_pack=feature_pack,
            )

            execution_record["status"] = "judge_position_action_executed"
            execution_record["executed"] = bool(position_execution.get("executed", False))
            execution_record["position_execution"] = position_execution
            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        try:
            raw_size_quote = self._parse_size_quote(judge)
        except (InvalidOperation, ValueError, TypeError):
            execution_record["status"] = "rejected"
            execution_record["hard_rejects"] = ["invalid_size_quote"]
            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        effective_size_quote = raw_size_quote
        if decision == "approve_trade" and side == "BUY":
            effective_size_quote = self._clamp_judge_buy_size_quote(judge, feature_pack)

        execution_record["raw_size_quote"] = str(raw_size_quote)
        execution_record["effective_size_quote"] = str(effective_size_quote)

        if decision == "approve_trade" and side == "BUY" and effective_size_quote <= Decimal("0"):
            execution_record["status"] = "rejected"
            execution_record["hard_rejects"] = ["invalid_portfolio_sized_quote"]
            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        hard_rejects = self._hard_risk_gate(
            ticker=ticker,
            judge=judge,
            feature_pack=feature_pack,
            size_quote=effective_size_quote,
            existing_position=existing_position,
        )
        execution_record["hard_rejects"] = hard_rejects

        if hard_rejects:
            execution_record["status"] = "rejected"
            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        current_price = self._to_decimal(feature_pack["market"].get("mid_price"), "0")
        estimated_base_size = self._estimate_base_size_from_quote(effective_size_quote, current_price)
        position_plan_snapshot = self._build_position_plan_snapshot_from_analysis(analysis)
        initial_risk_fields = self._build_initial_position_risk_fields(analysis, current_price)

        baseline_inventory_base = Decimal("0")
        if decision == "approve_trade" and side == "BUY":
            baseline_inventory_base = self._capture_pre_entry_inventory_base(ticker)
            execution_record["baseline_inventory_base_before_entry"] = str(baseline_inventory_base)

        if self.cfg.execution_mode == "paper":
            execution_record["status"] = "paper_trade"
            execution_record["paper_order"] = {
                "ticker": ticker,
                "side": side,
                "size_quote": str(effective_size_quote),
                "estimated_base_size": str(estimated_base_size),
                "estimated_entry_price": str(current_price),
                "setup_type": feature_pack.get("entry_gate", {}).get("setup_type", "unclear"),
            }

            if side == "BUY":
                self.state.create_position(
                    ticker=ticker,
                    side="BUY",
                    order_id=f"paper-{datetime.now(timezone.utc).timestamp()}",
                    entry_price=str(current_price),
                    position_size_base=str(estimated_base_size),
                    position_size_quote=str(effective_size_quote),
                    entry_reason=str(judge.get("strategy", "")),
                    extra={
                        "notes": "paper position created from judge approval",
                        "status": "open",
                        "judge_confidence": judge.get("confidence"),
                        "judge_raw_size_quote": str(raw_size_quote),
                        "judge_effective_size_quote": str(effective_size_quote),
                        "setup_type": judge.get("setup_type") or feature_pack.get("entry_gate", {}).get("setup_type", "unclear"),
                        "position_plan_snapshot": position_plan_snapshot,
                        **initial_risk_fields,
                        "last_heartbeat_status": "unknown",
                        "heartbeat_warning_count": 0,
                    },
                )
                self._initialize_inventory_tracking_after_entry(
                    ticker=ticker,
                    entry_base_size=estimated_base_size,
                    baseline_inventory_base=baseline_inventory_base,
                )
                self.state.set_cooldown(ticker, self.cfg.cooldown_minutes)

            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        # Live entries are owned exclusively by the C.4.3 guarded resting
        # limit-order boundary.  A second generic market-order route would
        # bypass OrderStore and lifecycle authority.
        execution_record["status"] = "live_entry_retired_requires_c43_boundary"
        execution_record["executed"] = False
        execution_record["blocker"] = "generic_market_buy_route_retired"
        self._write_jsonl("execution.jsonl", execution_record)
        return execution_record

    def _build_judge_position_action(
        self,
        ticker: str,
        judge: Dict[str, Any],
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        decision = self._normalize_decision(judge)
        side = self._normalize_side(judge)

        if decision not in {"reduce_size", "close_position"}:
            return None

        if side not in {"SELL", "NONE"}:
            return None

        current_price = self._to_decimal(
            feature_pack.get("market", {}).get("mid_price"),
            "0",
        )
        if current_price <= Decimal("0"):
            return None

        inventory_state = self._extract_position_inventory_state(position)
        bot_managed_base = inventory_state["bot_managed_base"]
        if bot_managed_base <= Decimal("0"):
            return None

        if decision == "close_position":
            requested_bot_size_base = bot_managed_base
            action = "close"
        else:
            requested_quote = self._to_decimal(judge.get("size_quote"), "0")
            if requested_quote <= Decimal("0"):
                requested_bot_size_base = bot_managed_base / Decimal("2")
            else:
                requested_bot_size_base = requested_quote / current_price

            if requested_bot_size_base >= bot_managed_base:
                requested_bot_size_base = bot_managed_base

            action = "reduce"

        if requested_bot_size_base <= Decimal("0"):
            return None

        live_available_base = self._get_live_available_base(ticker)
        inventory_plan = self._compute_inventory_sell_plan(
            ticker=ticker,
            position=position,
            action_type=action,
            requested_bot_sell_base=requested_bot_size_base,
            live_available_base=live_available_base,
        )

        sell_total_base = self._to_decimal(inventory_plan.get("sell_total_base"), "0")
        if sell_total_base <= Decimal("0"):
            return None

        return {
            "action": action,
            "reason": f"judge_{decision}",
            "side": "SELL",
            "size_base": str(sell_total_base),
            "size_quote": str(sell_total_base * current_price),
            "stop_price": str(position.get("stop_price", "0")),
            "take_profit_price": str(position.get("take_profit_price", "0")),
            "trailing_active": bool(position.get("trailing_active", False)),
            "metadata": {
                "ticker": ticker,
                "current_price": str(current_price),
                "judge_confidence": judge.get("confidence"),
                "judge_strategy": judge.get("strategy"),
                "judge_reasons": judge.get("reasons", []),
                "updated_position": position,
                "inventory_plan": inventory_plan,
                "requested_bot_size_base": str(requested_bot_size_base),
                "live_available_base": str(live_available_base),
            },
        }

    @staticmethod
    def _env_flag_enabled(name: str) -> bool:
        return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

    def _full_workflow_d3_bridge_blockers(
        self,
        *,
        action_type: str,
        side: str,
        position: Dict[str, Any],
    ) -> List[str]:
        blockers: List[str] = []
        cfg = self.cfg
        if not bool(getattr(cfg, "enable_full_workflow_live_mode", False)):
            blockers.append("full_workflow_live_mode_disabled")
        if str(getattr(cfg, "execution_mode", "")).lower() != "live":
            blockers.append("execution_mode_not_live")
        if action_type not in {"close", "reduce"}:
            blockers.append("position_action_not_d3_routable")
        if side != "SELL":
            blockers.append("position_action_side_not_sell")
        if not bool(getattr(cfg, "enable_live_exit_orders", False)):
            blockers.append("enable_live_exit_orders_false")
        if not bool(getattr(cfg, "autonomous_allow_exits", False)):
            blockers.append("autonomous_allow_exits_false")
        if not bool(getattr(cfg, "enable_phase_d3_actual_exit_submit", False)):
            blockers.append("enable_phase_d3_actual_exit_submit_false")
        if str(getattr(cfg, "phase_d3_runtime_submit_ack", "") or "").strip() != D3_ACK:
            blockers.append("phase_d3_runtime_submit_ack_missing_or_invalid")
        if bool(getattr(cfg, "phase_c_disable_exit_limit_orders", True)):
            blockers.append("phase_c_disable_exit_limit_orders_true")
        if bool(getattr(cfg, "autonomous_entry_only_first", True)):
            blockers.append("autonomous_entry_only_first_true")
        if getattr(self, "client", None) is None:
            blockers.append("coinbase_client_missing")
        inventory_state = self._extract_position_inventory_state(position)
        if inventory_state.get("bot_managed_base", Decimal("0")) <= Decimal("0"):
            blockers.append("bot_managed_base_missing_or_zero")
        if str(position.get("status") or "").strip().lower() != "open":
            blockers.append("position_not_open")
        for env_name in (
            "REPLICATION_ENABLED",
            "LEARNING_TO_EXECUTION_READY",
            "LEARNING_TO_EXECUTION_ALLOWED",
            "LIVE_LEARNING_ALLOWED",
            "PARAMETER_CHANGE_ALLOWED",
        ):
            if self._env_flag_enabled(env_name):
                blockers.append(f"{env_name.lower()}_true")
        market_flags = {
            "market_order_enabled": bool(getattr(cfg, "market_order_enabled", False)),
            "enable_market_orders": bool(getattr(cfg, "enable_market_orders", False)),
            "allow_market_orders": bool(getattr(cfg, "allow_market_orders", False)),
        }
        if any(market_flags.values()):
            blockers.append("market_order_flags_enabled_config_unsafe_for_orderbook_d3")
        return blockers

    def _feature_pack_orderbook_context(self, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        orderbook = feature_pack.get("orderbook_context")
        if not isinstance(orderbook, dict):
            orderbook = feature_pack.get("orderbook_summary")
        market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
        merged = dict(orderbook or {})
        for key in ("best_bid", "best_ask", "mid_price", "spread_pct", "freshness_status", "snapshot_available"):
            if key not in merged and key in market:
                merged[key] = market[key]
        return merged

    def _feature_pack_exchange_rules(self, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("exchange_rules", "product_rules", "coinbase_product_rules"):
            value = feature_pack.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _position_action_market_evidence(
        self,
        *,
        action: Dict[str, Any],
        feature_pack: Dict[str, Any],
    ) -> Decimal:
        metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
        market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
        for value in (
            metadata.get("current_price"),
            market.get("mid_price"),
            market.get("last_price"),
            market.get("best_bid"),
            market.get("best_ask"),
        ):
            price = self._to_decimal(value, "0")
            if price > Decimal("0"):
                return price
        return Decimal("0")

    def _requires_controlled_stop_exit_route(
        self,
        *,
        action: Dict[str, Any],
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
    ) -> bool:
        """Identify stop/invalidation closes that must never become D3 maker GTCs."""
        metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
        reasons = [
            str(action.get("reason") or ""),
            str(metadata.get("risk_reason") or ""),
            str(metadata.get("position_risk_reason") or ""),
            *[str(item) for item in metadata.get("reasons", []) if item is not None],
        ]
        reason_text = " ".join(reasons).lower()
        risk_tokens = (
            "stop_breached",
            "stop_loss",
            "stop_hit",
            "below_invalidation",
            "invalidation_breached",
            "invalidation_hit",
            "heartbeat_stop_breach",
            "forced_risk",
            "risk_management_override",
        )
        if bool(metadata.get("forced_risk_override")) or any(token in reason_text for token in risk_tokens):
            return True

        current_price = self._position_action_market_evidence(action=action, feature_pack=feature_pack)
        stop = self._to_decimal(position.get("stop_price"), "0")
        invalidation = self._to_decimal(position.get("invalidation_price"), "0")
        risk_boundary = max(stop, invalidation)
        return bool(current_price > Decimal("0") and risk_boundary > Decimal("0") and current_price <= risk_boundary)

    def _build_controlled_stop_exit_preview_from_position_action(
        self,
        *,
        ticker: str,
        position: Dict[str, Any],
        action: Dict[str, Any],
        feature_pack: Dict[str, Any],
        execution_record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Emit the Mode-A-safe stop-exit preview without a D3 limit submit."""
        metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
        orderbook = self._feature_pack_orderbook_context(feature_pack)
        current_price = self._position_action_market_evidence(action=action, feature_pack=feature_pack)
        linked_position_id = str(
            position.get("recovery_linked_position_id")
            or position.get("phase_c43_exchange_order_id")
            or position.get("order_id")
            or position.get("position_id")
            or ""
        ).strip()
        reason = str(action.get("reason") or "stop_or_invalidation_close")
        stop_preview = build_controlled_stop_market_exit_plan(
            ticker=ticker,
            linked_position_id=linked_position_id,
            position=position,
            market_context={
                "current_price": str(current_price),
                "mid_price": str(current_price),
                "best_bid": orderbook.get("best_bid"),
                "best_ask": orderbook.get("best_ask"),
                "reason": reason,
                "reasons": [reason, *[str(item) for item in metadata.get("reasons", [])]],
            },
            cfg=self.cfg,
            order_store=self.order_store,
            state_store=self.state,
        )
        execution_record.update({
            "status": "controlled_stop_exit_preview_required",
            "executed": False,
            "reason": "stop_or_invalidation_close_must_use_controlled_stop_exit_route",
            "controlled_stop_exit_report": stop_preview,
            "d3_full_workflow_bridge": {
                "attempted": False,
                "phase": D3_PHASE,
                "action_type": "close",
                "submit_live": False,
                "blocked_route": "risk_close_post_only_limit",
                "required_route": "controlled_stop_exit",
                "blockers": ["risk_close_requires_controlled_stop_exit_route"],
                "market_order_allowed": False,
            },
        })
        self._write_jsonl("execution.jsonl", execution_record)
        return execution_record

    def _maybe_route_full_workflow_position_exit_to_d3(
        self,
        *,
        ticker: str,
        position: Dict[str, Any],
        action: Dict[str, Any],
        feature_pack: Dict[str, Any],
        action_type: str,
        side: str,
        sell_size_base: Decimal,
        execution_record: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if action_type == "close" and self._requires_controlled_stop_exit_route(
            action=action,
            position=position,
            feature_pack=feature_pack,
        ):
            return self._build_controlled_stop_exit_preview_from_position_action(
                ticker=ticker,
                position=position,
                action=action,
                feature_pack=feature_pack,
                execution_record=execution_record,
            )

        blockers = self._full_workflow_d3_bridge_blockers(
            action_type=action_type,
            side=side,
            position=position,
        )
        if blockers:
            execution_record["d3_full_workflow_bridge"] = {
                "attempted": False,
                "reason": "full_workflow_d3_bridge_preconditions_failed",
                "blockers": blockers,
            }
            return None

        orderbook_context = self._feature_pack_orderbook_context(feature_pack)
        exchange_rules = self._feature_pack_exchange_rules(feature_pack)
        runtime_submit_ack = str(getattr(self.cfg, "phase_d3_runtime_submit_ack", "") or "").strip()
        d3_result: Dict[str, Any]

        if action_type == "close":
            position_id = str(position.get("order_id") or position.get("position_id") or "")
            plan = {
                "plan_id": f"d3-full-close-{ticker}-{position_id or 'position'}",
                "status": D2_PLAN_STATUS_READY,
                "ticker": ticker,
                "position_id": position_id,
                "exits": [],
            }
            exit_intent = build_phase_d3_full_close_exit_intent(
                cfg=self.cfg,
                ticker=ticker,
                position=position,
                order_store=self.order_store,
                orderbook_context=orderbook_context,
                exchange_rules=exchange_rules,
                requested_base_size=sell_size_base,
                label="FULL_CLOSE",
                source_reason=str(action.get("reason") or "full_workflow_close_position"),
                market_evidence_price=self._position_action_market_evidence(
                    action=action,
                    feature_pack=feature_pack,
                ),
            )
            d3_result = submit_phase_d3_controlled_exit(
                cfg=self.cfg,
                position=position,
                plan=plan,
                exit_intent=exit_intent,
                order_store=self.order_store,
                coinbase_client=self.client,
                human_ack=runtime_submit_ack,
                submit_live=True,
            )
            d3_report = {
                "status": d3_result.get("status"),
                "selected_exit_intent": exit_intent,
                "submit_result": d3_result,
                "readiness": d3_result.get("readiness"),
                "blockers": (d3_result.get("readiness") or {}).get("blockers", []) + d3_result.get("hard_blocks", []),
            }
        else:
            d3_report = build_phase_d3_controlled_live_exit_report(
                cfg=self.cfg,
                ticker=ticker,
                position=position,
                order_store=self.order_store,
                coinbase_client=self.client,
                exchange_rules=exchange_rules,
                submit_live=True,
                human_ack=runtime_submit_ack,
            )
            d3_result = d3_report.get("submit_result") if isinstance(d3_report.get("submit_result"), dict) else d3_report

        readiness = d3_result.get("readiness") or {}
        status = str(d3_result.get("status") or d3_report.get("status") or "")
        execution_record["d3_full_workflow_bridge"] = {
            "attempted": True,
            "phase": D3_PHASE,
            "action_type": action_type,
            "submit_live": True,
            "coinbase_client_present": getattr(self, "client", None) is not None,
            "human_ack_source": "phase_d3_runtime_submit_ack",
            "status": status,
            "readiness_status": readiness.get("status"),
            "readiness_ready": readiness.get("ready"),
            "blockers": d3_report.get("blockers", []),
            "market_order_allowed": False,
        }
        execution_record["d3_controlled_exit_report"] = d3_report
        execution_record["executed"] = bool(d3_result.get("live_order_submitted"))
        if status == D3_BLOCKED or readiness.get("ready") is False:
            execution_record["status"] = "d3_controlled_exit_blocked_by_readiness"
        else:
            execution_record["status"] = status or "d3_controlled_exit_result_unknown"
        self._write_jsonl("execution.jsonl", execution_record)
        return execution_record

    def _handle_position_action(
        self,
        ticker: str,
        position: Dict[str, Any],
        action: Dict[str, Any],
        feature_pack: Dict[str, Any],
    ) -> Dict[str, Any]:
        action_type = str(action.get("action", "hold")).lower().strip()

        execution_record: Dict[str, Any] = {
            "ticker": ticker,
            "position_before": position,
            "position_action": action,
            "mode": self.cfg.execution_mode,
            "executed": False,
        }

        metadata = action.get("metadata", {}) or {}
        updated_position = metadata.get("updated_position")
        inventory_plan = metadata.get("inventory_plan") or {}

        if action_type == "hold":
            if updated_position:
                self.state.upsert_position(ticker, updated_position)

            execution_record["status"] = "hold_position"
            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        side = str(action.get("side", "NONE")).upper().strip()
        requested_size_base = self._to_decimal(action.get("size_base"), "0")
        current_price = self._to_decimal(
            metadata.get("current_price")
            or feature_pack.get("market", {}).get("mid_price"),
            "0",
        )

        if side != "SELL" or requested_size_base <= Decimal("0"):
            execution_record["status"] = "position_action_rejected"
            execution_record["reason"] = "invalid_position_action"
            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        working_position = dict(updated_position or position)
        inventory_state = self._extract_position_inventory_state(working_position)
        bot_managed_base_before = inventory_state["bot_managed_base"]
        legacy_inventory_base_before = inventory_state["legacy_inventory_base"]

        if not inventory_plan:
            live_available_fallback = bot_managed_base_before + legacy_inventory_base_before
            inventory_plan = self._compute_inventory_sell_plan(
                ticker=ticker,
                position=working_position,
                action_type=action_type,
                requested_bot_sell_base=min(requested_size_base, bot_managed_base_before),
                live_available_base=live_available_fallback,
            )

        planned_sell_total_base = self._to_decimal(inventory_plan.get("sell_total_base"), str(requested_size_base))
        planned_sell_bot_base = self._to_decimal(
            inventory_plan.get("sell_bot_base"),
            str(min(requested_size_base, bot_managed_base_before)),
        )
        planned_sell_legacy_base = self._to_decimal(inventory_plan.get("sell_legacy_base"), "0")

        execution_record["inventory_plan"] = inventory_plan

        if self.cfg.execution_mode == "paper":
            execution_record["status"] = "paper_position_exit"
            execution_record["paper_order"] = {
                "ticker": ticker,
                "side": side,
                "size_base": str(planned_sell_total_base),
                "bot_managed_base_sold": str(planned_sell_bot_base),
                "legacy_inventory_base_sold": str(planned_sell_legacy_base),
            }

            realized_pnl = self._compute_realized_pnl(
                position=working_position,
                exit_base_size=planned_sell_bot_base,
                exit_price=current_price,
            )
            self.state.add_realized_pnl(realized_pnl)

            remaining_bot_managed_base = max(Decimal("0"), bot_managed_base_before - planned_sell_bot_base)
            remaining_legacy_inventory_base = max(Decimal("0"), legacy_inventory_base_before - planned_sell_legacy_base)

            self.state.upsert_position(
                ticker,
                {
                    "bot_managed_base": str(remaining_bot_managed_base),
                    "legacy_inventory_base": str(remaining_legacy_inventory_base),
                    "baseline_inventory_base": str(remaining_legacy_inventory_base),
                    "inventory_last_sell_scope": str(inventory_plan.get("sell_scope", "bot_only")),
                    "inventory_last_extra_sell_base": str(planned_sell_legacy_base),
                    "position_size_base": str(remaining_bot_managed_base),
                    "position_size_quote": str(remaining_bot_managed_base * current_price),
                },
            )

            if action_type == "close" or remaining_bot_managed_base <= self.position_epsilon_base:
                closed_position = self.state.mark_position_closed(
                    ticker=ticker,
                    close_reason=str(action.get("reason", "")),
                    close_price=str(current_price),
                    realized_pnl=realized_pnl,
                )
                self._record_trade_reflection(
                    ticker=ticker,
                    position_before=working_position,
                    closed_position=closed_position,
                    action=action,
                    feature_pack=feature_pack,
                    chart_patterns=build_chart_pattern_context(feature_pack),
                    trade_plan=metadata.get("trade_plan") or {},
                    judge=metadata.get("judge") or {
                        "decision": action.get("reason", "paper_position_exit"),
                        "strategy": action.get("reason", "paper_position_exit"),
                    },
                    execution_record=execution_record,
                    realized_pnl=realized_pnl,
                    exit_price=current_price,
                    source="paper_position_exit",
                )
            else:
                self.state.upsert_position(
                    ticker,
                    {
                        "position_size_base": str(remaining_bot_managed_base),
                        "position_size_quote": str(remaining_bot_managed_base * current_price),
                        "updated_at": self._now_iso(),
                    },
                )

            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        # A live SELL is only permitted through the D3 controlled reduce-only
        # boundary.  In particular, do not inspect balances and then mutate
        # local state before D3 has produced its auditable readiness result.
        # D3 owns balance/reservation checks at its own submit boundary.
        sell_size_base = min(planned_sell_total_base, bot_managed_base_before)
        execution_record["sell_size_base_for_d3"] = str(sell_size_base)
        if sell_size_base <= self.position_epsilon_base:
            execution_record["status"] = "d3_blocked_no_local_managed_base"
            execution_record["blocker"] = "valid_filled_position_evidence_missing_or_zero"
            self._write_jsonl("execution.jsonl", execution_record)
            return execution_record

        d3_bridge_result = self._maybe_route_full_workflow_position_exit_to_d3(
            ticker=ticker,
            position=working_position,
            action=action,
            feature_pack=feature_pack,
            action_type=action_type,
            side=side,
            sell_size_base=sell_size_base,
            execution_record=execution_record,
        )
        if d3_bridge_result is not None:
            return d3_bridge_result

        execution_record["status"] = "d3_controlled_exit_blocked_by_policy"
        execution_record["blocker"] = "full_workflow_d3_preconditions_not_met"
        execution_record["executed"] = False
        self._write_jsonl("execution.jsonl", execution_record)
        return execution_record

    def _heartbeat_requires_forced_risk_action(self, heartbeat: Dict[str, Any]) -> bool:
        decision = str(heartbeat.get("decision", "")).strip().lower()
        reasons = [str(r).strip().lower() for r in heartbeat.get("reasons", [])]
        if decision != "full_review":
            return False
        critical_tokens = {
            "stop_breached_or_below_invalidation",
            "spread_above_allowed_threshold",
            "material_adverse_move_with_bearish_trend_context",
        }
        return any(token in reasons for token in critical_tokens)

    def _build_forced_risk_close_action(
        self,
        ticker: str,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
        *,
        reason: str,
        current_price: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        market_price = current_price if current_price is not None else self._to_decimal(
            feature_pack.get("market", {}).get("mid_price"),
            "0",
        )
        if market_price <= Decimal("0"):
            market_price = self._to_decimal(feature_pack.get("market", {}).get("best_bid"), "0")
        inventory_state = self._extract_position_inventory_state(position)
        bot_managed_base = inventory_state["bot_managed_base"]
        live_available_base = self._get_live_available_base(ticker)
        requested_size_base = bot_managed_base if bot_managed_base > Decimal("0") else live_available_base
        requested_size_base = min(requested_size_base, live_available_base if live_available_base > Decimal("0") else requested_size_base)
        size_quote = requested_size_base * market_price if market_price > Decimal("0") else Decimal("0")

        return {
            "action": "close",
            "reason": reason,
            "side": "SELL",
            "size_base": str(requested_size_base),
            "size_quote": str(size_quote),
            "stop_price": str(position.get("stop_price", "0")),
            "take_profit_price": str(position.get("take_profit_price", "0")),
            "trailing_active": bool(position.get("trailing_active", False)),
            "metadata": {
                "ticker": ticker,
                "current_price": str(market_price),
                "forced_risk_override": True,
                "updated_position": position,
                "inventory_state": {
                    "bot_managed_base": str(bot_managed_base),
                    "live_available_base": str(live_available_base),
                },
            },
        }

    def _build_risk_override_cycle_result(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        existing_position: Dict[str, Any],
        heartbeat: Dict[str, Any],
        *,
        source: str,
    ) -> Dict[str, Any]:
        current_price = self._to_decimal(feature_pack.get("market", {}).get("mid_price"), "0")
        action = self.position_manager.evaluate_position(
            ticker=ticker,
            position=existing_position,
            feature_pack=feature_pack,
            judge=None,
        )

        action_type = str(action.get("action", "hold")).strip().lower()
        if action_type == "hold":
            action = self._build_forced_risk_close_action(
                ticker=ticker,
                position=existing_position,
                feature_pack=feature_pack,
                reason="heartbeat_stop_breach_override",
                current_price=current_price,
            )
            action_type = "close"

        position_execution = self._handle_position_action(
            ticker=ticker,
            position=existing_position,
            action=action,
            feature_pack=feature_pack,
        )

        decision = "close_position" if action_type == "close" else "reduce_size" if action_type == "reduce" else "wait"
        side = "SELL" if decision in {"close_position", "reduce_size"} else "NONE"
        size_quote = self._to_decimal(action.get("size_quote"), "0")
        size_base = self._to_decimal(action.get("size_base"), "0")

        execution_status = str(position_execution.get("status", "unknown")).strip().lower()
        if decision == "close_position" and execution_status == "hold_position":
            # make the failure explicit for logs and replication instead of silently looking healthy
            position_execution = dict(position_execution)
            position_execution["status"] = "risk_override_sell_not_executed"
            position_execution["reason"] = position_execution.get("reason") or "forced_close_not_executed"

        analysis = {
            "decision": decision,
            "ticker": ticker,
            "side": side,
            "strategy": "heartbeat_stop_breach_override",
            "confidence": 100,
            "size_quote": float(size_quote),
            "size_base": str(size_base),
            "reasons": ["heartbeat_detected_stop_breach", *[str(r) for r in heartbeat.get("reasons", [])]],
            "must_reject_if": [],
            "setup_type": "unknown",
        }
        result = {
            "ticker": ticker,
            "analysis": analysis,
            "entry_gate": {
                "decision": "position_risk_override",
                "priority": "critical",
                "setup_type": "unknown",
                "confidence": 100,
                "reasons": ["existing_open_position_triggered_forced_risk_override", *[str(r) for r in heartbeat.get("reasons", [])]],
                "warnings": [],
            },
            "position_execution": position_execution,
            "heartbeat": heartbeat,
            "status": "risk_management_override" if source == "heartbeat" else "position_risk_override",
        }
        return result

    def _run_open_position_hourly_check(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        existing_position: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self._position_monitoring_enabled_for(existing_position):
            payload = {
                "generated_at": self._now_iso(),
                "ticker": ticker,
                "heartbeat": {
                    "decision": "disabled",
                    "reasons": ["position_monitoring_disabled_or_position_not_open"],
                },
            }
            self._write_jsonl("heartbeat.jsonl", payload)
            return {
                "ticker": ticker,
                "heartbeat": payload["heartbeat"],
                "status": "heartbeat_skipped",
            }

        if self.state.position_heartbeat_paused(ticker):
            payload = {
                "generated_at": self._now_iso(),
                "ticker": ticker,
                "heartbeat": {
                    "decision": "paused",
                    "reasons": ["position_heartbeat_temporarily_paused"],
                },
            }
            self._write_jsonl("heartbeat.jsonl", payload)
            return {
                "ticker": ticker,
                "heartbeat": payload["heartbeat"],
                "status": "heartbeat_paused",
            }

        heartbeat = self._position_heartbeat_prefilter(
            ticker=ticker,
            position=existing_position,
            feature_pack=feature_pack,
        )

        if heartbeat["decision"] == "ok":
            self.state.mark_position_heartbeat_ok(
                ticker=ticker,
                reason="; ".join(heartbeat.get("reasons", [])),
                extra={
                    "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
                },
            )
            self._write_jsonl(
                "heartbeat.jsonl",
                {
                    "generated_at": self._now_iso(),
                    "ticker": ticker,
                    "heartbeat": heartbeat,
                    "status": "heartbeat_ok",
                },
            )
            return {
                "ticker": ticker,
                "heartbeat": heartbeat,
                "status": "heartbeat_ok",
            }

        if heartbeat["decision"] == "position_watch":
            self.state.mark_position_heartbeat_warning(
                ticker=ticker,
                reason="; ".join(heartbeat.get("reasons", [])),
                extra={
                    "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
                },
            )

            position_watch = self._run_position_watch(
                ticker=ticker,
                position=existing_position,
                feature_pack=feature_pack,
                heartbeat=heartbeat,
            )

            if not self._position_watch_requests_full_review(position_watch):
                non_escalated_decision = str(position_watch.get("decision", "hold_ok")).strip().lower()
                review_result = "position_watch_hold_ok" if non_escalated_decision == "hold_ok" else f"position_watch_{non_escalated_decision}"
                heartbeat_warning_count = 0 if non_escalated_decision == "hold_ok" else int(existing_position.get("heartbeat_warning_count", 0) or 0)
                self.state.mark_position_deepseek_review(
                    ticker=ticker,
                    result=review_result,
                    reason="; ".join(position_watch.get("reasons", [])),
                    extra={
                        "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
                        "heartbeat_warning_count": heartbeat_warning_count,
                    },
                )
                return {
                    "ticker": ticker,
                    "heartbeat": heartbeat,
                    "position_watch": position_watch,
                    "status": review_result,
                }

            analysis = self.analyze_ticker(
                ticker=ticker,
                feature_pack_override=feature_pack,
                existing_position=existing_position,
            )

            self.state.mark_position_full_review(
                ticker=ticker,
                result="escalate_full_review",
                reason="; ".join(position_watch.get("reasons", [])),
                extra={
                    "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
                },
            )

            cycle_result = self._analysis_to_cycle_result(
                ticker=ticker,
                analysis=analysis,
                existing_position=existing_position,
            )
            cycle_result["heartbeat"] = heartbeat
            cycle_result["position_watch"] = position_watch
            cycle_result["status"] = "position_watch_escalated_full_review"
            return cycle_result

        self.state.mark_position_heartbeat_warning(
            ticker=ticker,
            reason="; ".join(heartbeat.get("reasons", [])),
            extra={
                "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
            },
        )

        if self._heartbeat_requires_forced_risk_action(heartbeat):
            self.state.mark_position_full_review(
                ticker=ticker,
                result="risk_management_override",
                reason="; ".join(heartbeat.get("reasons", [])),
                extra={
                    "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
                },
            )
            return self._build_risk_override_cycle_result(
                ticker=ticker,
                feature_pack=feature_pack,
                existing_position=existing_position,
                heartbeat=heartbeat,
                source="heartbeat",
            )

        analysis = self.analyze_ticker(
            ticker=ticker,
            feature_pack_override=feature_pack,
            existing_position=existing_position,
        )

        self.state.mark_position_full_review(
            ticker=ticker,
            result="escalate_full_review",
            reason="; ".join(heartbeat.get("reasons", [])),
            extra={
                "position_plan_snapshot": existing_position.get("position_plan_snapshot", {}),
            },
        )

        cycle_result = self._analysis_to_cycle_result(
            ticker=ticker,
            analysis=analysis,
            existing_position=existing_position,
        )
        cycle_result["heartbeat"] = heartbeat
        cycle_result["status"] = "heartbeat_full_review"
        return cycle_result

    def run_position_heartbeat_cycle(self) -> Dict[str, Any]:
        set_current_cycle_id(f"heartbeat_{self._now_iso()}")
        all_results: List[Dict[str, Any]] = []

        inventory_sync_meta = self._sync_exchange_inventory_positions()
        positions = self.state.get_positions()
        open_position_tickers = self._unique_tickers([
            str(p.get("ticker", "")).upper().strip()
            for p in positions.values()
            if str(p.get("status", "open")).lower() == "open"
        ])

        if not open_position_tickers:
            return {
                "generated_at": self._now_iso(),
                "results": [],
                "meta": {
                    "open_positions_evaluated": 0,
                    "heartbeat_ok": 0,
                    "deepseek_hold_ok": 0,
                    "full_reviews": 0,
                },
            }

        feature_packs, scan_errors = self._scan_market_universe(open_position_tickers)
        paper_order_cycle_summary = self._review_paper_open_orders_for_feature_packs(
            feature_packs,
            cycle_source="run_position_heartbeat_cycle",
        )
        all_results.extend(scan_errors)

        heartbeat_ok = 0
        deepseek_hold_ok = 0
        full_reviews = 0

        for ticker in open_position_tickers:
            feature_pack = feature_packs.get(ticker)
            existing_position = self.state.get_position(ticker)

            if not feature_pack or not existing_position:
                continue

            try:
                result = self._run_open_position_hourly_check(
                    ticker=ticker,
                    feature_pack=feature_pack,
                    existing_position=existing_position,
                )
                all_results.append(result)

                status = str(result.get("status", "")).lower()
                if status == "heartbeat_ok":
                    heartbeat_ok += 1
                elif status == "deepseek_hold_ok":
                    deepseek_hold_ok += 1
                elif status in {"deepseek_escalated_full_review", "heartbeat_full_review"}:
                    full_reviews += 1

            except Exception as e:
                all_results.append(self._log_error(ticker, e))

        return {
            "generated_at": self._now_iso(),
            "results": all_results,
            "meta": {
                "open_positions_evaluated": len(open_position_tickers),
                "heartbeat_ok": heartbeat_ok,
                "deepseek_hold_ok": deepseek_hold_ok,
                "full_reviews": full_reviews,
                "inventory_sync": inventory_sync_meta,
            },
        }

    def run_ticker_cycle(self, ticker: str) -> Dict[str, Any]:
        set_current_cycle_id(f"single_{self._now_iso()}_{ticker}")
        self._phase_c43_new_live_orders_this_cycle = 0
        self._sync_exchange_inventory_positions()
        self._review_phase_c43_live_entry_fills(cycle_source="run_ticker_cycle_start")
        feature_pack = self.market.build_feature_pack(ticker)
        self._review_paper_open_orders_for_feature_packs({ticker: feature_pack}, cycle_source="run_ticker_cycle")
        existing_position = self.state.get_position(ticker)

        analysis = self.analyze_ticker(
            ticker=ticker,
            feature_pack_override=feature_pack,
            existing_position=existing_position,
        )
        result = self._analysis_to_cycle_result(
            ticker=ticker,
            analysis=analysis,
            existing_position=existing_position,
        )
        self._record_decision_outcome_snapshot(
            ticker=ticker,
            analysis=analysis,
            cycle_result=result,
            feature_pack=feature_pack,
            source="run_ticker_cycle",
        )
        self._record_shadow_decision(
            ticker=ticker,
            analysis=analysis,
            cycle_result=result,
            feature_pack=feature_pack,
            source="run_ticker_cycle",
        )
        return result

    def run_cycle(self) -> Dict[str, Any]:
        set_current_cycle_id(f"full_{self._now_iso()}")
        all_results: List[Dict[str, Any]] = []
        self._phase_c43_new_live_orders_this_cycle = 0
        live_learning_context = self._refresh_live_learning_context()

        inventory_sync_meta = self._sync_exchange_inventory_positions()
        phase_c43_fill_reconciliation = self._review_phase_c43_live_entry_fills(cycle_source="run_cycle_start")
        positions = self.state.get_positions()
        open_position_tickers = self._unique_tickers([
            str(p.get("ticker", "")).upper().strip()
            for p in positions.values()
            if str(p.get("status", "open")).lower() == "open"
        ])

        universe = self._unique_tickers(
            list(self.cfg.allowed_tickers) + open_position_tickers
        )

        feature_packs, scan_errors = self._scan_market_universe(universe)
        paper_order_cycle_summary = self._review_paper_open_orders_for_feature_packs(
            feature_packs,
            cycle_source="run_cycle",
        )
        decision_outcome_cycle_summary = self._evaluate_due_decision_outcomes(feature_packs)
        self._evaluate_due_shadow_outcomes(feature_packs)
        all_results.extend(scan_errors)

        processed_tickers = set()
        for ticker in open_position_tickers:
            feature_pack = feature_packs.get(ticker)
            existing_position = self.state.get_position(ticker)
            if not feature_pack or not existing_position:
                continue

            try:
                feature_pack.setdefault("decision_context", {})["live_learning"] = live_learning_context
                feature_pack = self._inject_execution_context(ticker, feature_pack)
                feature_pack = self._inject_bounded_exploration_context(feature_pack)
                feature_pack = self._inject_market_intelligence_context(feature_pack)
                feature_pack = self._inject_neural_shadow_context(ticker, feature_pack)
                result = self._run_existing_position_cycle(
                    ticker=ticker,
                    feature_pack=feature_pack,
                    existing_position=existing_position,
                )
                all_results.append(result)
                processed_tickers.add(ticker)
            except Exception as e:
                all_results.append(self._log_error(ticker, e))
                processed_tickers.add(ticker)

        new_entry_tickers = [
            t for t in self.cfg.allowed_tickers
            if t not in processed_tickers and t in feature_packs
        ]

        breadth_context = self._build_market_breadth_context(feature_packs, new_entry_tickers)
        watch_memory = self._get_watch_memory()

        prefiltered: List[Dict[str, Any]] = []
        for ticker in new_entry_tickers:
            try:
                feature_packs[ticker].setdefault("decision_context", {})["live_learning"] = live_learning_context
                feature_packs[ticker].setdefault("decision_context", {})["market_breadth"] = breadth_context
                feature_packs[ticker] = self._inject_execution_context(ticker, feature_packs[ticker])
                feature_packs[ticker] = self._inject_bounded_exploration_context(feature_packs[ticker])
                feature_packs[ticker] = self._inject_market_intelligence_context(feature_packs[ticker])
                feature_packs[ticker].setdefault("decision_context", {})["pending_trade_plan"] = self._build_pending_trade_plan_context(
                    ticker,
                    feature_packs[ticker],
                )
                feature_packs[ticker].setdefault("decision_context", {})["pending_order_intent"] = self._build_pending_order_intent_context(ticker)
                feature_packs[ticker] = self._inject_neural_shadow_context(ticker, feature_packs[ticker])
                pre = self._cheap_prefilter_candidate(
                    ticker,
                    feature_packs[ticker],
                    breadth_context=breadth_context,
                    watch_memory=watch_memory,
                )
                pre = self._apply_pending_plan_to_prefilter(ticker, feature_packs[ticker], pre)
                pre = self._apply_pending_order_intent_to_prefilter(ticker, feature_packs[ticker], pre)
                prefiltered.append({
                    "ticker": ticker,
                    "feature_pack": feature_packs[ticker],
                    "prefilter": pre,
                })
            except Exception as e:
                all_results.append(self._log_error(ticker, e))

        if getattr(self.cfg, "enable_candidate_ranking", True):
            prefiltered.sort(
                key=lambda x: int(x["prefilter"].get("prefilter_score", 0)),
                reverse=True,
            )

        max_gate_candidates = getattr(
            self.cfg,
            "max_candidates_for_deepseek_gate",
            max(4, min(8, getattr(self.cfg, "max_candidates_for_deep_analysis", 3) * 2)),
        )
        max_full_analysis = getattr(self.cfg, "max_candidates_for_deep_analysis", 3)

        selected_for_gate = prefiltered[:max_gate_candidates]
        selected_gate_tickers = {row["ticker"] for row in selected_for_gate}

        for row in prefiltered:
            ticker = row["ticker"]
            if ticker in selected_gate_tickers:
                continue
            try:
                result = self._build_gate_only_skip_result(
                    ticker=ticker,
                    feature_pack=row["feature_pack"],
                    prefilter=row["prefilter"],
                )
                self._update_watch_memory(ticker, row["prefilter"], result.get("entry_gate", {}))
                all_results.append(result)
                self._record_shadow_decision(
                    ticker=ticker,
                    analysis={},
                    cycle_result=result,
                    feature_pack=row["feature_pack"],
                    source="run_cycle_gate_skip",
                )
            except Exception as e:
                all_results.append(self._log_error(ticker, e))

        gated_rows: List[Dict[str, Any]] = []
        for row in selected_for_gate:
            ticker = row["ticker"]
            feature_pack = row["feature_pack"]
            prefilter = row["prefilter"]

            try:
                deepseek_pack = self._run_deepseek_preprocess(ticker, feature_pack)
                entry_gate = self._run_entry_gate(ticker, feature_pack, deepseek_pack)
                gate_rank = self._gate_rank_score(prefilter, entry_gate)

                self._update_watch_memory(ticker, prefilter, entry_gate)
                gated_rows.append({
                    "ticker": ticker,
                    "feature_pack": feature_pack,
                    "prefilter": prefilter,
                    "deepseek_pack": deepseek_pack,
                    "entry_gate": entry_gate,
                    "gate_rank": gate_rank,
                })
            except Exception as e:
                all_results.append(self._log_error(ticker, e))

        gated_rows.sort(key=lambda x: int(x.get("gate_rank", 0)), reverse=True)

        selected_for_full: List[Dict[str, Any]] = []
        for row in gated_rows:
            if len(selected_for_full) >= max_full_analysis:
                break
            decision = str(row["entry_gate"].get("decision", "watch")).lower()
            if decision in {"analyze", "priority_analyze"}:
                selected_for_full.append(row)

        # Pending-plan triggers are monitoring triggers, not execution permission.
        # They should nevertheless force a fresh full GPT-5.5 planner/judge pass
        # so the saved plan is revalidated from scratch instead of being lost at
        # the cheaper gate layer. The final judge and deterministic risk/firewall
        # still remain mandatory before any order can be placed.
        if len(selected_for_full) < max_full_analysis:
            for row in gated_rows:
                if len(selected_for_full) >= max_full_analysis:
                    break
                if row in selected_for_full:
                    continue
                pending_ctx = ((row.get("feature_pack") or {}).get("decision_context") or {}).get("pending_trade_plan") or {}
                if bool(pending_ctx.get("should_force_full_analysis") or pending_ctx.get("trigger_ready")):
                    row["entry_gate"].setdefault("reasons", []).append(
                        "pending_trade_plan_trigger_promoted_to_fresh_full_analysis"
                    )
                    row["entry_gate"].setdefault("warnings", []).append(
                        "pending_plan_trigger_is_not_execution_permission_requires_new_judge_and_risk_check"
                    )
                    selected_for_full.append(row)

        # Phase B.7: paper pending order-intents can promote a ticker back to
        # fresh full analysis, but never to execution. The fresh GPT/judge/risk
        # path remains mandatory and live limit-order switches are still off.
        if len(selected_for_full) < max_full_analysis:
            for row in gated_rows:
                if len(selected_for_full) >= max_full_analysis:
                    break
                if row in selected_for_full:
                    continue
                pending_order_ctx = ((row.get("feature_pack") or {}).get("decision_context") or {}).get("pending_order_intent") or {}
                if bool(pending_order_ctx.get("should_force_full_analysis") or pending_order_ctx.get("trigger_ready")):
                    row["entry_gate"].setdefault("reasons", []).append(
                        "paper_pending_order_intent_promoted_to_fresh_full_analysis"
                    )
                    row["entry_gate"].setdefault("warnings", []).append(
                        "paper_pending_order_intent_is_not_execution_permission_requires_new_judge_and_risk_check"
                    )
                    selected_for_full.append(row)

        if len(selected_for_full) < max_full_analysis:
            for row in gated_rows:
                if len(selected_for_full) >= max_full_analysis:
                    break
                if row in selected_for_full:
                    continue

                if self._watch_candidate_is_strong_enough_for_full_analysis(
                    feature_pack=row["feature_pack"],
                    prefilter=row["prefilter"],
                    entry_gate=row["entry_gate"],
                    gate_rank=int(row.get("gate_rank", 0)),
                ):
                    row["entry_gate"].setdefault("reasons", []).append(
                        "watch_promoted_to_full_analysis_by_ranked_selector"
                    )
                    if int(row["prefilter"].get("consecutive_constructive_watches", 0)) >= max(1, int(getattr(self.cfg, "watch_promotion_memory_cycles", 2)) - 1):
                        row["entry_gate"].setdefault("reasons", []).append(
                            "watch_promoted_with_memory_of_prior_constructive_cycles"
                        )
                    selected_for_full.append(row)

        selected_full_tickers = {row["ticker"] for row in selected_for_full}

        for row in gated_rows:
            ticker = row["ticker"]
            if ticker in selected_full_tickers:
                continue

            try:
                analysis = self._build_skip_analysis_result(
                    ticker=ticker,
                    feature_pack=row["feature_pack"],
                    deepseek_pack=row["deepseek_pack"],
                    entry_gate=row["entry_gate"],
                )
                result = self._build_gate_watch_result(
                    ticker=ticker,
                    analysis=analysis,
                )
                all_results.append(result)
                self._record_shadow_decision(
                    ticker=ticker,
                    analysis=analysis,
                    cycle_result=result,
                    feature_pack=row["feature_pack"],
                    source="run_cycle_gate_watch",
                )
            except Exception as e:
                all_results.append(self._log_error(ticker, e))

        for row in selected_for_full:
            ticker = row["ticker"]
            try:
                analysis = self._run_full_analysis_stack(
                    ticker=ticker,
                    feature_pack=row["feature_pack"],
                    deepseek_pack=row["deepseek_pack"],
                    entry_gate=row["entry_gate"],
                    existing_position=None,
                    pending_trade_plan=((row["feature_pack"].get("decision_context") or {}).get("pending_trade_plan") or None),
                )
                result = self._analysis_to_cycle_result(
                    ticker=ticker,
                    analysis=analysis,
                    existing_position=None,
                )
                self._record_decision_outcome_snapshot(
                    ticker=ticker,
                    analysis=analysis,
                    cycle_result=result,
                    feature_pack=row["feature_pack"],
                    source="run_cycle_full_analysis",
                )
                self._record_shadow_decision(
                    ticker=ticker,
                    analysis=analysis,
                    cycle_result=result,
                    feature_pack=row["feature_pack"],
                    source="run_cycle_full_analysis",
                )
                all_results.append(result)
            except Exception as e:
                all_results.append(self._log_error(ticker, e))

        trade_learning_summary = self._build_trade_learning_cycle_summary()

        return {
            "generated_at": self._now_iso(),
            "results": all_results,
            "meta": {
                "universe_size": len(universe),
                "open_positions_evaluated": len(open_position_tickers),
                "new_entry_universe_size": len(new_entry_tickers),
                "selected_for_gate": len(selected_for_gate),
                "selected_for_full_analysis": len(selected_for_full),
                "trade_learning": trade_learning_summary,
                "live_learning": live_learning_context,
                "decision_outcomes": decision_outcome_cycle_summary,
                "paper_orders": paper_order_cycle_summary,
            },
        }
