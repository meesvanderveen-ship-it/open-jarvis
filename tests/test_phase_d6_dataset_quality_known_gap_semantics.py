from bot.phase_d6_dataset_quality_known_gap_semantics import build_dataset_quality_known_gap_semantics


def test_known_gap_semantics_are_metadata_only_and_block_normal() -> None:
    report = build_dataset_quality_known_gap_semantics(
        policy_review={
            "chunk_id": "BTCUSDC-1H-gap01:chunk52",
            "classification": "confirmed_primary_source_data_hole",
            "missing_coinbase_starts": [1, 2, 3],
            "policy_decision": {
                "allows_chunk53_continuation": True,
                "allows_exploratory_only": True,
                "requires_human_ack": True,
                "requires_future_revisit": True,
            },
        }
    )

    assert report["raw_cache_mutation_allowed"] is False
    assert report["synthetic_ohlcv_allowed"] is False
    assert report["secondary_source_repair_allowed"] is False
    assert report["normal_backtest_blocked"] is True
    assert report["exploratory_only_allowed_with_warnings"] is True
    assert report["chunk_continuation_allowed_if_downstream_ranges_independently_validate"] is True
