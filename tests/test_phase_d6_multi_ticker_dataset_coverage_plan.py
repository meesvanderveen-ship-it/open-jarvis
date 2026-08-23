from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_multi_ticker_backlearning_readiness import (
    DATA_FETCH_ACK,
    build_multi_ticker_dataset_coverage_plan,
)


def _candles(path: Path, product: str, timeframe: str = "1D", count: int = 40) -> Path:
    rows = [
        {
            "product_id": product,
            "timeframe": timeframe,
            "start": i * 86400,
            "open": "100",
            "high": "101",
            "low": "99",
            "close": str(100 + i),
            "volume": "1",
        }
        for i in range(count)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_dataset_coverage_plan_marks_missing_timeframes_and_future_fetch_commands(tmp_path: Path):
    btc = _candles(tmp_path / "research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json", "BTC-USDC")
    report = build_multi_ticker_dataset_coverage_plan(
        config_text='"ALLOWED_TICKERS", ("BTC-USDC,ETH-USDC") ,',
        candle_paths=[btc],
        order_events_path=tmp_path / "missing.jsonl",
        as_of="1971-01-01T00:00:00Z",
    )

    rows = {(row["ticker"], row["timeframe"]): row for row in report["rows"]}
    assert rows[("BTC-USDC", "1D")]["cached_data_present"] is True
    assert rows[("BTC-USDC", "1H")]["missing_data_blocker"] is True
    assert rows[("ETH-USDC", "4H")]["future_fetch_command"]["required_ack"] == DATA_FETCH_ACK
    assert report["missing_row_count"] == 5
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["parameter_review_approved"] is False
    assert report["learning_to_execution_enabled"] is False
