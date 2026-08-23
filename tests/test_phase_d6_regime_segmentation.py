from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_regime_segmentation import build_phase_d6_regime_segmentation_report


def _candle(index: int, close: float, product: str = "BTC-USDC"):
    return {
        "product_id": product,
        "timeframe": "1D",
        "start": index * 86400,
        "open": str(close),
        "high": str(close * 1.01),
        "low": str(close * 0.99),
        "close": str(close),
        "volume": "10",
    }


def _write(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False
    assert report["human_review_required"] is True
    assert report["parameter_review_approved"] is False


def test_regime_segmentation_labels_local_candle_windows(tmp_path: Path):
    rows = [_candle(i, 100 + i * 2) for i in range(30)]
    path = _write(tmp_path / "research" / "btc.json", rows)

    report = build_phase_d6_regime_segmentation_report(candle_path=path, window_size=10, step_size=10)

    assert report["status"] == "d6_regime_segmentation_ready"
    assert report["product_id"] == "BTC-USDC"
    assert report["regime_window_count"] == 3
    assert report["regime_counts"]["uptrend"] >= 1
    assert all(row["contains_live_signal"] is False for row in report["window_rows"])
    assert report["usable_for_future_research"] is True
    _assert_safe(report)


def test_regime_segmentation_blocks_invalid_dataset(tmp_path: Path):
    path = _write(tmp_path / "research" / "bad.json", [{"start": 1, "close": "100"}])
    report = build_phase_d6_regime_segmentation_report(candle_path=path, window_size=2, step_size=1)

    assert report["status"] == "d6_regime_segmentation_blocked"
    assert "missing_required_candle_fields" in report["blockers"]
    assert report["usable_for_future_research"] is False
    _assert_safe(report)


def test_regime_segmentation_refuses_state_paths(tmp_path: Path):
    path = _write(tmp_path / "state" / "candles.json", [_candle(0, 100), _candle(1, 101)])
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_regime_segmentation_report(candle_path=path, window_size=2, step_size=1)


def test_cli_stdout_only(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    path = _write(tmp_path / "research" / "btc.json", [_candle(i, 100 + i) for i in range(12)])

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_regime_segmentation.py",
            "--candles",
            str(path),
            "--window-size",
            "6",
            "--step-size",
            "6",
            "--json",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["regime_window_count"] == 2
    _assert_safe(report)
