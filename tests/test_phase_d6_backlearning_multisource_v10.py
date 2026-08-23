import json
from pathlib import Path

from bot.phase_d6_backlearning_multisource_v10 import build_backlearning_multisource_scaffold_v10


def test_v10_backlearning_records_source_contracts_and_hard_gates(tmp_path: Path) -> None:
    candles = tmp_path / "btc.json"
    candles.write_text(json.dumps([{"product_id": "BTC-USDC", "timeframe": "1H", "start": 1}]), encoding="utf-8")

    report = build_backlearning_multisource_scaffold_v10(
        quality_summary={"global_counters": {"warning_count": 1, "poor_count": 1, "invalid_count": 0}},
        controller_result={"completed_chunk_ids": ["BTCUSDC-1H-gap01:chunk13"]},
        binance_reference={"available_reference_count": 1},
        source_paths=[candles],
    )

    assert report["report_name"] == "backlearning_multisource_scaffold_v10"
    assert report["source_contracts"]["primary_role"] == "execution_market_research_dataset"
    assert report["source_contracts"]["secondary_can_mutate_primary_cache"] is False
    assert report["quality_gate_matrix"]["normal_backtests"].startswith("blocked_until_primary_coinbase_quality")
    assert report["trial_accounting_by_dataset_hash_and_source_mix"]["creates_parameter_evidence"] is False
    assert report["normal_vs_exploratory_gate"]["exploratory_only_creates_parameter_evidence"] is False
    assert report["learning_to_execution_enabled"] is False
