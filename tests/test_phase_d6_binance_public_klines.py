from datetime import datetime, timezone
import json

from bot.phase_d6_binance_public_klines import (
    BinanceRateLimitPolicy,
    build_binance_klines_plan,
    build_btc_4h_gap_reference_report,
    build_multi_source_candle_policy_v1,
    classify_binance_fetch_error,
    execute_binance_klines_fetch,
    normalize_binance_klines,
)


def _row(open_time_ms: int) -> list:
    return [
        open_time_ms,
        "100",
        "110",
        "90",
        "105",
        "12.5",
        open_time_ms + 14_399_999,
        "1300",
        42,
        "6",
        "630",
        "0",
    ]


def test_multi_source_policy_keeps_external_data_out_of_coinbase_cache() -> None:
    policy = build_multi_source_candle_policy_v1()

    assert policy["venue_roles"]["coinbase"] == "primary_execution_venue"
    assert policy["venue_roles"]["binance"] == "secondary_reference_venue"
    assert policy["storage_policy"]["external_as_coinbase_raw_cache_allowed"] is False
    assert policy["normal_backtest_gate"]["secondary_reference_can_override_primary_gap"] is False
    assert policy["external_candle_written_as_coinbase_candle"] is False


def test_binance_plan_maps_btc_usdc_4h_to_public_klines(tmp_path) -> None:
    plan = build_binance_klines_plan(
        mapped_coinbase_product="BTC-USDC",
        symbol="BTCUSDC",
        timeframe="4H",
        start=1761408000,
        end_exclusive=1761422400,
        candidate_root=tmp_path,
        run_id="x",
        policy=BinanceRateLimitPolicy(max_requests_per_run=1),
    )

    assert plan["symbol"] == "BTCUSDC"
    assert plan["binance_interval"] == "4h"
    assert "startTime=1761408000000" in plan["request_url"]
    assert "source=binance" in plan["candidate_output_path"]
    assert plan["binance_account_or_order_call_performed"] is False


def test_normalize_binance_klines_preserves_provenance(tmp_path) -> None:
    plan = build_binance_klines_plan(
        mapped_coinbase_product="BTC-USDC",
        timeframe="4H",
        start=1761408000,
        end_exclusive=1761422400,
        candidate_root=tmp_path,
        run_id="x",
    )

    candles = normalize_binance_klines(
        [_row(1761408000000)],
        plan=plan,
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert candles[0]["source"] == "binance"
    assert candles[0]["venue"] == "binance_spot"
    assert candles[0]["mapped_coinbase_product"] == "BTC-USDC"
    assert candles[0]["open_time"] == 1761408000
    assert candles[0]["quote_asset"] == "USDC"
    assert candles[0]["transformation_applied"]


def test_execute_binance_fetch_writes_candidate_on_exact_reference(tmp_path) -> None:
    plan = build_binance_klines_plan(
        mapped_coinbase_product="BTC-USDC",
        timeframe="4H",
        start=1761408000,
        end_exclusive=1761422400,
        candidate_root=tmp_path,
        run_id="x",
        policy=BinanceRateLimitPolicy(min_delay_seconds=0, max_retries_per_request=0, retry_budget_total=0),
    )

    result = execute_binance_klines_fetch(
        plan=plan,
        http_get=lambda _: {"status_code": 200, "body": json.dumps([_row(1761408000000)])},
        sleep_fn=lambda _: None,
        now_fn=lambda: 0.0,
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "binance_public_klines_fetch_ready"
    assert result["candidate_count"] == 1
    assert result["exact_expected_start_found"] is True
    assert result["partial_candidate_quarantined"] is False


def test_zero_binance_fetch_quarantines_and_reference_missing(tmp_path) -> None:
    plan = build_binance_klines_plan(
        mapped_coinbase_product="BTC-USDC",
        timeframe="4H",
        start=1761408000,
        end_exclusive=1761422400,
        candidate_root=tmp_path,
        run_id="x",
        policy=BinanceRateLimitPolicy(min_delay_seconds=0, max_retries_per_request=0, retry_budget_total=0),
    )

    result = execute_binance_klines_fetch(
        plan=plan,
        http_get=lambda _: {"status_code": 200, "body": "[]"},
        sleep_fn=lambda _: None,
        now_fn=lambda: 0.0,
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    report = build_btc_4h_gap_reference_report(fetch_result=result)

    assert result["status"] == "binance_public_klines_fetch_blocked"
    assert result["partial_candidate_quarantined"] is True
    assert report["binance_reference"]["classification"] == "external_reference_missing"


def test_binance_error_classification() -> None:
    assert classify_binance_fetch_error(RuntimeError("429 too many requests")) == "rate_limit_error"
    assert classify_binance_fetch_error(RuntimeError("DNS timeout")) == "network_error"
    assert classify_binance_fetch_error("", zero_candle=True) == "zero_candle_response"
