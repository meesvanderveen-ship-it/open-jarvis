import json
from pathlib import Path

from bot.phase_d6_btc_1h_staged_controller_v5 import (
    build_btc_1h_staged_controller_plan_v5,
    build_resume_status_v7,
)


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_v5_plan_starts_at_chunk13_and_records_resume_gate(tmp_path: Path) -> None:
    resume = _write_json(
        tmp_path / "resume.json",
        {
            "content": {
                "previous_completed_chunks": ["BTCUSDC-1H-gap01:chunk0"],
                "new_completed_chunks": ["BTCUSDC-1H-gap01:chunk10", "BTCUSDC-1H-gap01:chunk11", "BTCUSDC-1H-gap01:chunk12"],
                "next_pending_scope": "BTCUSDC-1H-gap01:chunk13_or_review",
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

    plan = build_btc_1h_staged_controller_plan_v5(
        resume_status_path=resume,
        candidate_root=tmp_path / "candidates",
        max_chunks=1,
        candles_per_chunk=2,
        existing_path=candles,
    )

    chunk = plan["chunks"][0]
    assert plan["report_name"] == "btc_1h_staged_controller_plan_v5"
    assert chunk["chunk_id"] == "BTCUSDC-1H-gap01:chunk13"
    assert chunk["resume_status_before_chunk"] == "BTCUSDC-1H-gap01:chunk13_or_review"
    assert chunk["binance_reference_optional"] is True
    assert "v30-v31" in chunk["candidate_output_path"]


def test_v7_resume_points_to_chunk16_after_chunk15() -> None:
    plan = {"chunks": [{"chunk_id": "BTCUSDC-1H-gap01:chunk15"}], "resume_status": {"completed_pilot_chunks": ["BTCUSDC-1H-gap01:chunk12"]}}
    result = {"completed_chunk_ids": ["BTCUSDC-1H-gap01:chunk13", "BTCUSDC-1H-gap01:chunk14", "BTCUSDC-1H-gap01:chunk15"]}

    resume = build_resume_status_v7(plan=plan, result=result)

    assert resume["report_name"] == "btc_1h_staged_resume_status_v7"
    assert resume["next_pending_scope"] == "BTCUSDC-1H-gap01:chunk16_or_review"
    assert resume["auto_resume_allowed"] is False
    assert resume["chunk_batch_review_required_before_next_sprint"] is True
