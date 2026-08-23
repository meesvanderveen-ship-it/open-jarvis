from datetime import datetime, timezone
import json

from bot.phase_d6_tail_candle_refresh import (
    build_tail_chunk_plan,
    build_tail_refresh_plan,
    execute_tail_refresh,
    merge_tail_refresh_result,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_public_candles(self, *, product_id, granularity, start, end, limit):
        self.calls.append(
            {
                "product_id": product_id,
                "granularity": granularity,
                "start": start,
                "end": end,
                "limit": limit,
            }
        )
        return {
            "candles": [
                {
                    "start": int(start),
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100",
                    "volume": "1",
                },
                {
                    "start": int(end) - 3600,
                    "open": "101",
                    "high": "102",
                    "low": "100",
                    "close": "101",
                    "volume": "2",
                },
            ]
        }


def test_tail_chunk_plan_ends_at_as_of_and_moves_backward() -> None:
    chunks = build_tail_chunk_plan(as_of="2026-06-01T00:00:00Z", timeframe="1H", max_chunks=2)

    assert len(chunks) == 2
    assert chunks[-1]["end"] == "2026-06-01T00:00:00Z"
    assert chunks[0]["start"] < chunks[0]["end"] <= chunks[1]["start"] < chunks[1]["end"]


def test_dry_run_plan_is_research_only_and_candidate_rooted() -> None:
    plan = build_tail_refresh_plan(
        as_of="2026-06-01T00:00:00Z",
        tickers=["BTC-USDC"],
        timeframes=["1H"],
        max_chunks=1,
        output_root="/tmp/d6_tail_refresh_test",
    )

    assert plan["dry_run"] is True
    assert plan["fetch_executed"] is False
    assert plan["no_live_action"] is True
    assert plan["state_write_performed"] is False
    assert plan["parameter_change_allowed"] is False
    assert plan["learning_to_execution_enabled"] is False
    assert plan["entries"][0]["candidate_output_path"].startswith("/tmp/d6_tail_refresh_test/")


def test_execute_tail_refresh_uses_public_client_only(tmp_path) -> None:
    plan = build_tail_refresh_plan(
        as_of="2026-06-01T00:00:00Z",
        tickers=["BTC-USDC"],
        timeframes=["1H"],
        max_chunks=1,
        output_root=tmp_path / "candidate",
    )
    client = FakeClient()
    report = execute_tail_refresh(
        plan=plan,
        client=client,
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert report["fetch_executed"] is True
    assert report["coinbase_public_market_data_call_count"] == 1
    assert client.calls[0]["product_id"] == "BTC-USDC"
    assert report["entries"][0]["candle_count"] == 2
    assert report["coinbase_write_performed"] is False
    assert report["live_order_action_performed"] is False


def test_merge_tail_refresh_dedups_and_updates_existing(tmp_path) -> None:
    existing = tmp_path / "research" / "product=BTC-USDC" / "timeframe=1H" / "study_window=3y.json"
    candidate = tmp_path / "candidate" / "product=BTC-USDC" / "timeframe=1H" / "study_window=3y.json"
    existing.parent.mkdir(parents=True)
    candidate.parent.mkdir(parents=True)
    existing.write_text(json.dumps([{"start": 1, "close": "1"}]), encoding="utf-8")
    candidate.write_text(json.dumps([{"start": 1, "close": "1"}, {"start": 2, "close": "2"}]), encoding="utf-8")

    result = merge_tail_refresh_result(
        fetch_result={
            "entries": [
                {
                    "ticker": "BTC-USDC",
                    "timeframe": "1H",
                    "candidate_output_path": str(candidate),
                    "existing_cache_path": str(existing),
                }
            ]
        }
    )

    assert result["updated_file_count"] == 1
    merged = json.loads(existing.read_text(encoding="utf-8"))
    assert [row["start"] for row in merged] == [1, 2]
    assert result["state_write_performed"] is False
