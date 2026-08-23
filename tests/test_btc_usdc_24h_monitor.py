from __future__ import annotations

import json
from pathlib import Path

from tools.show_btc_usdc_24h_live_monitor import (
    OK,
    STOP_NOW,
    WATCH,
    _extract_tickers_from_loop_log,
    _iter_jsonl,
    _load_orders,
    build_monitor_report,
    summarize_orders,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_minimal_state(root: Path, *, orders: dict | None = None) -> None:
    _write_json(root / "state" / "open_orders.json", {"orders": orders or {}})
    _write_json(root / "state" / "positions.json", {"BTC-USDC": {"position_size_base": "0"}})


def test_summarize_orders_counts_open_and_d3_exit() -> None:
    summary = summarize_orders(
        [
            {
                "client_order_id": "phased3-BTCUSDC-TP1-test",
                "ticker": "BTC-USDC",
                "side": "SELL",
                "status": "submitted",
                "remaining_size": "0.0001",
                "limit_price": "70000",
            },
            {"client_order_id": "filled", "ticker": "BTC-USDC", "side": "BUY", "status": "filled", "size_quote": "5"},
        ]
    )

    assert summary["open_orders"] == 1
    assert summary["open_d3_exits"] == 1
    assert summary["unexpected_sell_samples"]


def test_ticker_scope_parser_flags_non_btc_startups() -> None:
    text = "\n".join(
        [
            "2026-06-09 01:00:00 INFO Execution mode=paper | tickers=BTC-USDC",
            "2026-06-09 01:05:00 INFO Execution mode=paper | tickers=BTC-USDC,ETH-USDC",
        ]
    )

    parsed = _extract_tickers_from_loop_log(text, since=None)

    assert parsed["last_startup"]["tickers"] == ["BTC-USDC", "ETH-USDC"]
    assert parsed["suspicious_startups"]


def test_jsonl_reader_fail_closed_for_missing_and_malformed_logs(tmp_path: Path) -> None:
    assert _iter_jsonl(tmp_path / "missing.jsonl") == []
    path = tmp_path / "logs" / "cycle_summary.jsonl"
    path.parent.mkdir()
    path.write_text('{"generated_at":"2026-06-09T00:00:00Z","total":1}\nnot-json\n', encoding="utf-8")

    rows = _iter_jsonl(path)

    assert rows[0]["total"] == 1
    assert rows[1]["_parse_error"] is True


def test_monitor_builds_watch_report_without_process_or_live_calls(tmp_path: Path) -> None:
    _write_minimal_state(tmp_path)

    report = build_monitor_report(root=tmp_path, detect_processes=False)

    assert report["classification"] == WATCH
    assert "run_process_not_active" in report["stop_rule_reasons"]
    assert report["read_only"] is True
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["orders"]["open_orders"] == 0


def test_monitor_stop_now_on_non_btc_runtime_scope(tmp_path: Path) -> None:
    _write_minimal_state(tmp_path)
    log = tmp_path / "logs" / "loop.log"
    log.parent.mkdir(parents=True)
    log.write_text("2026-06-09 01:05:00 INFO Execution mode=paper | tickers=BTC-USDC,ETH-USDC\n", encoding="utf-8")

    report = build_monitor_report(root=tmp_path, detect_processes=False)

    assert report["classification"] == STOP_NOW
    assert "non_btc_runtime_scope_seen" in report["stop_rule_reasons"]
    assert report["no_coinbase_call"] is True


def test_load_orders_and_monitor_do_not_write_state(tmp_path: Path) -> None:
    orders = {"one": {"client_order_id": "one", "ticker": "BTC-USDC", "side": "BUY", "status": "filled"}}
    _write_minimal_state(tmp_path, orders=orders)
    before = (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8")

    loaded = _load_orders(tmp_path / "state" / "open_orders.json")
    report = build_monitor_report(root=tmp_path, detect_processes=False)

    assert loaded[0]["client_order_id"] == "one"
    assert report["state_write_performed"] is False
    assert (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8") == before
    assert report["classification"] in {OK, WATCH}
