from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_multi_ticker_backlearning_readiness import build_multi_ticker_backtest_readiness_matrix


def _candles(path: Path, product: str) -> Path:
    rows = [
        {
            "product_id": product,
            "timeframe": "1D",
            "start": i * 86400,
            "open": "100",
            "high": "101",
            "low": "99",
            "close": str(100 + i),
            "volume": "1",
        }
        for i in range(40)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_backtest_readiness_matrix_separates_btc_partial_route_from_missing_tickers(tmp_path: Path):
    btc = _candles(tmp_path / "research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json", "BTC-USDC")
    events = tmp_path / "logs/order_events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        json.dumps({"event_type": "d3_live_exit_reconciled", "order": {"ticker": "BTC-USDC", "mode": "live", "live_order_submitted": True}})
        + "\n",
        encoding="utf-8",
    )
    report = build_multi_ticker_backtest_readiness_matrix(
        config_text='"ALLOWED_TICKERS", ("BTC-USDC,ETH-USDC") ,',
        candle_paths=[btc],
        order_events_path=events,
        as_of="1971-01-01T00:00:00Z",
    )

    rows = {row["ticker"]: row for row in report["rows"]}
    assert rows["BTC-USDC"]["baseline_backtest_possible"] is True
    assert "missing_required_timeframes" in rows["BTC-USDC"]["readiness_class"]
    assert rows["ETH-USDC"]["baseline_backtest_possible"] is False
    assert "missing_backtest_input" in rows["ETH-USDC"]["readiness_class"]
    assert "blocked_for_all_ticker_live_test" in rows["ETH-USDC"]["readiness_class"]
    assert report["summary"]["all_ticker_live_test_blocked"] is True
    assert report["contains_rankings"] is False
