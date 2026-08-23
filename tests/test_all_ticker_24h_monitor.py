from __future__ import annotations

import json
from pathlib import Path

from bot.phase_all_ticker_24h_monitor import (
    build_all_ticker_24h_monitor_report,
    render_all_ticker_24h_monitor_markdown,
)


def _write_orders(root: Path, orders: dict) -> None:
    path = root / "state" / "open_orders.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"orders": orders}), encoding="utf-8")


def test_all_tickers_supported_with_no_orders(tmp_path: Path) -> None:
    _write_orders(tmp_path, {})
    report = build_all_ticker_24h_monitor_report(root=tmp_path)

    assert report["classification"] == "OK"
    assert report["governance_flags"]["all_ticker_monitor_scaffold_ready"] is True
    assert len(report["per_ticker_monitor"]) == 18
    assert report["metadata"]["coinbase_call_attempted"] is False
    assert report["metadata"]["state_write_performed"] is False


def test_open_order_fails_closed(tmp_path: Path) -> None:
    _write_orders(tmp_path, {"o1": {"ticker": "ETH-USDC", "status": "open", "side": "BUY"}})
    report = build_all_ticker_24h_monitor_report(root=tmp_path)
    row = {item["ticker"]: item for item in report["per_ticker_monitor"]}["ETH-USDC"]

    assert report["classification"] == "STOP_NOW"
    assert row["open_order_count"] == 1


def test_monitor_markdown_renders(tmp_path: Path) -> None:
    _write_orders(tmp_path, {})
    markdown = render_all_ticker_24h_monitor_markdown(build_all_ticker_24h_monitor_report(root=tmp_path))

    assert "All-Ticker 24h Monitor" in markdown
    assert "BTC-USDC" in markdown
