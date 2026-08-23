from bot.phase_d6_backlearning_multisource_v5 import build_backlearning_multisource_scaffold_v5
from bot.phase_d6_binance_public_klines import build_multi_source_candle_policy_v1


def test_backlearning_multisource_keeps_normal_gate_on_coinbase_quality() -> None:
    scaffold = build_backlearning_multisource_scaffold_v5(
        quality_summary={"good_count": 1, "warning_count": 53, "poor_count": 2, "invalid_count": 0},
        multi_source_policy=build_multi_source_candle_policy_v1(),
        btc_4h_reference={
            "binance_reference": {
                "classification": "external_reference_available",
            }
        },
    )

    assert scaffold["quality_gates"]["normal_backtest_gate"]["allowed"] is False
    assert scaffold["quality_gates"]["normal_backtest_gate"]["secondary_source_can_override"] is False
    assert scaffold["quality_gates"]["exploratory_cross_venue_gate"]["allowed"] is True
    assert scaffold["parameter_evidence_created"] is False
    assert scaffold["external_candle_written_as_coinbase_candle"] is False


def test_backlearning_multisource_contract_splits_primary_and_secondary() -> None:
    scaffold = build_backlearning_multisource_scaffold_v5(
        quality_summary={"summary": {"good_count": 54, "warning_count": 0, "poor_count": 0, "invalid_count": 0}},
        multi_source_policy=build_multi_source_candle_policy_v1(),
        btc_4h_reference={"binance_reference": {"classification": "external_reference_missing"}},
    )

    assert scaffold["dataset_contract"]["primary_sources"][0]["source"] == "coinbase"
    assert scaffold["dataset_contract"]["secondary_sources"][0]["source"] == "binance"
    assert scaffold["dataset_contract"]["secondary_sources"][0]["may_fill_primary_cache"] is False
    assert scaffold["quality_gates"]["normal_backtest_gate"]["allowed"] is True
    assert scaffold["quality_gates"]["exploratory_cross_venue_gate"]["allowed"] is False
