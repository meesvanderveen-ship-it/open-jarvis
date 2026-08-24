import json

from dashboard.backend.services import ticker_universe


def test_get_allowed_tickers_reads_configured_universe(monkeypatch, tmp_path):
    path = tmp_path / "runtime_ticker_universe.json"
    path.write_text(json.dumps({
        "allowed_tickers": ["BTC-USDC", "ETH-USDC"],
        "configured_ticker_universe": ["BTC-USDC", "ETH-USDC", "SOL-USDC", "LINK-USDC"],
    }))
    monkeypatch.setattr(ticker_universe, "resolve_state_file", lambda name: path)

    assert ticker_universe.get_allowed_tickers() == ["BTC-USDC", "ETH-USDC", "SOL-USDC", "LINK-USDC"]


def test_get_allowed_tickers_fails_open_on_missing_file(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(ticker_universe, "resolve_state_file", lambda name: missing)

    assert ticker_universe.get_allowed_tickers() == []


def test_filter_to_allowed_tickers_is_noop_when_universe_unknown(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(ticker_universe, "resolve_state_file", lambda name: missing)

    items = [{"ticker": "BTC-USDC"}, {"ticker": "XRP-USDC"}]
    assert ticker_universe.filter_to_allowed_tickers(items) == items


def test_filter_to_allowed_tickers_hides_tickers_outside_universe(monkeypatch, tmp_path):
    path = tmp_path / "runtime_ticker_universe.json"
    path.write_text(json.dumps({"configured_ticker_universe": ["BTC-USDC", "ETH-USDC"]}))
    monkeypatch.setattr(ticker_universe, "resolve_state_file", lambda name: path)

    items = [{"ticker": "BTC-USDC"}, {"ticker": "XRP-USDC"}, {"ticker": "eth-usdc"}]
    filtered = ticker_universe.filter_to_allowed_tickers(items)

    assert {i["ticker"] for i in filtered} == {"BTC-USDC", "eth-usdc"}
