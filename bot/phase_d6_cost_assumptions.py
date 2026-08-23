from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import (
    ZERO,
    d6_metric_safety_flags,
    decimal_str,
    now_iso,
    pct_decimal,
    to_decimal,
)


D6_COST_ASSUMPTIONS_PHASE = "D6_fee_slippage_assumption_pack_v1"


SCENARIOS: "OrderedDict[str, Dict[str, str]]" = OrderedDict(
    [
        (
            "zero_cost_reference",
            {
                "description": "Unrealistic zero-cost reference for isolating gross behavior only.",
                "maker_fee_pct": "0",
                "taker_fee_pct": "0",
                "entry_fee_pct": "0",
                "exit_fee_pct": "0",
                "entry_slippage_pct": "0",
                "exit_slippage_pct": "0",
                "spread_pct": "0",
            },
        ),
        (
            "low_cost_maker_like",
            {
                "description": "Low-cost maker-like research placeholder, not a Coinbase fee schedule.",
                "maker_fee_pct": "0.001",
                "taker_fee_pct": "0.004",
                "entry_fee_pct": "0.001",
                "exit_fee_pct": "0.001",
                "entry_slippage_pct": "0.0002",
                "exit_slippage_pct": "0.0002",
                "spread_pct": "0.0002",
            },
        ),
        (
            "standard_fee_only",
            {
                "description": "Fee-only scaffold matching the existing D.6 default per-side fee assumption.",
                "maker_fee_pct": "0.004",
                "taker_fee_pct": "0.004",
                "entry_fee_pct": "0.004",
                "exit_fee_pct": "0.004",
                "entry_slippage_pct": "0",
                "exit_slippage_pct": "0",
                "spread_pct": "0",
            },
        ),
        (
            "conservative_slippage",
            {
                "description": "Conservative candle-only cost placeholder with fee, slippage and spread haircuts.",
                "maker_fee_pct": "0.004",
                "taker_fee_pct": "0.006",
                "entry_fee_pct": "0.004",
                "exit_fee_pct": "0.004",
                "entry_slippage_pct": "0.001",
                "exit_slippage_pct": "0.001",
                "spread_pct": "0.0005",
            },
        ),
        (
            "stress_cost",
            {
                "description": "Stress-cost placeholder for sensitivity checks, not a live execution forecast.",
                "maker_fee_pct": "0.006",
                "taker_fee_pct": "0.008",
                "entry_fee_pct": "0.006",
                "exit_fee_pct": "0.006",
                "entry_slippage_pct": "0.003",
                "exit_slippage_pct": "0.003",
                "spread_pct": "0.002",
            },
        ),
    ]
)


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
    }


def list_cost_scenarios() -> List[str]:
    return list(SCENARIOS.keys())


def _scenario_payload(name: str) -> Dict[str, str]:
    scenario = str(name or "").strip().lower()
    if scenario not in SCENARIOS:
        raise ValueError(f"unsupported_d6_cost_scenario:{name}")
    return dict(SCENARIOS[scenario])


def _pct_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "maker_fee_pct",
        "taker_fee_pct",
        "entry_fee_pct",
        "exit_fee_pct",
        "entry_slippage_pct",
        "exit_slippage_pct",
        "spread_pct",
    ]
    out: Dict[str, Any] = {}
    for key in keys:
        value = to_decimal(raw.get(key))
        if value < ZERO:
            raise ValueError(f"{key}_must_not_be_negative")
        out[key] = value
    return out


def _warnings(*, scenario_name: str, values: Dict[str, Any], round_trip_cost_pct: Any) -> List[str]:
    warnings = [
        "research_cost_assumption_only",
        "not_strategy_recommendation",
        "not_parameter_ranking",
        "not_parameter_search",
        "not_optimization",
        "not_live_fee_schedule",
        "candle_only_cost_model",
    ]
    if scenario_name == "zero_cost_reference":
        warnings.append("unrealistic_zero_cost_assumption")
    if values["entry_slippage_pct"] == ZERO and values["exit_slippage_pct"] == ZERO:
        warnings.append("slippage_not_modeled")
    if values["spread_pct"] == ZERO:
        warnings.append("spread_not_modeled")
    if to_decimal(round_trip_cost_pct) >= to_decimal("0.02"):
        warnings.append("stress_cost_assumption")
    return sorted(set(warnings))


