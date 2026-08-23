from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bot.phase_d6_coinbase_candle_ingest import (
    build_phase_d6_coinbase_candle_ingest_report,
    normalize_candles,
)


AS_OF = "2026-05-29"
NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


class FakeCoinbaseClient:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    def get_public_candles(self, *, product_id, granularity, start, end, limit):
        self.calls.append(
            {
                "method": "get_public_candles",
                "product_id": product_id,
                "granularity": granularity,
                "start": start,
                "end": end,
                "limit": limit,
            }
        )
        if self.fail:
            raise RuntimeError("fixture_api_error")
        return {
            "candles": [
                {"start": "1685491200", "open": "101", "high": "111", "low": "91", "close": "106", "volume": "2"},
                {"start": "1685318400", "open": "100", "high": "110", "low": "90", "close": "105", "volume": "1"},
                {"start": "1685318400", "open": "100.5", "high": "110.5", "low": "90.5", "close": "105.5", "volume": "1.5"},
            ]
        }


class ExplodingClient:
    def get_public_candles(self, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("dry_run_should_not_call_coinbase")


def _assert_report_only(report):
    assert report["research_only"] is True
    assert report["no_coinbase_write_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["no_backtest"] is True
    assert report["no_optimization"] is True
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False


def test_dry_run_makes_no_coinbase_calls_and_writes_no_outputs(tmp_path: Path):
    report = build_phase_d6_coinbase_candle_ingest_report(
        as_of=AS_OF,
        tickers=["BTC-USDC"],
        timeframes=["1D"],
        years=[3],
        client=ExplodingClient(),
        output_root=tmp_path / "research_data",
        now=NOW,
    )

    assert report["status"] == "d6_coinbase_candle_ingest_dry_run"
    assert report["dry_run"] is True
    assert report["fetch_executed"] is False
    assert report["coinbase_call_count"] == 0
    assert report["chunks_fetched"] == 0
    assert not (tmp_path / "research_data").exists()
    _assert_report_only(report)


def test_fetch_mode_calls_only_read_only_candle_method_and_writes_research_cache(tmp_path: Path):
    client = FakeCoinbaseClient()
    manifest = tmp_path / "reports" / "d6" / "coverage" / "manifest.json"
    report = build_phase_d6_coinbase_candle_ingest_report(
        as_of=AS_OF,
        tickers=["BTC-USDC"],
        timeframes=["1D"],
        years=[3],
        max_chunks=1,
        fetch=True,
        client=client,
        output_root=tmp_path / "research_data" / "coinbase" / "candles",
        manifest_output=manifest,
        now=NOW,
    )

    assert report["status"] == "d6_coinbase_candle_ingest_fetched"
    assert report["fetch_executed"] is True
    assert report["coinbase_call_count"] == 1
    assert [call["method"] for call in client.calls] == ["get_public_candles"]
    assert client.calls[0]["product_id"] == "BTC-USDC"
    assert client.calls[0]["granularity"] == "ONE_DAY"
    assert client.calls[0]["limit"] == 350
    assert report["chunks_requested"] == 1
    assert report["chunks_fetched"] == 1
    assert report["candle_count"] == 2
    assert report["entries"][0]["gap_count"] == 1
    assert manifest.exists()
    output_path = Path(report["entries"][0]["output_path"])
    assert output_path.exists()
    candles = json.loads(output_path.read_text(encoding="utf-8"))
    assert [c["start"] for c in candles] == [1685318400, 1685491200]
    assert candles[0]["open"] == "100.5"
    _assert_report_only(report)


def test_fetch_requires_explicit_max_chunks_and_blocks_without_call(tmp_path: Path):
    client = FakeCoinbaseClient()
    report = build_phase_d6_coinbase_candle_ingest_report(
        as_of=AS_OF,
        tickers=["BTC-USDC"],
        timeframes=["1D"],
        years=[3],
        fetch=True,
        client=client,
        output_root=tmp_path / "research_data",
        now=NOW,
    )

    assert report["status"] == "d6_coinbase_candle_ingest_blocked"
    assert "fetch_requires_explicit_max_chunks" in report["blockers"]
    assert report["coinbase_call_count"] == 0
    assert client.calls == []
    assert not (tmp_path / "research_data").exists()


def test_fetch_refuses_unbounded_full_universe_even_with_max_chunks(tmp_path: Path):
    client = FakeCoinbaseClient()
    report = build_phase_d6_coinbase_candle_ingest_report(
        as_of=AS_OF,
        max_chunks=1,
        fetch=True,
        client=client,
        output_root=tmp_path / "research_data",
        now=NOW,
    )

    assert report["status"] == "d6_coinbase_candle_ingest_blocked"
    assert "fetch_selection_too_large" in report["blockers"]
    assert report["coinbase_call_count"] == 0
    assert client.calls == []


def test_output_under_state_or_env_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_coinbase_candle_ingest_report(
            as_of=AS_OF,
            tickers=["BTC-USDC"],
            timeframes=["1D"],
            years=[3],
            output_root=tmp_path / "state" / "research_data",
            now=NOW,
        )

    with pytest.raises(ValueError, match="env"):
        build_phase_d6_coinbase_candle_ingest_report(
            as_of=AS_OF,
            tickers=["BTC-USDC"],
            timeframes=["1D"],
            years=[3],
            output_root=tmp_path / ".env",
            now=NOW,
        )


def test_api_error_is_recorded_safely(tmp_path: Path):
    client = FakeCoinbaseClient(fail=True)
    report = build_phase_d6_coinbase_candle_ingest_report(
        as_of=AS_OF,
        tickers=["BTC-USDC"],
        timeframes=["1D"],
        years=[3],
        max_chunks=1,
        fetch=True,
        client=client,
        output_root=tmp_path / "research_data",
        now=NOW,
    )

    assert report["status"] == "d6_coinbase_candle_ingest_fetched"
    assert report["coinbase_call_count"] == 1
    assert report["chunks_fetched"] == 0
    assert report["candle_count"] == 0
    assert report["errors"][0]["error"] == "fixture_api_error"
    assert report["entries"][0]["errors"][0]["error_type"] == "RuntimeError"
    output_path = Path(report["entries"][0]["output_path"])
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == []
    _assert_report_only(report)


def test_normalize_candles_drops_open_candle_and_deduplicates():
    candles = normalize_candles(
        [
            {"start": "1685318400", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "10"},
            {"start": "1685318400", "open": "1.1", "high": "2.1", "low": "0.6", "close": "1.6", "volume": "11"},
            {"start": str(int(NOW.timestamp()) - 100), "open": "9", "high": "9", "low": "9", "close": "9", "volume": "9"},
        ],
        product_id="BTC-USDC",
        timeframe="1H",
        fetched_at=NOW,
    )

    assert len(candles) == 1
    assert candles[0]["start"] == 1685318400
    assert candles[0]["open"] == "1.1"
    assert candles[0]["source"] == "Coinbase candles"


def test_cli_default_dry_run_and_state_output_refusal(tmp_path: Path):
    dry = subprocess.run(
        [
            sys.executable,
            "tools/fetch_phase_d6_coinbase_candles.py",
            "--as-of",
            AS_OF,
            "--tickers",
            "BTC-USDC",
            "--timeframes",
            "1D",
            "--years",
            "3",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    dry_report = json.loads(dry.stdout)
    assert dry_report["status"] == "d6_coinbase_candle_ingest_dry_run"
    assert dry_report["coinbase_call_count"] == 0
    _assert_report_only(dry_report)

    bad = subprocess.run(
        [
            sys.executable,
            "tools/fetch_phase_d6_coinbase_candles.py",
            "--as-of",
            AS_OF,
            "--tickers",
            "BTC-USDC",
            "--output-root",
            str(tmp_path / "state" / "candles"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )
    assert bad.returncode != 0
    assert "d6_ingest_output_path_must_not_be_under_state" in bad.stderr
