from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.run_cost_aware_backlearning import build_cost_aware_backlearning_report, main


def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EXECUTION_MODE", "paper")
    monkeypatch.setenv("ENABLE_APPROVED_PARAMETER_PROFILE", "false")


def test_backlearning_uses_local_files_only_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/execution_outcomes.jsonl").write_text(
        json.dumps({"primary_label": "missed_fill_opportunity", "labels": ["missed_fill_opportunity"]}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "state/decision_outcomes.json").write_text(json.dumps({"outcomes": [{"ticker": "BTC-USDC"}]}), encoding="utf-8")

    report = build_cost_aware_backlearning_report(root=tmp_path)

    assert report["local_only"] is True
    assert report["coinbase_call_attempted"] is False
    assert report["llm_call_attempted"] is False
    assert report["candidates"][0]["safe_to_activate_now"] is True
    assert set(report["candidates"][0]["parameter_values"]).issubset({
        "MAX_SPREAD_PCT",
        "DEFAULT_QUOTE_SIZE_USDC",
        "MAX_NOTIONAL_USD",
        "AUTONOMOUS_MAX_ORDER_QUOTE",
        "AUTONOMOUS_MAX_OPEN_ORDERS",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE",
        "PHASE_C_MAX_ORDER_QUOTE",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE",
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
    })


def test_backlearning_rejects_fetch_or_llm_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["--allow-bounded-fetch"])
    with pytest.raises(SystemExit):
        main(["--allow-llm-summary"])
