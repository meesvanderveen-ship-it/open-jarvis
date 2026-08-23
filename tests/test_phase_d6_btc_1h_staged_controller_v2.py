import json
from pathlib import Path

from bot.phase_d6_btc_1h_staged_controller_v2 import (
    build_btc_1h_staged_controller_plan_v2,
    build_resume_status_v4,
)


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_v2_plan_uses_next_chunk_from_v3_resume(tmp_path: Path) -> None:
    resume = _write_json(
        tmp_path / "resume.json",
        {
            "content": {
                "status": "btc_1h_staged_resume_status_v3_ready",
                "previous_completed_chunks": ["BTCUSDC-1H-gap01:chunk0"],
                "new_completed_chunks": [
                    "BTCUSDC-1H-gap01:chunk1",
                    "BTCUSDC-1H-gap01:chunk2",
                    "BTCUSDC-1H-gap01:chunk3",
                ],
                "next_pending_scope": "BTCUSDC-1H-gap01:chunk4_or_review",
                "auto_resume_allowed": False,
            }
        },
    )
    candles = _write_json(
        tmp_path / "btc1h.json",
        [
            {"product_id": "BTC-USDC", "timeframe": "1H", "start": 0},
            {"product_id": "BTC-USDC", "timeframe": "1H", "start": 3600},
            {"product_id": "BTC-USDC", "timeframe": "1H", "start": 3600 * 5},
        ],
    )

    plan = build_btc_1h_staged_controller_plan_v2(
        resume_status_path=resume,
        candidate_root=tmp_path / "candidates",
        max_chunks=1,
        candles_per_chunk=2,
        existing_path=candles,
    )

    assert plan["report_name"] == "btc_1h_staged_controller_plan_v2"
    assert plan["status"] == "btc_1h_staged_controller_plan_v2_ready"
    assert plan["chunks"][0]["chunk_id"] == "BTCUSDC-1H-gap01:chunk4"
    assert "v24-v25" in plan["chunks"][0]["candidate_output_path"]


def test_v4_resume_points_to_next_review_chunk() -> None:
    plan = {
        "chunks": [{"chunk_id": "BTCUSDC-1H-gap01:chunk4"}],
        "resume_status": {"completed_pilot_chunks": ["BTCUSDC-1H-gap01:chunk0"]},
    }
    result = {"completed_chunk_ids": ["BTCUSDC-1H-gap01:chunk4"], "status": "btc_1h_staged_controller_result_v2_ready"}

    resume = build_resume_status_v4(plan=plan, result=result)

    assert resume["report_name"] == "btc_1h_staged_resume_status_v4"
    assert resume["next_pending_scope"] == "BTCUSDC-1H-gap01:chunk5_or_review"
    assert resume["auto_resume_allowed"] is False
