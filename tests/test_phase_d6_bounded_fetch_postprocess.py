import json

from bot.phase_d6_bounded_fetch_postprocess import (
    DATA_FETCH_ACK,
    build_bounded_fetch_result_report,
    build_post_fetch_dataset_quality_summary,
)


def test_bounded_fetch_result_preserves_research_boundaries(tmp_path) -> None:
    candle_path = tmp_path / "research_data/coinbase/candles/product=BTC-USDC/timeframe=1H/study_window=3y.json"
    candle_path.parent.mkdir(parents=True)
    candle_path.write_text(json.dumps([{"start": 1}]), encoding="utf-8")

    report = build_bounded_fetch_result_report(
        requested_rows=[
            {"ticker": "BTC-USDC", "timeframe": "1H", "requested_chunks": 2, "chunks_fetched": 2, "output_path": candle_path}
        ],
        max_chunks=2,
    )

    assert report["required_ack"] == DATA_FETCH_ACK
    assert report["coinbase_public_market_data_call_count"] == 2
    assert report["state_write_performed"] is False
    assert report["live_order_action_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["learning_to_execution_enabled"] is False
    assert report["actually_fetched_rows"][0]["candle_count"] == 1


def test_dataset_quality_summary_ignores_state_paths(tmp_path) -> None:
    candle_path = tmp_path / "candles.json"
    candle_path.write_text(
        json.dumps(
            [
                {
                    "product_id": "BTC-USDC",
                    "timeframe": "1H",
                    "start": 1,
                    "open": "1",
                    "high": "1",
                    "low": "1",
                    "close": "1",
                    "volume": "1",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = build_post_fetch_dataset_quality_summary(candle_paths=[candle_path, "state/not_allowed.json"], as_of="")

    assert report["summary"]["quality_report_count"] == 1
    assert report["state_write_performed"] is False
    assert report["parameter_review_approved"] is False
