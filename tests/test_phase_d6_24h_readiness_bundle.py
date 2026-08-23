from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_24h_readiness_bundle import build_phase_d6_24h_readiness_bundle


def _candle(product: str, start: int, close: str, timeframe: str = "1D"):
    return {
        "product_id": product,
        "timeframe": timeframe,
        "start": start,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": "1",
    }


def _write_candles(path: Path, product: str, count: int = 350) -> Path:
    day = 86400
    rows = [_candle(product, i * day, str(100 + i)) for i in range(count)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False
    assert report["human_review_required"] is True
    assert report["parameter_review_approved"] is False


def test_24h_bundle_maps_multiticker_gaps_and_runs_cached_baseline(tmp_path: Path):
    btc = _write_candles(
        tmp_path / "research_data" / "coinbase" / "candles" / "product=BTC-USDC" / "timeframe=1D" / "study_window=3y.json",
        "BTC-USDC",
    )
    coverage = tmp_path / "reports" / "d6" / "coverage.json"
    coverage.parent.mkdir(parents=True)
    coverage.write_text(
        json.dumps({"entries": [{"ticker": "BTC-USDC", "timeframe": "1D", "study_window": "3y", "candle_count": 350, "gap_count": 0}]}),
        encoding="utf-8",
    )
    events = tmp_path / "logs" / "order_events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        json.dumps(
            {
                "event_type": "d3_live_exit_reconciled",
                "order": {"ticker": "BTC-USDC", "product_id": "BTC-USDC", "mode": "live", "live_order_submitted": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_phase_d6_24h_readiness_bundle(
        config_text='"ALLOWED_TICKERS", ("BTC-USDC,ETH-USDC") ,',
        coverage_manifest_paths=[coverage],
        candle_paths=[btc],
        order_events_path=events,
        state_hashes_before={"state/open_orders.json": "a"},
        state_hashes_after={"state/open_orders.json": "a"},
        as_of="1971-01-01T00:00:00Z",
    )

    rows = {row["ticker"]: row for row in report["multiticker_gap_report"]["per_ticker_rows"]}
    assert rows["BTC-USDC"]["cached_backtest_input_present"] is True
    assert rows["ETH-USDC"]["cached_any_timeframe"] is False
    assert "ETH-USDC" in report["multiticker_gap_report"]["summary"]["tickers_missing_required_cached_coverage"]
    assert report["cached_only_backtest_status"]["status"] == "cached_only_baseline_executed_report_only"
    assert report["future_24h_preflight_v2"]["safe_scope_for_next_prompt"]["product"] == "BTC-USDC"
    assert report["readiness_conclusion"]["btc_usdc_only_24h_ready_for_ack_review"] is True
    assert report["readiness_conclusion"]["all_ticker_24h_live_test_ready"] is False
    _assert_safe(report)


def test_24h_bundle_does_not_mark_empty_cache_as_backtest_ready(tmp_path: Path):
    report = build_phase_d6_24h_readiness_bundle(
        config_text='"ALLOWED_TICKERS", ("BTC-USDC,ETH-USDC") ,',
        coverage_manifest_paths=[],
        candle_paths=[],
        order_events_path=tmp_path / "missing.jsonl",
        as_of="2026-06-01T00:00:00Z",
    )

    assert report["cached_only_backtest_status"]["status"] == "not_run_no_cached_candles"
    assert report["backlearning_status_after_sprint"]["executed_on_all_configured_tickers"] is False
    assert report["scope"]["bulk_data_fetch"] is False
    _assert_safe(report)
