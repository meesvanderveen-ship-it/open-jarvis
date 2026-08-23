"""Regression tests for _maybe_promote_wait_to_small_probe (bot/strategy_engine.py).

Context (2026-07-02): a 72h audit of logs/analysis.jsonl across 8 tickers, all
trending +1.8%..+8.3%, found 144/144 judge decisions were "wait" and the small-probe
promotion path fired 0/64 times on valid prepare_breakout/prepare_reclaim plans.
Root cause: the promotion gate's mixed_context veto (bear_score >= max(40, bull-4))
was true on 64/64 candidates (analyst bear-case scores run structurally ~29pts
above bull-case scores even while price rose), and the HTF filter used OR semantics
so a lagging 4h EMA50/EMA200 cross alone (normal early in a fresh reversal) blocked
46/64 candidates that had a bullish 1h structure. See reports/audits/entry-funnel-72h-latest.md
and reports/backtests/recent-market-parameter-sweetspot-latest.md for full evidence.
"""
from __future__ import annotations

import sys
import types
from decimal import Decimal

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class OpenAI:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    openai_stub.OpenAI = OpenAI
    sys.modules["openai"] = openai_stub

if "anthropic" not in sys.modules:
    anthropic_stub = types.ModuleType("anthropic")

    class Anthropic:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    anthropic_stub.Anthropic = Anthropic
    sys.modules["anthropic"] = anthropic_stub

if "pandas" not in sys.modules:
    pandas_stub = types.ModuleType("pandas")
    pandas_stub.DataFrame = object
    pandas_stub.Series = object
    pandas_stub.concat = lambda *args, **kwargs: []
    pandas_stub.isna = lambda value: value is None
    sys.modules["pandas"] = pandas_stub

if "numpy" not in sys.modules:
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.nan = float("nan")
    numpy_stub.arange = lambda *args, **kwargs: []
    numpy_stub.polyfit = lambda *args, **kwargs: [0]
    sys.modules["numpy"] = numpy_stub

from bot.strategy_engine import StrategyEngine

DEFAULT_SMALL_PROBE_CFG = dict(
    small_probe_max_bear_bull_gap=32,
    small_probe_require_htf_both_timeframes=True,
    small_probe_tc_synth_min=68,
    small_probe_tc_bull_min=55,
    small_probe_tc_breakout_confirmation_min=42,
    small_probe_tc_vol_15m_min=Decimal("0.55"),
    small_probe_tc_vol_1h_min=Decimal("0.45"),
    small_probe_rc_synth_min=65,
    small_probe_rc_bull_min=52,
    small_probe_rc_breakout_confirmation_min=36,
    small_probe_rc_vol_15m_min=Decimal("0.50"),
    small_probe_rc_vol_1h_min=Decimal("0.40"),
)


def _engine(**cfg_overrides):
    e = StrategyEngine.__new__(StrategyEngine)
    base = dict(DEFAULT_SMALL_PROBE_CFG)
    base.update(cfg_overrides)
    e.cfg = types.SimpleNamespace(**base)
    e.min_trade_quote_usdc = Decimal("50.00")
    e.max_trade_quote_usdc = Decimal("100.00")
    return e


def _trade_plan(action="prepare_breakout", trigger=79.0):
    return {
        "plan_action": action,
        "side": "BUY",
        "ticker": "SOL-USDC",
        "setup_type": "breakout_retest",
        "entry_zone_low": trigger - 0.1,
        "entry_zone_high": trigger + 0.2,
        "trigger_price": trigger,
        "do_not_chase_above": trigger + 0.2,
        "invalidation_price": trigger - 2.0,
        "stop_loss_price": trigger - 2.0,
        "take_profit_1": trigger + 2.0,
        "max_quote_size": 25.0,
        "planner_confidence": 60,
    }


def _wait_judge():
    return {
        "decision": "wait",
        "side": "NONE",
        "size_quote": 0.0,
        "reasons": ["waiting for trigger confirmation"],
    }


