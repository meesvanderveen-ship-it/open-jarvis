from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.neural_shadow_policy import (
    build_shadow_context,
    load_shadow_model,
    train_shadow_policy,
    validate_parameter_suggestions,
)


def _sample(i: int, target: str = "prefer_no_trade") -> dict:
    return {
        "sample_id": f"s{i}",
        "ticker": "BTC-USDC",
        "features": {
            "gate": "watch",
            "gate_confidence": 50 + i,
            "judge_decision": "wait",
            "setup_type": "range",
            "pending_trigger_ready": False,
            "spread_pct": 0.001,
            "ema_4h_alignment": -1,
            "ema_1d_alignment": -1,
            "learning_context_classification": "WATCH",
        },
        "outcome": {"filled": False},
        "reward": 0.25,
        "target_class": target,
    }


def test_training_with_insufficient_samples_is_shadow_only(tmp_path: Path) -> None:
    report = train_shadow_policy([_sample(1)], model_out=tmp_path / "state/model.json", report_out=tmp_path / "report.json", min_samples=50)
    model = load_shadow_model(tmp_path / "state/model.json")
    assert report["status"] == "insufficient_samples_shadow_only"
    assert model["execution_allowed"] is False


def test_model_prediction_builds_soft_context(tmp_path: Path) -> None:
    model_path = tmp_path / "state/model.json"
    train_shadow_policy([_sample(i) for i in range(3)], model_out=model_path, report_out=tmp_path / "report.json", min_samples=1)
    ctx = build_shadow_context(
        {"features": _sample(1)["features"]},
        ticker="BTC-USDC",
        model_path=model_path,
        min_confidence=0.1,
    )
    assert ctx["enabled"] is True
    assert ctx["execution_allowed"] is False
    assert ctx["model_available"] is True
    assert ctx["prediction"] in {"prefer_no_trade", "wait", "watch", "analyze"}


def test_corrupt_or_missing_model_does_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{bad", encoding="utf-8")
    ctx = build_shadow_context({}, ticker="BTC-USDC", model_path=path)
    assert ctx["model_available"] is False
    assert ctx["execution_allowed"] is False


def test_unknown_suggested_parameter_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_parameter_suggestions({"UNKNOWN_PARAMETER": {"suggested": "1"}})
