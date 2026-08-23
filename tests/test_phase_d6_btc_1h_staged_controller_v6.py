import json
from pathlib import Path

from bot.phase_d6_btc_1h_staged_controller_v6 import (
    build_btc_1h_staged_controller_plan_v6,
    build_resume_status_v8,
)


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_v6_plan_starts_at_chunk16_and_records_fail_closed_gate(tmp_path: Path) -> None:
    resume = _write_json(
        tmp_path / "resume.json",
        {
            "content": {
                "previous_completed_chunks": ["BTCUSDC-1H-gap01:chunk0"],
                "new_completed_chunks": ["BTCUSDC-1H-gap01:chunk13", "BTCUSDC-1H-gap01:chunk14", "BTCUSDC-1H-gap01:chunk15"],
                "next_pending_scope": "BTCUSDC-1H-gap01:chunk16_or_review",
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

    plan = build_btc_1h_staged_controller_plan_v6(
        resume_status_path=resume,
        candidate_root=tmp_path / "candidates",
        max_chunks=1,
        candles_per_chunk=2,
        existing_path=candles,
    )

    chunk = plan["chunks"][0]
    assert plan["report_name"] == "btc_1h_staged_controller_plan_v6"
    assert chunk["chunk_id"] == "BTCUSDC-1H-gap01:chunk16"
    assert chunk["resume_status_before_chunk"] == "BTCUSDC-1H-gap01:chunk16_or_review"
    assert chunk["next_chunk_gate"] == "requires_this_chunk_completed_exact_validation_and_clean_rate_limit"
    assert plan["operational_safety"]["fail_closed_reason_required_on_stop"] is True
    assert "v32-v33" in chunk["candidate_output_path"]


def test_v8_resume_points_to_chunk19_after_chunk18() -> None:
    plan = {"chunks": [{"chunk_id": "BTCUSDC-1H-gap01:chunk18"}], "resume_status": {"completed_pilot_chunks": ["BTCUSDC-1H-gap01:chunk15"]}}
    result = {"completed_chunk_ids": ["BTCUSDC-1H-gap01:chunk16", "BTCUSDC-1H-gap01:chunk17", "BTCUSDC-1H-gap01:chunk18"]}

    resume = build_resume_status_v8(plan=plan, result=result)

    assert resume["report_name"] == "btc_1h_staged_resume_status_v8"
    assert resume["next_pending_scope"] == "BTCUSDC-1H-gap01:chunk19_or_review"
    assert resume["auto_resume_allowed"] is False
    assert resume["no_auto_resume_after_failure"] is True
