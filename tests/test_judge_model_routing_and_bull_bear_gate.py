"""Regression tests for OpenAI-only model routing and the deterministic
bull/bear/confidence fail-closed gate on the final judge's approve_trade output.

Context: JUDGE_MIN_BULL_SCORE / JUDGE_MAX_BEAR_SCORE / JUDGE_MIN_SYNTH_CONFIDENCE
were previously consulted only inside _should_call_expensive_judge (whether to
*call* the expensive judge at all) and never re-checked against the judge's own
approve_trade output. _enforce_bull_bear_confidence_gate (bot/strategy_engine.py)
closes that gap: it forces decision=wait whenever an approve_trade/BUY judge
output violates these thresholds, regardless of how the judge call was reached.
"""

from __future__ import annotations

import importlib.util
import sys
import types

# StrategyEngine imports bot.llm_clients at module import time, which imports
# the openai/anthropic SDKs. The test sandbox does not install them.
def _real_module_available(name: str) -> bool:
    """True als de echte module geinstalleerd is.

    De stubs in dit bestand bestaan zodat de test ook draait zonder de zware
    optionele pakketten. De oude conditie keek naar sys.modules, maar dat is
    bij het eerste gebruik altijd leeg -- ook als de echte module wel
    geinstalleerd is. De stub verdrong dan de echte module voor de rest van
    de sessie, waardoor latere tests over pytest.approx struikelden
    ("module 'numpy' has no attribute 'isscalar'").
    """
    if name in sys.modules:
        return True
    return importlib.util.find_spec(name) is not None


if not _real_module_available("openai"):
    openai_stub = types.ModuleType("openai")

    class OpenAI:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    openai_stub.OpenAI = OpenAI
    sys.modules["openai"] = openai_stub

if not _real_module_available("anthropic"):
    anthropic_stub = types.ModuleType("anthropic")

    class Anthropic:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    anthropic_stub.Anthropic = Anthropic
    sys.modules["anthropic"] = anthropic_stub

if not _real_module_available("pandas"):
    pandas_stub = types.ModuleType("pandas")
    pandas_stub.DataFrame = object
    pandas_stub.Series = object
    pandas_stub.concat = lambda *args, **kwargs: []
    pandas_stub.isna = lambda value: value is None
    sys.modules["pandas"] = pandas_stub

if not _real_module_available("numpy"):
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.nan = float("nan")
    numpy_stub.arange = lambda *args, **kwargs: []
    numpy_stub.polyfit = lambda *args, **kwargs: [0]
    sys.modules["numpy"] = numpy_stub

from bot.config import BotConfig
from bot.strategy_engine import DEFAULT_JUDGE_MODEL, StrategyEngine


def _engine(cfg):
    e = StrategyEngine.__new__(StrategyEngine)
    e.cfg = cfg
    return e


