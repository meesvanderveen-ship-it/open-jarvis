from __future__ import annotations

from bot.neural_reward_model import calculate_neural_reward


def test_reward_model_labels_missed_opportunity() -> None:
    result = calculate_neural_reward({
        "features": {"spread_pct": 0.001},
        "action_taken": "wait",
        "outcome": {"filled": False, "missed_opportunity": True, "max_favorable_move_pct": 0.03},
    })
    assert result.label == "missed_opportunity"
    assert result.reward < 0


def test_reward_model_labels_adverse_move_after_entry() -> None:
    result = calculate_neural_reward({
        "features": {"spread_pct": 0.001},
        "action_taken": "place_limit_buy",
        "outcome": {"filled": True, "adverse_move": True, "max_adverse_move_pct": 0.03},
    })
    assert result.label == "adverse_after_entry"
    assert result.reward == -1.0


def test_reward_model_labels_correct_wait() -> None:
    result = calculate_neural_reward({
        "features": {"spread_pct": 0.001},
        "action_taken": "wait",
        "outcome": {"filled": False, "missed_opportunity": False, "adverse_move": True},
    })
    assert result.label == "correct_wait_avoided_adverse"
    assert result.reward > 0
