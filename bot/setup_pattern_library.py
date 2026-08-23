from __future__ import annotations

from typing import Any, Dict, List

from bot.setup_pattern_schema import REQUIRED_SETUP_PATTERNS, SetupPatternSpec


PATTERN_SUPPORT: Dict[str, Dict[str, Any]] = {
    "trend_continuation": {
        "detected_by": "strategy_engine analyst stack + chart_patterns.higher_low_reclaim",
        "used_by_agent": "entry gate, trend analyst, synth, trade planner, final judge",
        "can_create_trade_plan": True,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": True,
        "has_entry_zone": True,
        "has_stop_logic": True,
        "has_target_logic": True,
        "has_tests": True,
        "priority": "P2",
    },
    "reclaim_reversal": {
        "detected_by": "strategy_engine analyst stack + support_sweep_reclaim",
        "used_by_agent": "entry gate, synth, trade planner, final judge",
        "can_create_trade_plan": True,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": True,
        "has_entry_zone": True,
        "has_stop_logic": True,
        "has_target_logic": True,
        "has_tests": True,
        "priority": "P2",
    },
    "mean_reversion": {
        "detected_by": "meanrev analyst + support/range context",
        "used_by_agent": "meanrev analyst, synth, trade planner, final judge",
        "can_create_trade_plan": True,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": True,
        "has_entry_zone": True,
        "has_stop_logic": True,
        "has_target_logic": True,
        "has_tests": True,
        "priority": "P2",
    },
    "breakout_retest": {
        "detected_by": "chart_patterns.detect_breakout_retest + breakout analyst",
        "used_by_agent": "breakout analyst, trade planner, final judge, orderbook entry planner",
        "can_create_trade_plan": True,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": True,
        "has_entry_zone": True,
        "has_stop_logic": True,
        "has_target_logic": True,
        "has_tests": True,
        "priority": "P1",
    },
    "failed_breakout": {
        "detected_by": "chart_patterns.detect_failed_breakout",
        "used_by_agent": "chart-pattern context, bear/synth/judge as warning",
        "can_create_trade_plan": False,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": True,
        "has_entry_zone": False,
        "has_stop_logic": False,
        "has_target_logic": True,
        "has_tests": True,
        "priority": "P2",
    },
    "liquidity_sweep": {
        "detected_by": "chart_patterns.detect_support_sweep_reclaim",
        "used_by_agent": "chart-pattern context, reclaim planner path",
        "can_create_trade_plan": True,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": True,
        "has_entry_zone": True,
        "has_stop_logic": True,
        "has_target_logic": True,
        "has_tests": True,
        "priority": "P2",
    },
    "volatility_squeeze": {
        "detected_by": "chart_patterns.detect_compression_squeeze",
        "used_by_agent": "chart-pattern context + breakout analyst",
        "can_create_trade_plan": False,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": True,
        "has_entry_zone": False,
        "has_stop_logic": False,
        "has_target_logic": False,
        "has_tests": True,
        "priority": "P1",
    },
    "support_bounce": {
        "detected_by": "market structure support distance + meanrev analyst",
        "used_by_agent": "meanrev analyst, planner text",
        "can_create_trade_plan": True,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": False,
        "has_entry_zone": True,
        "has_stop_logic": True,
        "has_target_logic": True,
        "has_tests": False,
        "priority": "P2",
    },
    "ema_pullback": {
        "detected_by": "EMA20/50 trend context; no named EMA 8/21/50/200 library spec",
        "used_by_agent": "trend analyst and planner via indicators",
        "can_create_trade_plan": True,
        "can_create_future_watch": True,
        "has_invalidation_level": True,
        "has_trigger_level": False,
        "has_entry_zone": True,
        "has_stop_logic": True,
        "has_target_logic": True,
        "has_tests": False,
        "priority": "P2",
    },
    "orderbook_imbalance": {
        "detected_by": "orderbook_analyzer/orderbook_entry_planner",
        "used_by_agent": "read-only execution planner and deterministic entry preview",
        "can_create_trade_plan": False,
        "can_create_future_watch": True,
        "has_invalidation_level": False,
        "has_trigger_level": False,
        "has_entry_zone": True,
        "has_stop_logic": False,
        "has_target_logic": False,
        "has_tests": True,
        "priority": "P1",
    },
    "spread_depth_opportunity": {
        "detected_by": "market/orderbook context + orderbook_entry_planner",
        "used_by_agent": "execution planner and deterministic entry preview",
        "can_create_trade_plan": False,
        "can_create_future_watch": True,
        "has_invalidation_level": False,
        "has_trigger_level": False,
        "has_entry_zone": True,
        "has_stop_logic": False,
        "has_target_logic": False,
        "has_tests": True,
        "priority": "P1",
    },
}


