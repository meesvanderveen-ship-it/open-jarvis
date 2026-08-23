"""Bounded parameter catalogue for the GrowBot/River learning sidecar.

The registry is deliberately broader than the currently approved-profile
whitelist.  A parameter can therefore be researched and ranked without being
eligible for profile activation.  This keeps learning useful while preserving
the existing approved-profile and governor gates as the only runtime route.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST
from bot.autonomous_parameter_governor import ALLOWED_PARAMETERS as GOVERNOR_ALLOWED_PARAMETERS


REGISTRY_VERSION = "learnable_parameter_registry_v1"

# Deliberately narrower than ALLOWED_PARAMETERS/APPROVED_PARAMETER_PROFILE_WHITELIST:
# the parameters an operator has explicitly judged safe enough for the lower
# evidence-volume "fast_start_autotune" tier (small, reversible, fine_tuning-sized
# steps only). Membership here is necessary but not sufficient -- a parameter must
# also already be governor- and approved-profile-routable and not high-risk.
FAST_START_AUTOTUNE_ALLOWED_PARAMETERS = frozenset({
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
    "MAX_SPREAD_PCT",
})

# Allowlisted for fast_start, but the suggested step is halved versus the normal
# fine_tuning ceiling -- extra caution because spread changes affect fill/no-fill
# behaviour directly rather than only a downstream profitability threshold.
FAST_START_EXTRA_CAUTION_PARAMETERS = frozenset({"MAX_SPREAD_PCT"})

# Parameters an operator may want on the fast_start tier eventually, but the
# approved-profile route does not currently support them (not in the governor's
# ALLOWED_PARAMETERS / APPROVED_PARAMETER_PROFILE_WHITELIST, or marked high-risk).
# Recorded here only so the gap is explicit rather than silent.
FAST_START_PENDING_APPROVED_PROFILE_SUPPORT = {
    "JUDGE_MIN_GATE_CONFIDENCE": (
        "not in autonomous_parameter_governor.ALLOWED_PARAMETERS or "
        "APPROVED_PARAMETER_PROFILE_WHITELIST, and registry safety_class is "
        "high_risk_manual_only; remains manual-governance-only until the "
        "approved-profile route is deliberately extended for this parameter"
    ),
}


@dataclass(frozen=True)
class LearnableParameter:
    name: str
    category: str
    runtime_key: str
    default: float
    minimum: float
    maximum: float
    unit: str
    loosen_change: str
    dependencies: Tuple[str, ...]
    evidence_requirements: Tuple[str, ...]
    rollback: Tuple[str, ...]
    safety_class: str = "human_review_required"
    implementation_status: str = "runtime_configured"

    def activation_route(self) -> str:
        if self.name in GOVERNOR_ALLOWED_PARAMETERS and self.name in APPROVED_PARAMETER_PROFILE_WHITELIST:
            return "current_governor_and_approved_profile"
        if self.name in APPROVED_PARAMETER_PROFILE_WHITELIST:
            return "approved_profile_only_manual_governance"
        if self.implementation_status == "logical_candidate_only":
            return "research_only_profile_extension_required"
        return "adaptive_review_only_not_currently_profile_routable"

    def fast_start_autotune_allowed(self) -> bool:
        """Whether this parameter may be considered for the lower-evidence
        fast_start_autotune tier. Never sufficient on its own to apply anything --
        the unchanged autonomous_parameter_governor ACK/cooldown/candidate-hash
        gates remain the only real authorization path."""
        return (
            self.name in FAST_START_AUTOTUNE_ALLOWED_PARAMETERS
            and self.name in GOVERNOR_ALLOWED_PARAMETERS
            and self.name in APPROVED_PARAMETER_PROFILE_WHITELIST
            and self.safety_class == "human_review_required"
            and self.implementation_status == "runtime_configured"
        )

    def fast_start_max_step_pct(self) -> Optional[float]:
        """Fine_tuning-sized step ceiling for a fast_start candidate, or None if
        this parameter is not fast_start-allowlisted at all."""
        if not self.fast_start_autotune_allowed():
            return None
        from bot.parameter_step_scheduler import PHASES  # deferred: avoids import cycle

        ceiling = float(PHASES["fine_tuning"]["max_step_pct"])
        return ceiling / 2.0 if self.name in FAST_START_EXTRA_CAUTION_PARAMETERS else ceiling

    def to_dict(self, *, current_value: Optional[float] = None) -> Dict[str, Any]:
        return {
            "parameter": self.name,
            "category": self.category,
            "runtime_key": self.runtime_key,
            "current_value": self.default if current_value is None else current_value,
            "default_value": self.default,
            "min": self.minimum,
            "max": self.maximum,
            "unit": self.unit,
            "loosen_change": self.loosen_change,
            "step_pct_by_phase": {
                "coarse_tuning": {"min": 5.0, "max": 15.0},
                "stabilization": {"min": 2.0, "max": 5.0},
                "fine_tuning": {"min": 0.25, "max": 2.0},
            },
            "dependencies": list(self.dependencies),
            "rollback": list(self.rollback),
            "evidence_requirements": list(self.evidence_requirements),
            "safety_class": self.safety_class,
            "implementation_status": self.implementation_status,
            "activation_route": self.activation_route(),
            "approved_profile_supported": self.name in APPROVED_PARAMETER_PROFILE_WHITELIST,
            "governor_supported": self.name in GOVERNOR_ALLOWED_PARAMETERS,
            "fast_start_autotune_allowed": self.fast_start_autotune_allowed(),
            "fast_start_max_step_pct": self.fast_start_max_step_pct(),
            "automatic_activation_allowed": False,
        }


def _p(
    name: str,
    category: str,
    default: float,
    minimum: float,
    maximum: float,
    unit: str,
    loosen_change: str,
    dependencies: Iterable[str],
    evidence: Iterable[str],
    *,
    safety_class: str = "human_review_required",
    implementation_status: str = "runtime_configured",
) -> LearnableParameter:
    return LearnableParameter(
        name=name,
        category=category,
        runtime_key=name,
        default=default,
        minimum=minimum,
        maximum=maximum,
        unit=unit,
        loosen_change=loosen_change,
        dependencies=tuple(dependencies),
        evidence_requirements=tuple(evidence),
        rollback=(
            "retain_previous_approved_profile_hash",
            "validate_BotConfig_before_activation",
            "governor_backup_and_rollback_plan_required",
            "post_change_holdout_and_health_review_required",
        ),
        safety_class=safety_class,
        implementation_status=implementation_status,
    )


# `loosen_change` describes the numerical direction of a less strict setting;
# it is not an instruction to change the live runtime.
_PARAMETERS: Tuple[LearnableParameter, ...] = (
    # Entry quality / deterministic D.2 gates.
    _p("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "entry_quality", 0.0125, 0.0025, 0.0500, "decimal_pct", "decrease", ("fee_model", "spread_cost", "D2_risk_gate"), ("cost_aware_outcomes", "missed_opportunity_labels", "walk_forward_validation")),
    _p("PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "entry_quality", 3.0, 1.0, 8.0, "ratio", "decrease", ("fee_model", "exit_distance"), ("fee_impact", "closed_trade_outcomes", "walk_forward_validation")),
    _p("PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "entry_quality", 1.5, 1.0, 5.0, "ratio", "decrease", ("stop_distance", "target_distance"), ("mae_mfe_distribution", "closed_trade_outcomes", "walk_forward_validation")),
    _p("JUDGE_MIN_GATE_CONFIDENCE", "entry_quality", 62.0, 45.0, 90.0, "score", "decrease", ("judge_schema", "deterministic_risk"), ("decision_outcomes", "bad_entry_labels", "regime_coverage"), safety_class="high_risk_manual_only"),
    _p("JUDGE_MIN_SYNTH_CONFIDENCE", "entry_quality", 60.0, 45.0, 90.0, "score", "decrease", ("judge_schema",), ("decision_outcomes", "reflection_labels"), safety_class="high_risk_manual_only"),
    _p("PENDING_TRADE_PLAN_MIN_CONFIDENCE", "entry_quality", 60.0, 45.0, 90.0, "score", "decrease", ("pending_plan_workflow",), ("pending_plan_outcomes", "missed_opportunity_labels")),
    _p("PENDING_TRADE_PLAN_TRIGGER_SCORE", "entry_quality", 88.0, 60.0, 98.0, "score", "decrease", ("pending_plan_workflow",), ("pending_plan_outcomes", "no_chase_evidence")),
    _p("SETUP_TRIGGER_STRICTNESS", "entry_quality", 1.0, 0.50, 1.50, "multiplier", "decrease", ("setup_type", "judge_context"), ("setup_segmented_outcomes", "multi_regime_evidence"), implementation_status="logical_candidate_only"),
    # C4.3 / orderbook entry quality.
    _p("MAX_SPREAD_PCT", "orderbook_c43", 0.0060, 0.0010, 0.0200, "decimal_pct", "increase", ("fee_model", "orderbook_snapshot"), ("spread_distribution", "fills_no_fills", "adverse_selection")),
    _p("ORDERBOOK_ENTRY_MAX_DISTANCE_FROM_MID_PCT", "orderbook_c43", 0.0030, 0.0005, 0.0100, "decimal_pct", "increase", ("maker_offset", "orderbook_snapshot"), ("fill_quality", "no_fill_followup", "slippage_analysis")),
    _p("ORDERBOOK_ENTRY_MAX_TTL_MINUTES", "orderbook_c43", 60.0, 5.0, 240.0, "minutes", "increase", ("entry_lifecycle", "cancel_policy"), ("fill_latency", "stale_order_analysis", "missed_opportunities")),
    _p("ORDERBOOK_ENTRY_MAX_REPLACES_PER_ORDER", "orderbook_c43", 1.0, 0.0, 3.0, "count", "increase", ("cancel_replace_safety",), ("cancel_replace_churn", "fill_quality", "retry_storm_review"), safety_class="high_risk_manual_only"),
    _p("MAX_ORDER_REPLACES_PER_TICKER_PER_HOUR", "orderbook_c43", 1.0, 0.0, 4.0, "count", "increase", ("cancel_replace_safety",), ("cancel_replace_churn", "lifecycle_safety_review"), safety_class="never_auto_change"),
    _p("ORDERBOOK_MAKER_OFFSET_PCT", "orderbook_c43", 0.0010, 0.0, 0.0100, "decimal_pct", "increase", ("post_only", "best_bid_ask"), ("orderbook_snapshots", "fill_quality", "fee_impact"), implementation_status="logical_candidate_only"),
    _p("ORDERBOOK_LIQUIDITY_MIN_SCORE", "orderbook_c43", 0.50, 0.10, 0.95, "score", "decrease", ("orderbook_snapshot", "market_data"), ("liquidity_distribution", "no_fill_analysis", "adverse_selection"), implementation_status="logical_candidate_only"),
    _p("ORDERBOOK_IMBALANCE_MIN_ABS", "orderbook_c43", 0.15, 0.02, 0.80, "ratio", "decrease", ("orderbook_snapshot", "regime"), ("imbalance_fill_quality", "regime_segmented_outcomes"), implementation_status="logical_candidate_only"),
    # Sizing.  The registry can rank these, but high-risk values remain manual.
    _p("DEFAULT_QUOTE_SIZE_USDC", "sizing", 50.0, 5.0, 100.0, "quote_usdc", "increase", ("min_live_quote", "max_live_quote", "drawdown_limits"), ("sizing_sensitivity", "drawdown_analysis", "portfolio_exposure"), safety_class="high_risk_manual_only"),
    _p("MAX_NOTIONAL_USD", "sizing", 100.0, 10.0, 250.0, "quote_usdc", "increase", ("portfolio_risk", "max_daily_loss"), ("portfolio_exposure", "tail_risk", "drawdown_analysis"), safety_class="high_risk_manual_only"),
    _p("AUTONOMOUS_MAX_ORDER_QUOTE", "sizing", 100.0, 5.0, 120.0, "quote_usdc", "increase", ("max_notional", "live_quote_caps"), ("sizing_sensitivity", "safety_cap_review"), safety_class="high_risk_manual_only"),
    _p("MIN_DYNAMIC_ENTRY_QUOTE_USDC", "sizing", 5.0, 5.0, 50.0, "quote_usdc", "decrease", ("min_live_quote",), ("fill_quality", "minimum_order_rejections"), safety_class="high_risk_manual_only"),
    _p("MAX_DYNAMIC_ENTRY_QUOTE_USDC", "sizing", 100.0, 10.0, 120.0, "quote_usdc", "increase", ("max_notional", "drawdown_limits"), ("sizing_sensitivity", "risk_tail"), safety_class="high_risk_manual_only"),
    _p("CONFIDENCE_TO_SIZE_MULTIPLIER", "sizing", 1.0, 0.25, 1.50, "multiplier", "increase", ("confidence_calibration", "sizing_model"), ("calibration_report", "size_conditioned_pnl", "drawdown"), implementation_status="logical_candidate_only"),
    _p("EDGE_TO_SIZE_MULTIPLIER", "sizing", 1.0, 0.25, 1.50, "multiplier", "increase", ("net_edge", "sizing_model"), ("cost_aware_edge", "size_conditioned_pnl"), implementation_status="logical_candidate_only"),
    _p("REGIME_SIZE_MULTIPLIER", "sizing", 1.0, 0.25, 1.25, "multiplier", "increase", ("regime_classifier", "portfolio_risk"), ("regime_segmented_pnl", "correlation_regime"), implementation_status="logical_candidate_only"),
    _p("VOLATILITY_SIZE_MULTIPLIER", "sizing", 1.0, 0.25, 1.25, "multiplier", "increase", ("volatility_regime", "risk_model"), ("volatility_segmented_drawdown", "mae_distribution"), implementation_status="logical_candidate_only"),
    _p("DRAWDOWN_SIZE_MULTIPLIER", "sizing", 1.0, 0.10, 1.0, "multiplier", "increase", ("drawdown_tracking", "risk_model"), ("drawdown_recovery", "tail_risk"), implementation_status="logical_candidate_only"),
    # D.2/D.3 exits.  These are research candidates unless already profile-routable.
    _p("EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT", "exit_d3", 0.0350, 0.0050, 0.1000, "decimal_pct", "increase", ("D3_exit_validity", "resistance_context"), ("exit_fill_quality", "stale_tp_analysis", "closed_trade_outcomes")),
    _p("PHASE_D2_DEFAULT_TIME_LIMIT_HOURS", "exit_d3", 48.0, 4.0, 168.0, "hours", "increase", ("D2_plan", "D3_lifecycle"), ("time_in_trade", "opportunity_cost", "exit_timeout_analysis")),
    _p("PHASE_D2_DEFAULT_TRAILING_ACTIVATION_PCT", "exit_d3", 0.0250, 0.0050, 0.1000, "decimal_pct", "decrease", ("trailing_preview", "D3_exit_plan"), ("trailing_path_simulation", "runner_outcomes")),
    _p("PHASE_D2_DEFAULT_TRAILING_DISTANCE_PCT", "exit_d3", 0.0180, 0.0050, 0.1000, "decimal_pct", "increase", ("trailing_preview", "D3_exit_plan"), ("trailing_path_simulation", "mae_mfe_distribution")),
    _p("TP1_ALLOCATION_PCT", "exit_d3", 0.50, 0.20, 0.90, "fraction", "increase", ("D2_exit_slices", "min_order_quote"), ("partial_tp_outcomes", "min_size_fallbacks"), implementation_status="logical_candidate_only"),
    _p("TP2_ALLOCATION_PCT", "exit_d3", 0.25, 0.00, 0.60, "fraction", "increase", ("D2_exit_slices", "TP1_ALLOCATION_PCT"), ("partial_tp_outcomes", "runner_outcomes"), implementation_status="logical_candidate_only"),
    _p("RUNNER_ALLOCATION_PCT", "exit_d3", 0.25, 0.00, 0.60, "fraction", "increase", ("D2_exit_slices", "TP1_ALLOCATION_PCT", "TP2_ALLOCATION_PCT"), ("runner_outcomes", "trailing_path_simulation"), implementation_status="logical_candidate_only"),
    _p("STOP_DISTANCE_PCT", "exit_d3", 0.0200, 0.0050, 0.1000, "decimal_pct", "increase", ("D2_risk_plan", "position_sizing"), ("mae_distribution", "avoided_loss", "risk_tail"), implementation_status="logical_candidate_only"),
    # Regime and market filters.
    _p("TICKER_SCORE_MIN", "regime_market_filters", 50.0, 20.0, 90.0, "score", "decrease", ("ticker_ranking", "market_breadth"), ("ticker_score_outcomes", "regime_coverage"), implementation_status="logical_candidate_only"),
    _p("VOLUME_CONFIRMATION_MIN", "regime_market_filters", 1.0, 0.25, 3.0, "multiplier", "decrease", ("volume_features",), ("volume_segmented_outcomes", "fill_quality"), implementation_status="logical_candidate_only"),
    _p("VOLATILITY_MAX_PCT", "regime_market_filters", 0.0300, 0.0050, 0.1500, "decimal_pct", "increase", ("volatility_regime", "risk_model"), ("volatility_segmented_outcomes", "adverse_selection"), implementation_status="logical_candidate_only"),
    _p("TREND_STRENGTH_MIN", "regime_market_filters", 25.0, 10.0, 60.0, "score", "decrease", ("trend_features",), ("trend_segmented_outcomes", "setup_performance"), implementation_status="logical_candidate_only"),
    _p("MARKET_INTELLIGENCE_WEIGHT", "regime_market_filters", 1.0, 0.0, 2.0, "weight", "increase", ("market_intelligence_context",), ("event_risk_outcomes", "news_quality_audit"), implementation_status="logical_candidate_only"),
    _p("REFLECTION_LEARNING_WEIGHT", "regime_market_filters", 1.0, 0.0, 2.0, "weight", "increase", ("reflection_ledger",), ("reflection_quality", "out_of_sample_validation"), implementation_status="logical_candidate_only"),
    _p("NEURAL_SHADOW_WEIGHT", "regime_market_filters", 1.0, 0.0, 1.0, "weight", "increase", ("neural_shadow_policy",), ("shadow_calibration", "holdout_validation"), implementation_status="logical_candidate_only"),
    # Workflow behaviour.  Limits that can increase order pressure are never automatic.
    _p("AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE", "workflow_behaviour", 1.0, 1.0, 2.0, "count", "increase", ("C43_order_budget", "open_order_safety"), ("order_budget_analysis", "overtrading_review"), safety_class="high_risk_manual_only"),
    _p("AUTONOMOUS_MAX_OPEN_ORDERS", "workflow_behaviour", 1.0, 1.0, 4.0, "count", "increase", ("C43_order_budget", "open_order_safety"), ("open_order_lifecycle", "duplicate_order_review"), safety_class="high_risk_manual_only"),
    _p("MAX_OPEN_POSITIONS", "workflow_behaviour", 3.0, 1.0, 6.0, "count", "increase", ("portfolio_risk", "order_budget"), ("position_cap_blocked_opportunities", "portfolio_exposure", "drawdown_analysis"), safety_class="high_risk_manual_only"),
    _p("COOLDOWN_MINUTES", "workflow_behaviour", 240.0, 15.0, 1440.0, "minutes", "decrease", ("ticker_state", "overtrading_guard"), ("decision_outcomes", "overtrading_analysis", "missed_opportunities")),
    _p("TICKER_ROTATION_LIMIT", "workflow_behaviour", 3.0, 1.0, 10.0, "count", "increase", ("ticker_ranking", "analysis_budget"), ("ticker_rotation_outcomes", "provider_cost_report"), implementation_status="logical_candidate_only"),
    _p("MISSED_OPPORTUNITY_SENSITIVITY", "workflow_behaviour", 1.0, 0.25, 2.0, "weight", "increase", ("decision_outcomes", "reflection_ledger"), ("missed_opportunity_precision", "false_positive_review"), implementation_status="logical_candidate_only"),
    _p("OVERTRADING_PENALTY", "workflow_behaviour", 1.0, 0.25, 3.0, "weight", "increase", ("order_budget", "cooldown"), ("overtrading_analysis", "drawdown_analysis"), implementation_status="logical_candidate_only"),
)


def parameter_definitions() -> Dict[str, LearnableParameter]:
    return {item.name: item for item in _PARAMETERS}


def get_parameter(name: str) -> Optional[LearnableParameter]:
    return parameter_definitions().get(str(name or "").strip())


def is_fast_start_autotune_allowed(name: str) -> bool:
    definition = get_parameter(name)
    return bool(definition and definition.fast_start_autotune_allowed())


def fast_start_max_step_pct_for(name: str) -> Optional[float]:
    definition = get_parameter(name)
    if definition is None:
        return None
    return definition.fast_start_max_step_pct()


def load_current_values(root: Path = Path(".")) -> Dict[str, float]:
    """Read only the approved profile; never load or mutate `.env`."""
    values = {item.name: item.default for item in _PARAMETERS}
    try:
        payload = json.loads((root / "state/approved_parameter_profile.json").read_text(encoding="utf-8"))
    except Exception:
        return values
    params = payload.get("parameters") if isinstance(payload, dict) else None
    if not isinstance(params, dict):
        return values
    for name, raw in params.items():
        if name not in values:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        definition = get_parameter(name)
        if definition and definition.minimum <= value <= definition.maximum:
            values[name] = value
    return values


def build_learnable_parameter_registry(root: Path = Path(".")) -> Dict[str, Any]:
    current = load_current_values(root)
    parameters = [item.to_dict(current_value=current.get(item.name)) for item in _PARAMETERS]
    by_category: Dict[str, int] = {}
    for item in parameters:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
    return {
        "schema_version": REGISTRY_VERSION,
        "parameter_count": len(parameters),
        "category_counts": by_category,
        "parameters": parameters,
        "safety_policy": {
            "registry_is_descriptive_not_executable": True,
            "parameter_mutation_allowed": False,
            "order_submission_allowed": False,
            "approved_profile_hash_ack_required": True,
            "governor_route_required_for_any_current_auto_route": True,
        },
    }


__all__ = [
    "FAST_START_AUTOTUNE_ALLOWED_PARAMETERS",
    "FAST_START_EXTRA_CAUTION_PARAMETERS",
    "FAST_START_PENDING_APPROVED_PROFILE_SUPPORT",
    "GOVERNOR_ALLOWED_PARAMETERS",
    "LearnableParameter",
    "REGISTRY_VERSION",
    "build_learnable_parameter_registry",
    "fast_start_max_step_pct_for",
    "get_parameter",
    "is_fast_start_autotune_allowed",
    "load_current_values",
    "parameter_definitions",
]
