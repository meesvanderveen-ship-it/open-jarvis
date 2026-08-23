from __future__ import annotations

import csv
import json
from pathlib import Path

from tools.run_historical_parameter_backtest import build_historical_parameter_backtest, main as backtest_main


def _write_candles(path: Path, rows: int = 120) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["open", "high", "low", "close", "volume"])
        writer.writeheader()
        price = 100.0
        for idx in range(rows):
            price += 0.2
            writer.writerow({
                "open": price - 0.1,
                "high": price + 0.4,
                "low": price - 0.4,
                "close": price,
                "volume": 1000 + idx,
            })


def test_historical_backtest_reports_missing_data_honestly(tmp_path):
    report = build_historical_parameter_backtest(root=tmp_path, generated_at="2026-06-14T00:00:00Z")
    assert report["coinbase_call_attempted"] is False
    assert report["historical_orderbook_available"] is False
    assert report["candidate"]["safe_to_live_activate_now"] is False
    assert report["candidate"]["requires_operator_review"] is True
    assert report["candidate"]["sample_size"] == 0
    assert report["data_missing"]


def test_historical_backtest_uses_local_fixture_candles(tmp_path):
    _write_candles(tmp_path / "data/candles/btc_usdc_1h.csv")
    report = build_historical_parameter_backtest(root=tmp_path, generated_at="2026-06-14T00:00:00Z")
    assert report["candidate"]["sample_size"] >= 120
    assert any(row.get("data_available") for row in report["results"])
    assert report["candidate"]["safe_to_live_activate_now"] is False


def test_historical_backtest_tool_writes_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = backtest_main([])
    assert rc == 0
    payload = json.loads((tmp_path / "reports/backtests/btc-eth-parameter-backtest-latest.json").read_text())
    assert payload["candidate"]["safe_to_live_activate_now"] is False
    assert (tmp_path / "reports/backtests/btc-eth-parameter-backtest-latest.md").exists()