def _cfg(**overrides):
    base = dict(
        judge_min_bull_score=56,
        judge_max_bear_score=72,
        judge_min_synth_confidence=60,
        openai_judge_model="gpt-5.5",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _judge_input(bull_score, bear_score, synth_conf):
    return {
        "bull": {"bull_case_score": bull_score},
        "bear": {"bear_case_score": bear_score},
        "synth": {"composite_confidence": synth_conf},
    }


# ---------------------------------------------------------------------------
# OpenAI-only model routing
# ---------------------------------------------------------------------------

def test_judge_model_is_fully_driven_by_env_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("OPENAI_JUDGE_MODEL", "gpt-5.4-mini")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = BotConfig()
    assert cfg.openai_judge_model == "gpt-5.4-mini"

    # This mirrors the exact expression StrategyEngine.__init__ uses to set
    # self.judge_model -- no call site overrides it with a hardcoded model.
    resolved = getattr(cfg, "openai_judge_model", DEFAULT_JUDGE_MODEL) or DEFAULT_JUDGE_MODEL
    assert resolved == "gpt-5.4-mini"


def test_judge_model_defaults_to_gpt_5_5_only_when_env_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.delenv("OPENAI_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = BotConfig()
    assert cfg.openai_judge_model == "gpt-5.5" == DEFAULT_JUDGE_MODEL


def test_no_active_deepseek_runtime_route_by_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.delenv("ENABLE_DEEPSEEK_PREPROCESS", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = BotConfig()
    assert cfg.enable_deepseek_preprocess is False
    cfg.validate()  # must not require DEEPSEEK_API_KEY when disabled


def test_cheaper_judge_model_changes_only_model_not_risk_thresholds(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    monkeypatch.setenv("OPENAI_JUDGE_MODEL", "gpt-5.5")
    cfg_expensive = BotConfig()

    monkeypatch.setenv("OPENAI_JUDGE_MODEL", "gpt-5.4-mini")
    cfg_cheap = BotConfig()

    assert cfg_expensive.openai_judge_model != cfg_cheap.openai_judge_model
    assert cfg_expensive.judge_min_bull_score == cfg_cheap.judge_min_bull_score
    assert cfg_expensive.judge_max_bear_score == cfg_cheap.judge_max_bear_score
    assert cfg_expensive.judge_min_synth_confidence == cfg_cheap.judge_min_synth_confidence

    # The deterministic gate's verdict is identical regardless of which judge
    # model produced the decision -- only the score thresholds matter.
    judge_input = _judge_input(bull_score=50, bear_score=80, synth_conf=50)
    judge_expensive = {"decision": "approve_trade", "side": "BUY"}
    judge_cheap = {"decision": "approve_trade", "side": "BUY"}

    e_expensive = _engine(cfg_expensive)
    e_cheap = _engine(cfg_cheap)
    out_expensive = StrategyEngine._enforce_bull_bear_confidence_gate(e_expensive, judge_expensive, judge_input)
    out_cheap = StrategyEngine._enforce_bull_bear_confidence_gate(e_cheap, judge_cheap, judge_input)

    assert out_expensive["decision"] == out_cheap["decision"] == "wait"


# ---------------------------------------------------------------------------
# Bull/bear/confidence deterministic fail-closed gate
# ---------------------------------------------------------------------------

def test_bull_score_below_min_blocks_approve_trade():
    e = _engine(_cfg())
    judge = {"decision": "approve_trade", "side": "BUY", "size_quote": 25.0, "reasons": []}
    judge_input = _judge_input(bull_score=55, bear_score=30, synth_conf=70)  # bull < 56

    out = StrategyEngine._enforce_bull_bear_confidence_gate(e, judge, judge_input)

    assert out["decision"] == "wait"
    assert out["side"] == "NONE"
    assert out["size_quote"] == 0.0
    assert any("bull_score_below_min" in r for r in out["reasons"])


def test_bull_score_at_or_above_min_is_not_blocked_on_that_basis():
    e = _engine(_cfg())
    judge = {"decision": "approve_trade", "side": "BUY", "size_quote": 25.0, "reasons": []}
    judge_input = _judge_input(bull_score=56, bear_score=30, synth_conf=70)  # bull == min

    out = StrategyEngine._enforce_bull_bear_confidence_gate(e, judge, judge_input)

    assert out["decision"] == "approve_trade"
    assert out["side"] == "BUY"


def test_bear_score_above_max_blocks_approve_trade_even_with_strong_bull():
    e = _engine(_cfg())
    judge = {"decision": "approve_trade", "side": "BUY", "size_quote": 25.0, "reasons": []}
    judge_input = _judge_input(bull_score=90, bear_score=73, synth_conf=80)  # bear > 72

    out = StrategyEngine._enforce_bull_bear_confidence_gate(e, judge, judge_input)

    assert out["decision"] == "wait"
    assert any("bear_score_above_max" in r for r in out["reasons"])


def test_bear_score_at_or_below_max_is_not_blocked_on_that_basis():
    e = _engine(_cfg())
    judge = {"decision": "approve_trade", "side": "BUY", "size_quote": 25.0, "reasons": []}
    judge_input = _judge_input(bull_score=90, bear_score=72, synth_conf=80)  # bear == max

    out = StrategyEngine._enforce_bull_bear_confidence_gate(e, judge, judge_input)

    assert out["decision"] == "approve_trade"


def test_synth_confidence_below_min_blocks_approve_trade():
    e = _engine(_cfg())
    judge = {"decision": "approve_trade", "side": "BUY", "size_quote": 25.0, "reasons": []}
    judge_input = _judge_input(bull_score=90, bear_score=10, synth_conf=59)  # synth < 60

    out = StrategyEngine._enforce_bull_bear_confidence_gate(e, judge, judge_input)

    assert out["decision"] == "wait"
    assert any("synth_confidence_below_min" in r for r in out["reasons"])


def test_all_thresholds_satisfied_leaves_approve_trade_untouched():
    e = _engine(_cfg())
    judge = {"decision": "approve_trade", "side": "BUY", "size_quote": 25.0, "reasons": ["ok"]}
    judge_input = _judge_input(bull_score=70, bear_score=20, synth_conf=75)

    out = StrategyEngine._enforce_bull_bear_confidence_gate(e, judge, judge_input)

    assert out["decision"] == "approve_trade"
    assert out["side"] == "BUY"
    assert out["size_quote"] == 25.0
    assert out["reasons"] == ["ok"]


def test_gate_ignores_non_buy_decisions():
    e = _engine(_cfg())
    for decision, side in (("wait", "NONE"), ("reduce_size", "SELL"), ("close_position", "SELL")):
        judge = {"decision": decision, "side": side, "size_quote": 0.0, "reasons": []}
        judge_input = _judge_input(bull_score=10, bear_score=95, synth_conf=10)  # would violate every threshold
        out = StrategyEngine._enforce_bull_bear_confidence_gate(e, judge, judge_input)
        assert out["decision"] == decision
        assert out["side"] == side


def test_higher_bull_score_is_strictly_more_permissive():
    """Directional sanity check: raising bull_score alone can only relax the
    gate, never tighten it (holding bear/synth fixed at passing values)."""
    e = _engine(_cfg())
    low_bull = StrategyEngine._enforce_bull_bear_confidence_gate(
        e,
        {"decision": "approve_trade", "side": "BUY", "size_quote": 1.0, "reasons": []},
        _judge_input(bull_score=40, bear_score=20, synth_conf=75),
    )
    high_bull = StrategyEngine._enforce_bull_bear_confidence_gate(
        e,
        {"decision": "approve_trade", "side": "BUY", "size_quote": 1.0, "reasons": []},
        _judge_input(bull_score=90, bear_score=20, synth_conf=75),
    )
    assert low_bull["decision"] == "wait"
    assert high_bull["decision"] == "approve_trade"


def test_higher_bear_score_is_strictly_more_restrictive():
    """Directional sanity check: raising bear_score alone can only tighten the
    gate, never relax it (holding bull/synth fixed at passing values)."""
    e = _engine(_cfg())
    low_bear = StrategyEngine._enforce_bull_bear_confidence_gate(
        e,
        {"decision": "approve_trade", "side": "BUY", "size_quote": 1.0, "reasons": []},
        _judge_input(bull_score=80, bear_score=20, synth_conf=75),
    )
    high_bear = StrategyEngine._enforce_bull_bear_confidence_gate(
        e,
        {"decision": "approve_trade", "side": "BUY", "size_quote": 1.0, "reasons": []},
        _judge_input(bull_score=80, bear_score=90, synth_conf=75),
    )
    assert low_bear["decision"] == "approve_trade"
    assert high_bear["decision"] == "wait"
