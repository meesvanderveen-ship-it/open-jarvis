import json
from pathlib import Path

from bot.phase_d6_btc_1h_server_downloader import (
    build_progress_report,
    build_resume_status_v11,
    build_server_download_plan,
    normalize_resume_for_controller,
)


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_normalize_resume_adds_next_pending_scope_and_completed_chunks() -> None:
    resume = {
        "next_scope": "BTCUSDC-1H-gap01:chunk37_or_review",
        "completed_chunks_total": 37,
        "auto_resume_allowed": False,
    }

    normalized = normalize_resume_for_controller(resume)

    assert normalized["next_pending_scope"] == "BTCUSDC-1H-gap01:chunk37_or_review"
    assert normalized["next_scope"] == "BTCUSDC-1H-gap01:chunk37_or_review"
    assert len(normalized["completed_pilot_chunks"]) == 37
    assert normalized["completed_pilot_chunks"][-1] == "BTCUSDC-1H-gap01:chunk36"
    assert normalized["auto_resume_allowed"] is False


def test_server_download_plan_caps_at_30_chunks_and_uses_three_chunk_phases(tmp_path: Path) -> None:
    resume = _write_json(
        tmp_path / "resume.json",
        {
            "content": {
                "next_scope": "BTCUSDC-1H-gap01:chunk37_or_review",
                "completed_chunks_total": 37,
                "auto_resume_allowed": False,
            }
        },
    )
    candles = []
    for start in range(0, 5 * 3600, 3600):
        candles.append({"product_id": "BTC-USDC", "timeframe": "1H", "start": start})
    candles.append({"product_id": "BTC-USDC", "timeframe": "1H", "start": 5 * 3600 + 10205 * 3600})
    candle_path = _write_json(tmp_path / "btc1h.json", candles)

    plan = build_server_download_plan(
        resume_status_path=resume,
        candidate_root=tmp_path / "candidates",
        max_chunks=30,
        phase_size=3,
        existing_path=candle_path,
        cooldown_seconds=0,
    )

    assert plan["status"] == "btc_1h_server_download_plan_v1_ready"
    assert plan["planned_chunk_count"] == 30
    assert plan["planned_phase_count"] == 10
    assert plan["phases"][0]["chunk_start"] == 37
    assert plan["phases"][0]["chunk_end_inclusive"] == 39
    assert plan["phases"][-1]["chunk_start"] == 64
    assert plan["phases"][-1]["chunk_end_inclusive"] == 66


def test_progress_and_resume_reports_remain_research_only() -> None:
    plan = {
        "start_scope": "BTCUSDC-1H-gap01:chunk37_or_review",
        "planned_chunk_count": 3,
    }
    result = {
        "completed_chunk_count": 3,
        "completed_chunks": ["BTCUSDC-1H-gap01:chunk37", "BTCUSDC-1H-gap01:chunk38", "BTCUSDC-1H-gap01:chunk39"],
        "next_pending_scope": "BTCUSDC-1H-gap01:chunk40_or_review",
        "gap_closed": False,
        "cache_count_before": 16100,
        "cache_count_after": 17150,
        "final_gap": {"gap_start": 1_000_000, "gap_end_exclusive": 2_000_000, "missing_candle_count": 100},
        "stop_reason": "",
    }

    progress = build_progress_report(plan=plan, result=result)
    resume = build_resume_status_v11(plan=plan, result=result)

    assert progress["state_write_performed"] is False
    assert progress["live_order_action_performed"] is False
    assert resume["next_pending_scope"] == "BTCUSDC-1H-gap01:chunk40_or_review"
    assert resume["completed_chunks_total"] == 40
    assert resume["completed_pilot_chunks"][-1] == "BTCUSDC-1H-gap01:chunk39"
    assert resume["auto_resume_allowed"] is False
