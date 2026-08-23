from dashboard.backend.services import logs as logs_service


def test_tail_log_filters_by_ticker(tmp_path, monkeypatch):
    log_file = tmp_path / "fake.jsonl"
    log_file.write_text(
        '{"ticker": "BTC-USDC", "event": "a"}\n'
        '{"ticker": "ETH-USDC", "event": "b"}\n'
        '{"ticker": "BTC-USDC", "event": "c"}\n'
    )
    monkeypatch.setattr(logs_service, "resolve_under_logs", lambda name: log_file)

    result = logs_service.tail_log("fake.jsonl", limit=10, ticker="BTC-USDC")

    assert len(result["entries"]) == 2
    assert all(e["ticker"] == "BTC-USDC" for e in result["entries"])
    # most recent first
    assert result["entries"][0]["event"] == "c"


def test_tail_log_respects_limit(tmp_path, monkeypatch):
    log_file = tmp_path / "fake.jsonl"
    log_file.write_text("\n".join(f'{{"i": {i}}}' for i in range(50)) + "\n")
    monkeypatch.setattr(logs_service, "resolve_under_logs", lambda name: log_file)

    result = logs_service.tail_log("fake.jsonl", limit=5)

    assert len(result["entries"]) == 5
    assert result["entries"][0]["i"] == 49


def test_missing_log_file_returns_empty(tmp_path, monkeypatch):
    missing = tmp_path / "missing.jsonl"
    monkeypatch.setattr(logs_service, "resolve_under_logs", lambda name: missing)

    result = logs_service.tail_log("missing.jsonl", limit=10)

    assert result["entries"] == []
