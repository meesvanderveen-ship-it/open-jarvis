from bot.phase_d6_historical_data_downloader import plan_historical_download


def test_historical_download_plan_chunks_and_refuses_live_scope(tmp_path):
    plan = plan_historical_download(
        source="coinbase",
        product="BTC-USDC",
        symbol="BTCUSDC",
        timeframe="1H",
        start=0,
        end=3600 * 800,
        max_chunks=3,
        max_requests=3,
        candidate_root=tmp_path / "candidates",
        run_id="run",
    )

    assert plan["chunk_count"] == 3
    assert plan["source_contract"]["role"] == "primary_execution_market"
    assert plan["coinbase_account_or_order_call_performed"] is False
    assert plan["allow_merge_default"] is False
    assert plan["fetch_plan"]["request_count"] == 3