ALIASES = {
    "breakout": "breakout_retest",
    "reclaim_retest": "reclaim_reversal",
    "pullback": "ema_pullback",
    "range_break": "breakout_retest",
    "resistance_rejection": "failed_breakout",
    "volume_expansion": "breakout_retest",
    "momentum_continuation": "trend_continuation",
    "higher_timeframe_confluence": "trend_continuation",
}


def build_setup_pattern_matrix() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for pattern in REQUIRED_SETUP_PATTERNS:
        key = pattern if pattern in PATTERN_SUPPORT else ALIASES.get(pattern)
        support = PATTERN_SUPPORT.get(key or "", {})
        supported = bool(support)
        missing = []
        if not supported:
            missing = ["detector", "planner mapping", "tests"]
        else:
            for field, label in (
                ("has_trigger_level", "trigger_level"),
                ("has_invalidation_level", "invalidation_level"),
                ("has_entry_zone", "entry_zone"),
                ("has_stop_logic", "stop_logic"),
                ("has_target_logic", "target_logic"),
                ("has_tests", "tests"),
            ):
                if not bool(support.get(field)):
                    missing.append(label)
        action = "Keep as prompt/planner supported setup and add richer metrics only if evidence improves."
        if not supported:
            action = "Add report-only detector first, then prompt/schema fields, then deterministic gates if proven."
        elif missing:
            action = "Fill missing schema/test coverage before relying on it for live-entry decisions."
        spec = SetupPatternSpec(
            setup_pattern=pattern,
            currently_supported=supported,
            detected_by=str(support.get("detected_by") or ""),
            used_by_agent=str(support.get("used_by_agent") or ""),
            can_create_trade_plan=bool(support.get("can_create_trade_plan")),
            can_create_future_watch=bool(support.get("can_create_future_watch")),
            has_invalidation_level=bool(support.get("has_invalidation_level")),
            has_trigger_level=bool(support.get("has_trigger_level")),
            has_entry_zone=bool(support.get("has_entry_zone")),
            has_stop_logic=bool(support.get("has_stop_logic")),
            has_target_logic=bool(support.get("has_target_logic")),
            has_tests=bool(support.get("has_tests")),
            missing=missing,
            recommended_action=action,
            priority=str(support.get("priority") or "P1"),
        )
        rows.append(spec.to_dict())
    return rows


def build_setup_pattern_status() -> Dict[str, Any]:
    matrix = build_setup_pattern_matrix()
    return {
        "phase": "setup_pattern_library_poc_v1",
        "read_only": True,
        "live_order_authority": False,
        "copy_code": False,
        "license_notes": "Own implementation inspired by common strategy-taxonomy patterns; no open-source code copied.",
        "summary": {
            "patterns_total": len(matrix),
            "currently_supported": sum(1 for row in matrix if row["currently_supported"]),
            "can_create_future_watch": sum(1 for row in matrix if row["can_create_future_watch"]),
            "missing_tests": sum(1 for row in matrix if not row["has_tests"]),
        },
        "matrix": matrix,
    }


__all__ = ["build_setup_pattern_matrix", "build_setup_pattern_status"]
