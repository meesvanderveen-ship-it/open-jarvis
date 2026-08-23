from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.show_btc_usdc_24h_live_monitor import (
    OK,
    STOP_NOW,
    WATCH,
    build_monitor_report,
    _markdown,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "REPLICATION_ENABLED=false",
                "ENABLE_LIVE_EXIT_ORDERS=false",
                "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false",
                "LEARNING_TO_EXECUTION_ALLOWED=false",
                "PARAMETER_CHANGE_ALLOWED=false",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "state/open_orders.json").write_text(json.dumps({"orders": {}}), encoding="utf-8")
    (tmp_path / "state/positions.json").write_text(json.dumps({"positions": {}}), encoding="utf-8")
    _write_jsonl(
        tmp_path / "logs/cycle_summary.jsonl",
        [{"generated_at": "2026-06-09T10:00:00+00:00", "total": 1, "errors": 0, "executed": 0}],
    )
    _write_jsonl(
        tmp_path / "logs/heartbeat_summary.jsonl",
        [{"generated_at": "2026-06-09T10:00:00+00:00", "total": 0, "errors": 0, "executed": 0}],
    )
    _write_jsonl(
        tmp_path / "logs/phase_c43_lifecycle_service.jsonl",
        [{"generated_at": "2026-06-09T10:00:00+00:00", "status": "no_open_orders_noop"}],
    )
    (tmp_path / "logs/loop.log").write_text(
        "2026-06-09 10:00:00,000 - INFO - Execution mode=live | tickers=BTC-USDC\n",
        encoding="utf-8",
    )
    return tmp_path


def test_monitor_reports_ok_when_btc_only_and_process_active(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(
        "tools.show_btc_usdc_24h_live_monitor._detect_active_processes",
        lambda: [{"pid": 123, "cmdline": "python run_trader_loop.py"}],
    )

    report = build_monitor_report(root=root, since=None)

    assert report["read_only"] is True
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["classification"] == OK
    assert report["orders"]["open_orders"] == 0
    assert report["logs"]["ticker_scope"]["last_startup"]["tickers"] == ["BTC-USDC"]


def test_monitor_stops_on_multi_ticker_runtime_scope(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(
        "tools.show_btc_usdc_24h_live_monitor._detect_active_processes",
        lambda: [{"pid": 123, "cmdline": "python run_trader_loop.py"}],
    )
    (root / "logs/loop.log").write_text(
        "2026-06-09 10:00:00,000 - INFO - Execution mode=live | tickers=BTC-USDC,ETH-USDC\n",
        encoding="utf-8",
    )

    report = build_monitor_report(root=root, since=None)

    assert report["classification"] == STOP_NOW
    assert "non_btc_runtime_scope_seen" in report["stop_rule_reasons"]
    assert "cycle_total_not_btc_only" not in report["stop_rule_reasons"]


def test_monitor_stops_on_open_d3_exit_and_oversized_order(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(
        "tools.show_btc_usdc_24h_live_monitor._detect_active_processes",
        lambda: [{"pid": 123, "cmdline": "python run_trader_loop.py"}],
    )
    order = {
        "client_order_id": "d3exit-BTCUSDC-TP1",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "size_quote": "11.00",
        "updated_at": "2026-06-09T10:00:00+00:00",
    }
    (root / "state/open_orders.json").write_text(json.dumps({"orders": {"x": order}}), encoding="utf-8")

    report = build_monitor_report(root=root, since=None)

    assert report["classification"] == STOP_NOW
    assert "unexpected_open_d3_exit" in report["stop_rule_reasons"]
    assert "order_notional_above_10_usdc" in report["stop_rule_reasons"]
    assert "unexpected_sell_or_exit_order" in report["stop_rule_reasons"]


def test_monitor_reports_hash_drift_without_writing_state(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr("tools.show_btc_usdc_24h_live_monitor._detect_active_processes", lambda: [])
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")

    report = build_monitor_report(
        root=root,
        since=None,
        baseline_open_orders_hash="not-the-current-hash",
        baseline_positions_hash="not-the-current-hash",
    )

    assert report["classification"] == STOP_NOW
    assert "state_hash_drift_open_orders" in report["stop_rule_reasons"]
    assert "state_hash_drift_positions" in report["stop_rule_reasons"]
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions


def test_monitor_watch_when_no_run_process(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr("tools.show_btc_usdc_24h_live_monitor._detect_active_processes", lambda: [])

    report = build_monitor_report(root=root, since=None)

    assert report["classification"] == WATCH
    assert report["stop_rule_reasons"] == ["run_process_not_active"]


def test_monitor_stops_on_llm_and_provider_error_bursts(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(
        "tools.show_btc_usdc_24h_live_monitor._detect_active_processes",
        lambda: [{"pid": 123, "cmdline": "python run_trader_loop.py"}],
    )
    _write_jsonl(
        root / "logs/llm_corrupt.jsonl",
        [
            {"generated_at": "2026-06-09T10:01:00+00:00", "ticker": "BTC-USDC", "error": "bad_json"},
            {"generated_at": "2026-06-09T10:02:00+00:00", "ticker": "BTC-USDC", "error": "bad_json"},
            {"generated_at": "2026-06-09T10:03:00+00:00", "ticker": "BTC-USDC", "error": "bad_json"},
        ],
    )
    _write_jsonl(
        root / "logs/llm_provider_errors.jsonl",
        [
            {"generated_at": "2026-06-09T10:01:00+00:00", "provider": "openai", "error": "rate_limit"},
            {"generated_at": "2026-06-09T10:02:00+00:00", "provider": "openai", "error": "rate_limit"},
            {"generated_at": "2026-06-09T10:03:00+00:00", "provider": "openai", "error": "rate_limit"},
        ],
    )

    report = build_monitor_report(root=root, since=None)
    markdown = _markdown(report)

    assert report["classification"] == STOP_NOW
    assert "llm_corrupt_burst" in report["stop_rule_reasons"]
    assert "provider_error_burst" in report["stop_rule_reasons"]
    assert "- recent_llm_corrupt: `3`" in markdown
    assert "- recent_provider_errors: `3`" in markdown
