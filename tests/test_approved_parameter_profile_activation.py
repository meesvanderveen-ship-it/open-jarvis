from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.activate_approved_parameter_profile import build_activation_report


def _write_candidate(path: Path, *, safe: bool = True, params: dict[str, str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "profile_name": "cost_aware_bootstrap_conservative",
                        "safe_to_activate_now": safe,
                        # Sizing values must stay within the live 50.00-100.00 USDC
                        # rails (bot/live_order_size_policy.py MIN/MAX_LIVE_ORDER_QUOTE_USDC),
                        # which BotConfig.validate() enforces unconditionally.
                        "parameter_values": params or {
                            "MAX_SPREAD_PCT": "0.0060",
                            "DEFAULT_QUOTE_SIZE_USDC": "55.00",
                            "MAX_NOTIONAL_USD": "90.00",
                            "AUTONOMOUS_MAX_ORDER_QUOTE": "80.00",
                            "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
                            "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
                            "PHASE_C_MAX_ORDER_QUOTE": "70.00",
                            "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "90.00",
                            "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0100",
                            "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
                            "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
                            "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
                        },
                    }
                ]
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_candidate_unsafe_no_activation(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, safe=False)

    report = build_activation_report(candidate_path=candidate, root=tmp_path, apply=False)

    assert "candidate_not_marked_safe_to_activate_now" in report["blockers"]
    assert report["write_performed"] is False


def test_unknown_parameter_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, params={"MAX_SPREAD_PCT": "0.0060", "BAD_KEY": "1"})

    report = build_activation_report(candidate_path=candidate, root=tmp_path, apply=False)

    assert any(x.startswith("unknown_parameter") for x in report["blockers"])


def test_conservative_safe_profile_can_be_written_with_exact_ack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setenv("ENABLE_FULL_WORKFLOW_LIVE_MODE", "true")
    for key in [
        "ENABLE_LIMIT_ORDER_MANAGER",
        "ENABLE_LIVE_LIMIT_ORDERS",
        "ENABLE_LIVE_ENTRY_ORDERS",
        "ENABLE_LIVE_EXIT_ORDERS",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE",
        "AUTONOMOUS_ALLOW_EXITS",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT",
        "PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL",
    ]:
        monkeypatch.setenv(key, "true")
    monkeypatch.setenv("AUTONOMOUS_ENTRY_ONLY_FIRST", "false")
    monkeypatch.setenv("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "false")
    monkeypatch.setenv("LEARNING_TO_EXECUTION_ALLOWED", "false")
    monkeypatch.setenv("LIVE_LEARNING_ALLOWED", "false")
    monkeypatch.setenv("PARAMETER_CHANGE_ALLOWED", "false")
    # ENABLE_FULL_WORKFLOW_LIVE_MODE pins these cycle/order-count fields to
    # exact values regardless of the sizing rails above; not part of the
    # approved-profile whitelist, so they must come from env directly.
    monkeypatch.setenv("PHASE_C_MAX_OPEN_ENTRY_ORDERS", "3")
    monkeypatch.setenv("MAX_NEW_ORDERS_PER_CYCLE", "1")
    monkeypatch.setenv("PHASE_D3_MAX_OPEN_EXIT_ORDERS", "3")
    monkeypatch.setenv("PHASE_D3_RUNTIME_SUBMIT_ACK", "I_UNDERSTAND_AND_APPROVE_D3_CONTROLLED_REDUCE_ONLY_LIVE_EXITS")

    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate, safe=True)
    dry = build_activation_report(candidate_path=candidate, root=tmp_path, apply=False)
    report = build_activation_report(candidate_path=candidate, root=tmp_path, apply=True, ack=dry["required_ack"])

    assert report["write_performed"] is True
    assert report["bot_config_validation"]["status"] == "BOT_CONFIG_VALID"
    assert (tmp_path / "state/approved_parameter_profile.json").exists()
