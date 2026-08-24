import json

from dashboard.backend.services import orders as orders_service
from dashboard.backend.services import positions as positions_service
from dashboard.backend.services import ticker_universe


def test_get_positions_marks_open_vs_closed(monkeypatch, tmp_path):
    fixture = {
        "BTC-USDC": {"close_time": None, "entry_price": "100", "position_risk_incomplete": False},
        "ETH-USDC": {"close_time": "2026-06-01T00:00:00Z", "entry_price": "50", "position_risk_incomplete": True},
    }
    path = tmp_path / "positions.json"
    path.write_text(json.dumps(fixture))
    monkeypatch.setattr(positions_service, "resolve_state_file", lambda name: path)

    result = positions_service.get_positions()

    assert result["summary"]["total"] == 2
    assert result["summary"]["open_count"] == 1
    by_ticker = {p["ticker"]: p for p in result["positions"]}
    assert by_ticker["BTC-USDC"]["is_open"] is True
    assert by_ticker["ETH-USDC"]["is_open"] is False


def test_closed_risk_incomplete_does_not_count_as_open_warning(monkeypatch, tmp_path):
    # Regression test: a closed position can carry a leftover
    # position_risk_incomplete=true flag from before it was closed (e.g.
    # controlled_position_close_filled). That is historical data quality,
    # not current exposure, and must never be counted/shown as an actual
    # open-risk warning.
    fixture = {
        "AVAX-USDC": {
            "close_time": "2026-06-19T15:27:09.432423+00:00",
            "close_reason": "controlled_position_close_filled",
            "status": "closed",
            "position_risk_incomplete": True,
        },
        "BTC-USDC": {
            "close_time": None,
            "status": "open",
            "position_risk_incomplete": True,
        },
        "ETH-USDC": {
            "close_time": None,
            "status": "open",
            "position_risk_incomplete": False,
        },
    }
    path = tmp_path / "positions.json"
    path.write_text(json.dumps(fixture))
    monkeypatch.setattr(positions_service, "resolve_state_file", lambda name: path)

    result = positions_service.get_positions()
    summary = result["summary"]

    assert summary["open_risk_incomplete_count"] == 1
    assert summary["open_risk_incomplete_tickers"] == ["BTC-USDC"]
    assert summary["closed_risk_incomplete_count"] == 1
    assert summary["closed_risk_incomplete_tickers"] == ["AVAX-USDC"]


def test_get_positions_hides_closed_positions_outside_ticker_universe(monkeypatch, tmp_path):
    fixture = {
        "BTC-USDC": {"close_time": None, "entry_price": "100"},
        "XRP-USDC": {"close_time": "2026-06-01T00:00:00Z", "entry_price": "0.5"},
    }
    path = tmp_path / "positions.json"
    path.write_text(json.dumps(fixture))
    monkeypatch.setattr(positions_service, "resolve_state_file", lambda name: path)
    universe_path = tmp_path / "runtime_ticker_universe.json"
    universe_path.write_text(json.dumps({"configured_ticker_universe": ["BTC-USDC"]}))
    monkeypatch.setattr(ticker_universe, "resolve_state_file", lambda name: universe_path)

    result = positions_service.get_positions()

    tickers = {p["ticker"] for p in result["positions"]}
    assert tickers == {"BTC-USDC"}


def test_get_positions_never_hides_an_open_position_outside_ticker_universe(monkeypatch, tmp_path):
    # A currently open position must stay visible even if ALLOWED_TICKERS
    # shrank after it was entered -- it still needs to be monitored/exited.
    fixture = {
        "XRP-USDC": {"close_time": None, "entry_price": "0.5"},
    }
    path = tmp_path / "positions.json"
    path.write_text(json.dumps(fixture))
    monkeypatch.setattr(positions_service, "resolve_state_file", lambda name: path)
    universe_path = tmp_path / "runtime_ticker_universe.json"
    universe_path.write_text(json.dumps({"configured_ticker_universe": ["BTC-USDC"]}))
    monkeypatch.setattr(ticker_universe, "resolve_state_file", lambda name: universe_path)

    result = positions_service.get_positions()

    tickers = {p["ticker"] for p in result["positions"]}
    assert tickers == {"XRP-USDC"}


def test_get_positions_handles_missing_file(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist.json"
    monkeypatch.setattr(positions_service, "resolve_state_file", lambda name: missing)

    result = positions_service.get_positions()

    assert result["positions"] == []
    assert result["summary"]["total"] == 0


def test_get_orders_classifies_open_orders(monkeypatch, tmp_path):
    fixture = {
        "orders": {
            "order-1": {"status": "filled", "remaining_size": "0", "ticker": "BTC-USDC"},
            "order-2": {"status": "open", "remaining_size": "1", "ticker": "ETH-USDC"},
            "order-3": {
                "status": "open",
                "remaining_size": "1",
                "ticker": "BTC-USDC",
                "phase": "D3_controlled_live_reduce_only_exits",
                "client_order_id": "phased3-BTCUSDC-TP1",
            },
        }
    }
    path = tmp_path / "open_orders.json"
    path.write_text(json.dumps(fixture))
    monkeypatch.setattr(orders_service, "resolve_state_file", lambda name: path)
    monkeypatch.setattr(orders_service.cache, "get_or_compute", lambda key, compute, ttl_seconds=None: {})

    result = orders_service.get_orders()

    assert result["summary"]["total"] == 3
    assert result["summary"]["open_count"] == 2
    assert result["summary"]["open_d3_exit_count"] == 1
