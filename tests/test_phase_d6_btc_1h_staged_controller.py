import json
from pathlib import Path

from bot.phase_d6_btc_1h_staged_controller import (
    build_binance_btc_1h_reference_report,
    build_btc_1h_staged_controller_plan,
    build_cross_source_btc_1h_gap_diagnostic,
    build_resume_status_v3,
)


def _write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _resume(path: Path) -> Path:
    return _write_json(
        path,
        {
            "content": {
                "status": "btc_1h_staged_resume_status_ready",
                "completed_pilot_chunks": ["BTCUSDC-1H-gap01:chunk0"],
                "next_pending_scope": "BTCUSDC-1H-gap01:chunk1_or_review",
                "auto_resume_allowed": False,
            }
        },
    )


def _candles(path: Path) -> Path:
    rows = [
        {"product_id": "BTC-USDC", "timeframe": "1H", "start": 0, "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"},
        {"product_id": "BTC-USDC", "timeframe": "1H", "start": 3600, "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"},
        {"product_id": "BTC-USDC", "timeframe": "1H", "start": 3600 * 6, "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"},
    ]
    return _write_json(path, rows)


def test_controller_plan_starts_at_first_missing_candle(tmp_path) -> None:
    plan = build_btc_1h_staged_controller_plan(
        resume_status_path=_resume(tmp_path / "resume.json"),
        candidate_root=tmp_path / "candidates",
        max_chunks=2,
        candles_per_chunk=2,
        existing_path=_candles(tmp_path / "btc1h.json"),
    )

    assert plan["status"] == "btc_1h_staged_controller_plan_ready"
    assert plan["planned_chunk_count"] == 2
    assert plan["chunks"][0]["subrange_start"] == 7200
    assert plan["chunks"][0]["expected_candle_count"] == 2
    assert plan["chunks"][1]["subrange_start"] == 14400
    assert plan["auto_resume_allowed"] is False


def test_controller_plan_requires_auto_resume_disabled(tmp_path) -> None:
    bad_resume = _write_json(tmp_path / "resume.json", {"content": {"auto_resume_allowed": True}})
    plan = build_btc_1h_staged_controller_plan(
        resume_status_path=bad_resume,
        candidate_root=tmp_path / "candidates",
        existing_path=_candles(tmp_path / "btc1h.json"),
    )

    assert plan["status"] == "btc_1h_staged_controller_plan_blocked"
    assert "resume_status_does_not_disable_auto_resume" in plan["blockers"]


def test_resume_status_v3_keeps_operator_review_gate(tmp_path) -> None:
    plan = build_btc_1h_staged_controller_plan(
        resume_status_path=_resume(tmp_path / "resume.json"),
        candidate_root=tmp_path / "candidates",
        max_chunks=1,
        candles_per_chunk=2,
        existing_path=_candles(tmp_path / "btc1h.json"),
    )
    status = build_resume_status_v3(
        plan=plan,
        result={"status": "btc_1h_staged_controller_result_ready", "completed_chunk_ids": ["BTCUSDC-1H-gap01:chunk1"]},
    )

    assert status["new_completed_chunks"] == ["BTCUSDC-1H-gap01:chunk1"]
    assert status["auto_resume_allowed"] is False
    assert status["requires_operator_review_before_next_chunk"] is True


def test_binance_reference_and_cross_source_reports_are_reference_only() -> None:
    controller_result = {
        "binance_reference_rows": [
            {
                "chunk_id": "BTCUSDC-1H-gap01:chunk1",
                "status": "binance_public_klines_fetch_ready",
                "candidate_count": 350,
                "fail_closed": False,
            }
        ],
        "result_rows": [
            {
                "chunk_id": "BTCUSDC-1H-gap01:chunk1",
                "candidate_validation": {"status": "candidate_coverage_validation_pass", "candidate_count": 350},
                "binance_reference_result": {"status": "binance_public_klines_fetch_ready", "candidate_count": 350},
            }
        ],
    }

    ref = build_binance_btc_1h_reference_report(controller_result=controller_result)
    diag = build_cross_source_btc_1h_gap_diagnostic(controller_result=controller_result)

    assert ref["available_reference_count"] == 1
    assert ref["coinbase_cache_mutated_by_binance"] is False
    assert diag["diagnostic_rows"][0]["classification"] == "coinbase_gap_fill_with_secondary_reference_available"
    assert diag["normal_backtest_permission_changed"] is False
