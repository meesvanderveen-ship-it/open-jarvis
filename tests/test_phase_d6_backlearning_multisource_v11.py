import json
from pathlib import Path

from bot.phase_d6_backlearning_multisource_v11 import build_backlearning_multisource_scaffold_v11


def test_v11_backlearning_records_batch_review_and_reference_visibility(tmp_path: Path) -> None:
    candles = tmp_path / "btc.json"
    candles.write_text(json.dumps([{"product_id": "BTC-USDC", "timeframe": "1H", "start": 1}]), encoding="utf-8")

    report = build_backlearning_multisource_scaffold_v11(
        quality_summary={"global_counters": {"warning_count": 1, "poor_count": 1, "invalid_count": 0}},
        controller_result={"completed_chunk_ids": ["BTCUSDC-1H-gap01:chunk16"]},
        binance_reference={"available_reference_count": 1},
        source_paths=[candles],
    )

    assert report["report_name"] == "backlearning_multisource_scaffold_v11"
    assert report["chunk_batch_review_accounting"]["completed_chunks"] == ["BTCUSDC-1H-gap01:chunk16"]
    assert report["chunk_batch_review_accounting"]["auto_resume_allowed"] is False
    assert report["cross_source_reference_visibility"]["reference_only"] is True
    assert report["normal_vs_exploratory_gate"]["secondary_reference_can_release_normal_backtests"] is False
    assert report["hard_gate"]["learning_to_execution_enabled"] is False
