from __future__ import annotations

from bot.phase_d6_metrics import (
    build_drawdown_metrics,
    build_exposure_metrics,
    build_fee_metrics,
    build_metric_warnings,
    build_phase_d6_metrics_report,
    build_return_metrics,
    build_trade_metrics,
    d6_metric_safety_flags,
    max_drawdown,
    net_return,
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
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False


def test_return_and_drawdown_metrics_are_decimal_stable():
    assert str(net_return("1000", "1250")) == "0.25"
    assert str(max_drawdown(["100", "120", "90", "150", "120"])) == "0.25"

    returns = build_return_metrics(initial_quote="1000", final_quote="1250")
    drawdown = build_drawdown_metrics(["100", "120", "90", "150", "120"])

    assert returns["net_return"] == "0.25"
    assert returns["net_return_pct"] == "25"
    assert drawdown["max_drawdown"] == "0.25"
    assert drawdown["max_drawdown_pct"] == "25"


def test_exposure_trade_and_fee_metrics():
    exposure = build_exposure_metrics(exposed_bars=25, total_bars=100)
    trades = build_trade_metrics(trades_count=5, round_trips=2, wins=3, losses=1)
    fees = build_fee_metrics(fees_quote="4", initial_quote="1000")

    assert exposure["exposure"] == "0.25"
    assert exposure["exposure_pct"] == "25"
    assert trades["trades_count"] == 5
    assert trades["round_trips"] == 2
    assert trades["winrate"] == "0.75"
    assert trades["winrate_pct"] == "75"
    assert fees["fees_paid_quote_estimate"] == "4"
    assert fees["fees_to_initial_quote"] == "0.004"
    assert fees["fees_to_initial_quote_pct"] == "0.4"


def test_warning_helpers_are_explicit_and_non_executing():
    warnings = build_metric_warnings(
        trades_count=1,
        max_drawdown_value="0.35",
        exposure_value="0",
        data_quality_ready=False,
        split_usable=False,
    )

    assert warnings == [
        "too_few_trades",
        "high_drawdown",
        "zero_exposure",
        "data_quality_blocked",
        "split_unusable",
    ]


def test_safety_flags_are_hard_false_for_execution_paths():
    flags = d6_metric_safety_flags()

    assert flags["research_only"] is True
    assert flags["no_live_action"] is True
    assert flags["no_coinbase_call"] is True
    assert flags["state_write_performed"] is False
    assert flags["no_optimization"] is True
    assert flags["parameter_search_performed"] is False
    assert flags["signal_generation_performed"] is False
    assert flags["learning_to_execution_allowed"] is False
    assert flags["parameter_change_allowed"] is False


def test_metrics_report_shape_and_warnings():
    report = build_phase_d6_metrics_report(
        initial_quote="1000",
        final_quote="900",
        equity_curve=["1000", "1100", "700", "900"],
        exposed_bars=0,
        total_bars=4,
        trades_count=1,
        round_trips=0,
        fees_quote="2",
        data_quality_ready=False,
        split_usable=False,
    )

    assert report["status"] == "d6_metrics_report_ready"
    assert report["return_metrics"]["net_return"] == "-0.1"
    assert report["drawdown_metrics"]["max_drawdown"] == "0.3636363636363636363636363636"
    assert report["exposure_metrics"]["exposure"] == "0"
    assert report["trade_metrics"]["trades_count"] == 1
    assert report["fee_metrics"]["fees_to_initial_quote_pct"] == "0.2"
    assert "high_drawdown" in report["warnings"]
    assert "data_quality_blocked" in report["warnings"]
    _assert_safe(report)
