from __future__ import annotations

import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.approved_parameter_profile import load_approved_parameter_profile, sha256_file
from bot.config import BotConfig


def _base_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "OPENAI_API_KEY": "test-key",
        "EXECUTION_MODE": "paper",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE": "false",
        "ENABLE_LIVE_ENTRY_ORDERS": "false",
        "ENABLE_LIVE_LIMIT_ORDERS": "false",
        "ENABLE_LIVE_EXIT_ORDERS": "false",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "false",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "false",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": "false",
        "ENABLE_LIMIT_ORDER_MANAGER": "false",
        "AUTONOMOUS_ALLOW_EXITS": "false",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "false",
    }
    env.update(extra or {})
    return env


def _write_profile(root: Path, payload: dict[str, object]) -> Path:
    path = root / "state/approved_parameter_profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_profile_disabled_skips_without_reading_missing_file(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    result = load_approved_parameter_profile(path=tmp_path / "state/approved_parameter_profile.json", env=_base_env())
    assert result.status == "skipped"
    assert result.values == {}
    assert "skipped" in caplog.text


def test_hash_mismatch_rejected(tmp_path: Path) -> None:
    # A rejection must never raise: BotConfig() calls this unguarded in
    # __post_init__, so an uncaught exception here takes down the whole bot
    # (including live position monitoring/exits) over an optional, whitelisted
    # profile layer that already has working .env fallback values. Confirmed
    # live 2026-07-08: the autonomous_parameter_governor updated the profile
    # without anyone syncing .env's pinned hash (nothing does that
    # automatically -- that hash is supposed to represent a human approving
    # the governor's own proposed change), and the very next unrelated
    # restart crash-looped indefinitely instead of just running on baseline
    # .env values, leaving an open, stop-breached position unmonitored.
    path = _write_profile(tmp_path, {"MAX_SPREAD_PCT": "0.0100"})
    env = _base_env({
        "ENABLE_APPROVED_PARAMETER_PROFILE": "true",
        "APPROVED_PARAMETER_PROFILE_HASH": "0" * 64,
    })
    result = load_approved_parameter_profile(path=path, env=env)
    assert result.status == "rejected"
    assert result.reason == "hash_mismatch"
    assert result.values == {}


def test_unknown_key_rejected(tmp_path: Path) -> None:
    path = _write_profile(tmp_path, {"MAX_SPREAD_PCT": "0.0100", "ENABLE_LIVE_EXIT_ORDERS": "true"})
    env = _base_env({
        "ENABLE_APPROVED_PARAMETER_PROFILE": "true",
        "APPROVED_PARAMETER_PROFILE_HASH": sha256_file(path),
    })
    result = load_approved_parameter_profile(path=path, env=env)
    assert result.status == "rejected"
    assert result.reason.startswith("unknown_keys:")
    assert "ENABLE_LIVE_EXIT_ORDERS" in result.reason
    assert result.values == {}


def test_config_falls_back_gracefully_instead_of_crashing_on_rejected_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The critical end-to-end guarantee: BotConfig() itself must not raise when
    # the profile is rejected -- it must silently fall back to plain .env
    # values, exactly like it does for the "disabled" case.
    path = _write_profile(tmp_path, {"MAX_SPREAD_PCT": "0.0100"})
    monkeypatch.chdir(tmp_path)
    env = _base_env({
        "ENABLE_APPROVED_PARAMETER_PROFILE": "true",
        "APPROVED_PARAMETER_PROFILE_HASH": "0" * 64,
        "MAX_SPREAD_PCT": "0.0060",
    })
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    cfg = BotConfig()
    assert str(cfg.max_spread_pct) == "0.0060"


def test_allowed_profile_loaded_and_applied_to_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Sizing values must stay within the live 50.00-100.00 USDC rails
    # (bot/live_order_size_policy.py MIN/MAX_LIVE_ORDER_QUOTE_USDC), which
    # BotConfig.validate() enforces unconditionally, including in paper mode.
    path = _write_profile(
        tmp_path,
        {
            "parameters": {
                "MAX_SPREAD_PCT": "0.0200",
                "DEFAULT_QUOTE_SIZE_USDC": "55.00",
                    "MAX_NOTIONAL_USD": "90.00",
                    "AUTONOMOUS_MAX_ORDER_QUOTE": "80.00",
                    "PHASE_C_MAX_ORDER_QUOTE": "70.00",
                    "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "90.00",
                    "AUTONOMOUS_MAX_OPEN_ORDERS": "2",
                "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
                "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0150",
                "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "4.0",
                "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "2.0",
                "STOP_DISTANCE_PCT": "0.0250",
            }
        },
    )
    monkeypatch.chdir(tmp_path)
    for key, value in _base_env({
        "ENABLE_APPROVED_PARAMETER_PROFILE": "true",
        "APPROVED_PARAMETER_PROFILE_HASH": sha256_file(path),
    }).items():
        monkeypatch.setenv(key, value)
    cfg = BotConfig()
    assert cfg.max_spread_pct == Decimal("0.0200")
    assert cfg.default_quote_size_usdc == Decimal("55.00")
    assert cfg.max_notional_usd == Decimal("90.00")
    assert cfg.autonomous_max_order_quote == Decimal("80.00")
    assert cfg.autonomous_max_open_orders == 2
    assert cfg.phase_d2_min_reward_to_risk_ratio == Decimal("2.0")
    assert cfg.stop_distance_pct == Decimal("0.0250")
    cfg.validate()


def test_max_open_positions_and_small_probe_params_apply_via_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: MAX_OPEN_POSITIONS was whitelisted but never mapped in
    BotConfig.__post_init__, making it a silent no-op via the approved-profile
    route (only .env had effect). Fixed 2026-07-02 alongside the new
    SMALL_PROBE_* governance wiring -- both must now actually apply."""
    path = _write_profile(
        tmp_path,
        {
            "parameters": {
                "MAX_OPEN_POSITIONS": "5",
                "SMALL_PROBE_MAX_BEAR_BULL_GAP": "20",
                "SMALL_PROBE_REQUIRE_HTF_BOTH_TIMEFRAMES": "false",
                "SMALL_PROBE_TC_BULL_MIN": "60",
                "SMALL_PROBE_TC_VOL_15M_MIN": "0.70",
            }
        },
    )
    monkeypatch.chdir(tmp_path)
    for key, value in _base_env({
        "ENABLE_APPROVED_PARAMETER_PROFILE": "true",
        "APPROVED_PARAMETER_PROFILE_HASH": sha256_file(path),
    }).items():
        monkeypatch.setenv(key, value)
    cfg = BotConfig()
    assert cfg.max_open_positions == 5
    assert cfg.small_probe_max_bear_bull_gap == 20
    assert cfg.small_probe_require_htf_both_timeframes is False
    assert cfg.small_probe_tc_bull_min == 60
    assert cfg.small_probe_tc_vol_15m_min == Decimal("0.70")
    cfg.validate()


def test_recent_market_active_probe_candidate_keys_are_all_whitelisted() -> None:
    """The Phase 6 candidate profile artifact must only reference governable
    (whitelisted) parameters, so it could actually be activated through the
    existing approved-profile route without an unknown-key rejection."""
    from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST

    root = Path(__file__).resolve().parents[1]
    candidate_path = root / "config/parameter_profiles/recent_market_active_probe_candidate.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    keys = set(payload["parameter_changes"].keys())
    unknown = keys - APPROVED_PARAMETER_PROFILE_WHITELIST
    assert not unknown, f"candidate profile references non-whitelisted keys: {sorted(unknown)}"
