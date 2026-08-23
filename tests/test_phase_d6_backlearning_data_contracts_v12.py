from bot.phase_d6_backlearning_data_contracts_v12 import build_backlearning_data_contracts_v12


def test_backlearning_contract_blocks_normal_when_primary_not_clean() -> None:
    report = build_backlearning_data_contracts_v12(
        quality_summary={"rows": [{"product_id": "BTC-USDC", "timeframe": "1H", "quality_class": "usable_with_warnings"}]},
        known_gap_decision={"classification": "confirmed_coinbase_data_hole_candidate", "exploratory_only_allowed": True},
    )

    contract = report["dataset_contracts"]["BTC-USDC:1H"]
    assert contract["primary_clean"] is False
    assert contract["normal_backtest_blocked"] is True
    assert contract["exploratory_only_allowed"] is True
    assert contract["learning_to_execution_enabled"] is False