def build_phase_d6_cost_assumption_report(*, scenario_name: str = "standard_fee_only") -> Dict[str, Any]:
    scenario = str(scenario_name or "").strip().lower()
    raw = _scenario_payload(scenario)
    values = _pct_fields(raw)
    half_spread = values["spread_pct"] / to_decimal("2")
    entry_cost = values["entry_fee_pct"] + values["entry_slippage_pct"] + half_spread
    exit_cost = values["exit_fee_pct"] + values["exit_slippage_pct"] + half_spread
    round_trip_cost = entry_cost + exit_cost

    return {
        "generated_at": now_iso(),
        "phase": D6_COST_ASSUMPTIONS_PHASE,
        "status": "d6_cost_assumption_report_ready",
        "scenario_name": scenario,
        "description": raw["description"],
        "fee_assumptions": {
            "maker_fee_pct": decimal_str(values["maker_fee_pct"]),
            "maker_fee_pct_points": decimal_str(pct_decimal(values["maker_fee_pct"])),
            "taker_fee_pct": decimal_str(values["taker_fee_pct"]),
            "taker_fee_pct_points": decimal_str(pct_decimal(values["taker_fee_pct"])),
            "entry_fee_pct": decimal_str(values["entry_fee_pct"]),
            "exit_fee_pct": decimal_str(values["exit_fee_pct"]),
            "fee_model": "research_placeholder_not_live_fee_schedule",
        },
        "slippage_assumptions": {
            "entry_slippage_pct": decimal_str(values["entry_slippage_pct"]),
            "exit_slippage_pct": decimal_str(values["exit_slippage_pct"]),
            "slippage_model": "fixed_pct_research_placeholder",
        },
        "spread_assumptions": {
            "spread_pct": decimal_str(values["spread_pct"]),
            "entry_spread_cost_pct": decimal_str(half_spread),
            "exit_spread_cost_pct": decimal_str(half_spread),
            "spread_model": "fixed_full_spread_split_across_entry_exit",
        },
        "derived_costs": {
            "entry_cost_pct": decimal_str(entry_cost),
            "entry_cost_pct_points": decimal_str(pct_decimal(entry_cost)),
            "exit_cost_pct": decimal_str(exit_cost),
            "exit_cost_pct_points": decimal_str(pct_decimal(exit_cost)),
            "round_trip_cost_pct": decimal_str(round_trip_cost),
            "round_trip_cost_pct_points": decimal_str(pct_decimal(round_trip_cost)),
            "conservative_cost_pct": decimal_str(round_trip_cost),
            "conservative_cost_pct_points": decimal_str(pct_decimal(round_trip_cost)),
        },
        "limitations": [
            "research_assumption_only",
            "not_a_live_fee_schedule",
            "not_a_live_execution_model",
            "does_not_model_orderbook_depth",
            "does_not_model_partial_fills",
            "does_not_model_post_only_queue_position",
        ],
        "warnings": _warnings(
            scenario_name=scenario,
            values=values,
            round_trip_cost_pct=round_trip_cost,
        ),
        **_safety_flags(),
    }


def build_phase_d6_cost_assumption_catalog(
    *,
    scenarios: Iterable[str] | None = None,
) -> Dict[str, Any]:
    selected = list(scenarios) if scenarios is not None else list_cost_scenarios()
    reports = [build_phase_d6_cost_assumption_report(scenario_name=name) for name in selected]
    return {
        "generated_at": now_iso(),
        "phase": D6_COST_ASSUMPTIONS_PHASE,
        "status": "d6_cost_assumption_catalog_ready",
        "scenario_count": len(reports),
        "scenario_names": [report["scenario_name"] for report in reports],
        "scenarios": reports,
        "warnings": [
            "research_cost_assumption_catalog_only",
            "not_parameter_ranking",
            "not_optimization",
            "not_live_recommendation",
        ],
        **_safety_flags(),
    }


def write_cost_assumption_report(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_COST_ASSUMPTIONS_PHASE",
    "SCENARIOS",
    "list_cost_scenarios",
    "build_phase_d6_cost_assumption_report",
    "build_phase_d6_cost_assumption_catalog",
    "write_cost_assumption_report",
]
