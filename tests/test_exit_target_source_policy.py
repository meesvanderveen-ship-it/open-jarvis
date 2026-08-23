from __future__ import annotations

from types import SimpleNamespace

from bot.exit_target_source_policy import build_exit_target_source_policy_report


def _cfg(**overrides):
    base = {
        "exit_target_max_distance_from_mid_pct": "0.0350",
        "exit_target_allow_far_tp_with_resistance_confirmation": True,
        "exit_target_require_fresh_context_when_stop_breached": True,
        "exit_target_stale_if_stop_breached": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_policy_prefers_fresh_market_context_target() -> None:
    report = build_exit_target_source_policy_report(
        cfg=_cfg(),
        position={"ticker": "BTC-USDC", "entry_price": "67503.96", "take_profit_price": "71554.19"},
        market_context={"current_price": "69000", "tp1_price": "70000", "nearest_resistance": "70050"},
    )

    assert report["target_price"] == "70000"
    assert report["target_source"] == "gpt_market_context_exit_target"
    assert report["used_market_context"] is True
    assert report["is_stale_target"] is False


def test_stop_breach_marks_stored_far_tp_as_stale_exit_above_market() -> None:
    report = build_exit_target_source_policy_report(
        cfg=_cfg(),
        position={"ticker": "BTC-USDC", "entry_price": "67503.96", "take_profit_price": "71554.19"},
        market_context={"current_price": "65400", "reasons": ["stop_breached_or_below_invalidation"]},
    )

    assert report["target_source"] == "position_take_profit_price"
    assert report["is_stop_or_risk_exit"] is True
    assert report["is_stale_target"] is True
    assert report["target_reason"] in {"stale_exit_above_market", "stop_breached_requires_fresh_context"}


def test_risk_reward_default_target_is_last_fallback_and_reported() -> None:
    report = build_exit_target_source_policy_report(
        cfg=_cfg(),
        position={"ticker": "BTC-USDC", "entry_price": "67503.96"},
        market_context={"current_price": "67500"},
        risk_reward_fallback_target="71554.19",
    )

    assert report["target_source"] == "risk_reward_default_target"
    assert report["used_risk_reward_fallback"] is True
    assert report["target_reason"] in {"stored_risk_reward_default_target", "target_far_from_mid_without_resistance_confirmation"}