def _judge_input(
    *,
    setup_type="trend_continuation",
    bull_score=61,
    bear_score=67,
    synth_conf=70,
    breakout_confirmation=55,
    vol_15m=1.2,
    vol_1h=1.0,
    rsi_1h=60.0,
    rsi_4h=55.0,
    close_1h=78.6,
    ema20_1h=76.9,
    ema50_1h=75.5,
    ema50_4h=73.5,
    ema200_4h=72.8,
    higher_lows_1h=True,
    higher_highs_1h=False,
    lower_highs_1h=False,
    lower_lows_1h=False,
    compression_detected=False,
    close_15m=78.6,
    ema20_15m=77.0,
    bb_mid_1h=76.8,
    trade_plan=None,
    entry_gate_decision="analyze",
    spread_pct=0.0001,
    max_spread_pct=0.006,
    available_quote=200.0,
):
    return {
        "feature_pack": {
            "ticker": "SOL-USDC",
            "market": {
                "spread_pct": spread_pct,
                "max_spread_pct": max_spread_pct,
                "trading_disabled": False,
                "cancel_only": False,
            },
            "risk_context": {
                "available_quote_balance": available_quote,
                "engine_state": {"cooldown_active": False},
            },
            "entry_gate": {"decision": entry_gate_decision, "setup_type": setup_type},
            "microstructure": {
                "15m": {"volume_vs_avg": vol_15m},
                "1h": {"volume_vs_avg": vol_1h},
            },
            "indicators": {
                "15m": {"close": close_15m, "ema_20": ema20_15m},
                "1h": {
                    "close": close_1h,
                    "ema_20": ema20_1h,
                    "ema_50": ema50_1h,
                    "rsi_14": rsi_1h,
                    "bb_mid": bb_mid_1h,
                },
                "4h": {"rsi_14": rsi_4h, "ema_50": ema50_4h, "ema_200": ema200_4h},
            },
            "structure": {
                "higher_lows_1h": higher_lows_1h,
                "higher_highs_1h": higher_highs_1h,
                "lower_highs_1h": lower_highs_1h,
                "lower_lows_1h": lower_lows_1h,
                "compression_detected": compression_detected,
            },
        },
        "trade_plan": trade_plan or _trade_plan(),
        "synth": {"composite_confidence": synth_conf},
        "bull": {"bull_case_score": bull_score},
        "bear": {"bear_case_score": bear_score},
        "breakout": {"breakout_confirmation_score": breakout_confirmation},
    }


# ---------------------------------------------------------------------------
# Core regression: a realistic strong-uptrend candidate must now promote
# ---------------------------------------------------------------------------

def test_strong_trend_continuation_setup_promotes_to_small_probe():
    """This mirrors a real live record class (72h audit): valid prepare_breakout
    plan, moderately bullish analyst scores, bearish-lagging 4h EMA only (1h bullish).
    Under the pre-fix thresholds this NEVER promoted (0/64 in 72h live). It must now."""
    e = _engine()
    judge_input = _judge_input(
        setup_type="trend_continuation",
        bull_score=60,
        bear_score=70,        # gap=10, well under the new 32 threshold
        synth_conf=72,
        breakout_confirmation=50,
        vol_15m=1.1,
        vol_1h=0.9,
        ema50_4h=73.0,
        ema200_4h=74.0,       # 4h EMA50 < EMA200: lagging-only bearish leg
        ema20_1h=76.9,
        ema50_1h=75.5,        # 1h EMA20 > EMA50: bullish leg -> AND-gate passes
        close_1h=78.6,
    )
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "approve_trade"
    assert result["side"] == "BUY"
    assert result["valid_trade_plan"] is True
    assert result["size_quote"] > 0
    assert "wait_upgraded_to_small_probe_based_on_tactical_setup" in result["reasons"]


def test_reclaim_setup_promotes_when_near_ema_and_holding_mid():
    e = _engine()
    judge_input = _judge_input(
        setup_type="reclaim_reversal",
        trade_plan=_trade_plan(action="prepare_reclaim", trigger=77.0),
        bull_score=56,
        bear_score=68,
        synth_conf=68,
        breakout_confirmation=40,
        vol_15m=0.7,
        vol_1h=0.6,
        close_15m=77.0,
        ema20_15m=77.05,
        close_1h=77.0,
        bb_mid_1h=76.5,
        ema50_4h=73.0,
        ema200_4h=74.0,
        ema20_1h=76.9,
        ema50_1h=75.5,
    )
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "approve_trade"


