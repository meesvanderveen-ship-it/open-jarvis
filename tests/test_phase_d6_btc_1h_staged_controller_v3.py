import json
from pathlib import Path

from bot.phase_d6_btc_1h_staged_controller_v3 import (
    build_btc_1h_staged_controller_plan_v3,
    build_resume_status_v5,
)


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_v3_plan_starts_at_chunk7_and_records_fail_closed_reasons(tmp_path: Path) -> None:
    resume = _write_json(
        tmp_path / "resume.json",
        {
            "content": {
                "previous_completed_chunks": ["BTCUSDC-1H-gap01:chunk0"],
                "new_completed_chunks": ["BTCUSDC-1H-gap01:chunk4", "BTCUSDC-1H-gap01:chunk5", "BTCUSDC-1H-gap01:chunk6"],
                "next_pending_scope": "BTCUSDC-1H-gap01:chunk7_or_review",
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

    plan = build_btc_1h_staged_controller_plan_v3(
        resume_status_path=resume,
        candidate_root=tmp_path / "candidates",
        max_chunks=1,
        candles_per_chunk=2,
        existing_path=candles,
    )

    assert plan["report_name"] == "btc_1h_staged_controller_plan_v3"
    assert plan["chunks"][0]["chunk_id"] == "BTCUSDC-1H-gap01:chunk7"
    assert "validation_failure" in plan["chunks"][0]["fail_closed_stop_reasons"]
    assert plan["operational_safety"]["stop_after_first_failure"] is True
    assert "v26-v27" in plan["chunks"][0]["candidate_output_path"]


def test_v5_resume_points_to_chunk10_after_chunk9() -> None:
    plan = {"chunks": [{"chunk_id": "BTCUSDC-1H-gap01:chunk9"}], "resume_status": {"completed_pilot_chunks": ["BTCUSDC-1H-gap01:chunk6"]}}
    result = {"completed_chunk_ids": ["BTCUSDC-1H-gap01:chunk7", "BTCUSDC-1H-gap01:chunk8", "BTCUSDC-1H-gap01:chunk9"]}

    resume = build_resume_status_v5(plan=plan, result=result)

    assert resume["report_name"] == "btc_1h_staged_resume_status_v5"
    assert resume["next_pending_scope"] == "BTCUSDC-1H-gap01:chunk10_or_review"
    assert resume["auto_resume_allowed"] is False
