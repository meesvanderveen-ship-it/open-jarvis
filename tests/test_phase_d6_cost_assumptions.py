from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_cost_assumptions import (
    build_phase_d6_cost_assumption_catalog,
    build_phase_d6_cost_assumption_report,
    list_cost_scenarios,
    write_cost_assumption_report,
)


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_live_action"] is True
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["no_bulk_fetch"] is True
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["signal_generation_performed"] is False
    assert report["live_recommendation"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False


def test_scenario_catalog_is_stable_and_report_only():
    names = list_cost_scenarios()
    assert names == [
        "zero_cost_reference",
        "low_cost_maker_like",
        "standard_fee_only",
        "conservative_slippage",
        "stress_cost",
    ]

    catalog = build_phase_d6_cost_assumption_catalog()
    assert catalog["status"] == "d6_cost_assumption_catalog_ready"
    assert catalog["scenario_count"] == 5
    assert catalog["scenario_names"] == names
    assert "not_parameter_ranking" in catalog["warnings"]
    _assert_safe(catalog)
    for scenario in catalog["scenarios"]:
        _assert_safe(scenario)


def test_standard_fee_only_derives_round_trip_costs():
    report = build_phase_d6_cost_assumption_report(scenario_name="standard_fee_only")

    assert report["scenario_name"] == "standard_fee_only"
    assert report["fee_assumptions"]["entry_fee_pct"] == "0.004"
    assert report["fee_assumptions"]["exit_fee_pct"] == "0.004"
    assert report["derived_costs"]["entry_cost_pct"] == "0.004"
    assert report["derived_costs"]["exit_cost_pct"] == "0.004"
    assert report["derived_costs"]["round_trip_cost_pct"] == "0.008"
    assert report["derived_costs"]["round_trip_cost_pct_points"] == "0.8"
    assert "slippage_not_modeled" in report["warnings"]
    assert "spread_not_modeled" in report["warnings"]
    _assert_safe(report)


def test_conservative_and_stress_scenarios_include_slippage_and_spread():
    conservative = build_phase_d6_cost_assumption_report(scenario_name="conservative_slippage")
    stress = build_phase_d6_cost_assumption_report(scenario_name="stress_cost")

    assert conservative["derived_costs"]["entry_cost_pct"] == "0.00525"
    assert conservative["derived_costs"]["exit_cost_pct"] == "0.00525"
    assert conservative["derived_costs"]["round_trip_cost_pct"] == "0.0105"
    assert "slippage_not_modeled" not in conservative["warnings"]
    assert "spread_not_modeled" not in conservative["warnings"]

    assert stress["derived_costs"]["round_trip_cost_pct"] == "0.02"
    assert "stress_cost_assumption" in stress["warnings"]
    _assert_safe(conservative)
    _assert_safe(stress)


def test_zero_cost_warns_and_invalid_scenario_fails_closed():
    zero = build_phase_d6_cost_assumption_report(scenario_name="zero_cost_reference")

    assert zero["derived_costs"]["round_trip_cost_pct"] == "0"
    assert "unrealistic_zero_cost_assumption" in zero["warnings"]
    assert "not_live_fee_schedule" in zero["warnings"]
    _assert_safe(zero)

    with pytest.raises(ValueError, match="unsupported_d6_cost_scenario"):
        build_phase_d6_cost_assumption_report(scenario_name="best_cost")


def test_write_report_refuses_state_and_env_paths(tmp_path: Path):
    report = build_phase_d6_cost_assumption_report(scenario_name="standard_fee_only")
    output = tmp_path / "reports" / "d6" / "costs.json"

    assert write_cost_assumption_report(report, output) == output
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["scenario_name"] == "standard_fee_only"
    assert written["no_coinbase_call"] is True

    with pytest.raises(ValueError, match="state"):
        write_cost_assumption_report(report, tmp_path / "state" / "costs.json")
    with pytest.raises(ValueError, match="env"):
        write_cost_assumption_report(report, tmp_path / ".env")


def test_cli_stdout_and_explicit_output(tmp_path: Path):
    output = tmp_path / "reports" / "d6" / "costs.json"

    stdout_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_cost_assumptions.py",
            "--scenario",
            "conservative_slippage",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    stdout_report = json.loads(stdout_result.stdout)
    assert stdout_report["scenario_name"] == "conservative_slippage"
    assert stdout_report["derived_costs"]["round_trip_cost_pct"] == "0.0105"
    _assert_safe(stdout_report)

    output_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_cost_assumptions.py",
            "--scenario",
            "all",
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    assert output_result.stdout == ""
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["scenario_count"] == 5
    assert written["parameter_search_performed"] is False