# ---------------------------------------------------------------------------
# Still-blocked cases: genuinely weak/bearish setups must not promote
# ---------------------------------------------------------------------------

def test_genuinely_bearish_setup_still_blocked_by_htf_when_both_timeframes_agree():
    e = _engine()
    judge_input = _judge_input(
        bull_score=60, bear_score=70, synth_conf=72, breakout_confirmation=50,
        vol_15m=1.1, vol_1h=0.9,
        ema50_4h=73.0, ema200_4h=74.0,   # 4h bearish
        ema20_1h=74.0, ema50_1h=75.5,    # 1h ALSO bearish -> AND-gate blocks
        close_1h=78.6,
    )
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "wait"


def test_dominant_bear_case_still_blocked_by_gap_veto():
    e = _engine()
    judge_input = _judge_input(bull_score=40, bear_score=85, synth_conf=72, breakout_confirmation=50)
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "wait"


def test_weak_confirmation_still_blocked():
    e = _engine()
    judge_input = _judge_input(bull_score=60, bear_score=68, synth_conf=72, breakout_confirmation=20, vol_15m=0.3, vol_1h=0.2)
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "wait"


def test_mean_reversion_setup_never_promotes():
    e = _engine()
    judge_input = _judge_input(setup_type="mean_reversion", bull_score=70, bear_score=60, synth_conf=90, breakout_confirmation=90, vol_15m=2, vol_1h=2)
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "wait"


def test_open_position_blocks_promotion():
    e = _engine()
    judge_input = _judge_input(bull_score=60, bear_score=68, synth_conf=72, breakout_confirmation=50)
    result = e._maybe_promote_wait_to_small_probe(
        judge_input, _wait_judge(), existing_position={"status": "open"}
    )
    assert result["decision"] == "wait"


def test_invalid_trade_plan_blocks_promotion():
    e = _engine()
    bad_plan = _trade_plan()
    bad_plan["trigger_price"] = None  # invalidates the plan
    judge_input = _judge_input(bull_score=60, bear_score=68, synth_conf=72, breakout_confirmation=50, trade_plan=bad_plan)
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "wait"


def test_already_approved_judge_is_not_overwritten():
    e = _engine()
    judge_input = _judge_input(bull_score=60, bear_score=68, synth_conf=72, breakout_confirmation=50)
    approved = {"decision": "approve_trade", "side": "BUY", "size_quote": 50.0}
    result = e._maybe_promote_wait_to_small_probe(judge_input, approved)
    assert result is approved


# ---------------------------------------------------------------------------
# Config-driven thresholds: gap and HTF semantics are read from self.cfg
# ---------------------------------------------------------------------------

def test_gap_threshold_is_read_from_config():
    """With a tighter operator-configured gap, the same candidate that promotes
    under defaults must fall back to wait -- proves the threshold is live-configurable."""
    e = _engine(small_probe_max_bear_bull_gap=5)  # gap=10 in the fixture below exceeds 5
    judge_input = _judge_input(bull_score=60, bear_score=70, synth_conf=72, breakout_confirmation=50, vol_15m=1.1, vol_1h=0.9)
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "wait"


def test_htf_or_mode_is_stricter_than_and_mode():
    """Reverting to legacy OR semantics via config must reproduce the old
    (over-blocking) behavior for a candidate with only a lagging 4h cross."""
    e = _engine(small_probe_require_htf_both_timeframes=False)
    judge_input = _judge_input(
        bull_score=60, bear_score=70, synth_conf=72, breakout_confirmation=50,
        vol_15m=1.1, vol_1h=0.9,
        ema50_4h=73.0, ema200_4h=74.0,  # 4h bearish only
        ema20_1h=76.9, ema50_1h=75.5,   # 1h bullish
    )
    result = e._maybe_promote_wait_to_small_probe(judge_input, _wait_judge())
    assert result["decision"] == "wait"
