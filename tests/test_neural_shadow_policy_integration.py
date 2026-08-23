from __future__ import annotations

from pathlib import Path

import pytest

from bot.config import BotConfig
from bot.neural_shadow_policy import MODEL_VERSION, build_shadow_context


def test_prediction_soft_context_shape_for_decision_context() -> None:
    feature_pack = {"decision_context": {}, "risk_context": {}, "market": {}}
    feature_pack["decision_context"]["neural_shadow_policy"] = build_shadow_context(
        feature_pack,
        ticker="BTC-USDC",
        model_path="missing.json",
    )
    ctx = feature_pack["decision_context"]["neural_shadow_policy"]
    assert ctx["enabled"] is True
    assert ctx["execution_allowed"] is False
    assert ctx["model_available"] is False


def test_neural_execution_allowed_true_blocked_in_full_workflow_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ENABLE_APPROVED_PARAMETER_PROFILE", "false")
    monkeypatch.setenv("NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED", "true")
    cfg = BotConfig()
    with pytest.raises(ValueError, match="NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED"):
        cfg.validate()


def test_strategy_engine_scan_hook_injects_shadow_context() -> None:
    source = Path("bot/strategy_engine.py").read_text(encoding="utf-8")
    scan_body = source[source.index("    def _scan_market_universe("):source.index("    def _suppress_repeated_partial_take_profit_action(")]
    assert "feature_pack = self._inject_neural_shadow_context(ticker, feature_pack)" in scan_body


def test_one_class_neural_policy_is_diagnostic_only_and_cannot_block_planner_or_judge(tmp_path: Path) -> None:
    model_path = tmp_path / "one-class.json"
    model_path.write_text(
        """
{
  "model_version": "neural_shadow_policy_v1",
  "status": "trained_shadow_only",
  "execution_allowed": false,
  "trained_at": "2026-06-14T00:00:00Z",
  "class_counts": {"prefer_no_trade": 10},
  "centroids": {},
  "categories": {},
  "sample_count": 10,
  "one_class_dataset_warning": true
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    ctx = build_shadow_context({"market": {}}, ticker="BTC-USDC", model_path=model_path)

    assert ctx["model_version"] == MODEL_VERSION
    assert ctx["prediction"] == "prefer_no_trade"
    assert ctx["confidence"] == 0.10
    assert ctx["diagnostic_only"] is True
    assert ctx["can_block_planner"] is False
    assert ctx["can_block_judge"] is False
    assert ctx["can_authorize_execution"] is False
    assert ctx["execution_allowed"] is False
