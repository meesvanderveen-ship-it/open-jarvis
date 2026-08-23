from __future__ import annotations

import json
from types import SimpleNamespace

from bot.neural_feature_schema import PREDICTION_CLASSES, prediction_class_for_sample
from bot.neural_shadow_policy import neural_learning_status_from_config


def _cfg(report_path="reports/live_learning/neural-shadow-policy-latest.json"):
    return SimpleNamespace(
        neural_shadow_policy_enabled=True,
        neural_shadow_policy_training_enabled=True,
        neural_shadow_policy_execution_allowed=False,
        neural_shadow_policy_agreement_required=False,
        neural_shadow_policy_model_path="state/neural_shadow_policy.json",
        neural_shadow_policy_report_path=report_path,
    )


def test_balanced_label_classes_are_available():
    for label in [
        "missed_opportunity",
        "bad_wait",
        "good_wait",
        "good_entry_candidate",
        "bad_entry_candidate",
        "good_probe_candidate",
        "bad_probe_candidate",
        "correct_avoid",
        "false_positive_plan",
        "trigger_ready_but_waited",
        "planner_no_plan_missed_move",
    ]:
        assert label in PREDICTION_CLASSES


def test_missed_waits_can_get_non_prefer_no_trade_labels():
    sample = {
        "decision": "wait",
        "pending_trade_plan": {"trigger_ready": True},
        "reward": {"label": "missed_opportunity", "reward": "1.0"},
    }
    assert prediction_class_for_sample(sample) == "trigger_ready_but_waited"


def test_one_class_prefer_no_trade_report_sets_passivity_warning(tmp_path):
    report_path = tmp_path / "reports/live_learning/neural-shadow-policy-latest.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps({"class_counts": {"prefer_no_trade": 12}, "model_available": True}),
        encoding="utf-8",
    )
    status = neural_learning_status_from_config(_cfg(report_path=str(report_path.relative_to(tmp_path))), root=tmp_path)
    assert status["execution_allowed"] is False
    assert status["one_class_dataset_warning"] is True
    assert status["neural_shadow_one_class_passivity_bias"] is True
    assert "bounded exploration" in status["balanced_label_recommendation"]

