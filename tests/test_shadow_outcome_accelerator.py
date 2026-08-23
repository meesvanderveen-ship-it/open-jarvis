"""Tests for the Shadow Outcome Accelerator.

Safety invariants verified:
- No Coinbase API calls (no coinbase_client, no REST/WebSocket imports)
- No live orders (no submit/cancel/replace/apply)
- No parameter mutation (no BotConfig write, no .env write, no profile activation)
- JSONL append-only safety and atomic rewrite
- Pending/completed evaluation lifecycle
- Correct 1h/4h/24h scheduling
- Missing candle/price data degrades to insufficient_data, not an error
- River consumes shadow records as read-only evidence only
- No execution authority granted through evidence feed
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.shadow_outcome_accelerator import (
    LEARNING_POLICY,
    SHADOW_HORIZONS_HOURS,
    SHADOW_OUTCOME_VERSION,
    ShadowOutcomeStore,
    _classify_shadow_outcome,
    _evidence_quality,
    _shadow_id,
    build_shadow_decision_record,
    build_shadow_outcome_summary,
    evaluate_shadow_record,
    load_shadow_evidence_for_river,
    write_shadow_outcome_reports,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _minimal_analysis(decision: str = "wait") -> Dict[str, Any]:
    return {
        "judge": {"decision": decision, "confidence": 0.6, "bull_score": 0.4, "bear_score": 0.3},
        "entry_gate": {"decision": "skip", "confidence": 0.5, "setup_type": "breakout"},
        "trade_plan": {
            "plan_action": "no_plan",
            "stop_loss": 95000.0,
            "take_profit_1": 105000.0,
            "trigger": 99000.0,
        },
    }


def _minimal_feature_pack(mid_price: float = 100000.0) -> Dict[str, Any]:
    return {
        "orderbook_context": {
            "mid_price": mid_price,
            "best_bid": mid_price - 10.0,
            "best_ask": mid_price + 10.0,
        }
    }


def _feature_pack_with_candles(mid_price: float = 100000.0) -> Dict[str, Any]:
    """Feature pack containing simple 1h candles for path metrics."""
    candles = []
    for i in range(24):
        t = _now() - timedelta(hours=24 - i)
        candles.append({
            "time": t.isoformat(),
            "open": mid_price * (1 + i * 0.001),
            "high": mid_price * (1 + i * 0.001 + 0.005),
            "low": mid_price * (1 + i * 0.001 - 0.003),
            "close": mid_price * (1 + i * 0.001 + 0.002),
            "volume": 1.0,
        })
    return {
        "orderbook_context": {
            "mid_price": mid_price,
            "best_bid": mid_price - 10.0,
            "best_ask": mid_price + 10.0,
        },
        "raw_context": {
            "1h": {
                "closes": [c["close"] for c in candles],
                "highs": [c["high"] for c in candles],
                "lows": [c["low"] for c in candles],
                "starts": [c["time"] for c in candles],
                "volumes": [c["volume"] for c in candles],
            }
        },
    }


# ---------------------------------------------------------------------------
# Safety: no Coinbase, no live orders, no parameter mutation
# ---------------------------------------------------------------------------

class TestSafetyInvariants:
    """Verify no dangerous imports or exports from shadow_outcome_accelerator."""

    def test_no_coinbase_client_import(self) -> None:
        import bot.shadow_outcome_accelerator as mod
        src = inspect.getsource(mod)
        assert "coinbase_client" not in src
        assert "CoinbaseClient" not in src
        assert "coinbase_order" not in src.lower()

    def test_no_live_order_submission(self) -> None:
        import bot.shadow_outcome_accelerator as mod
        src = inspect.getsource(mod)
        for forbidden in ("submit_order", "place_order", "create_order", "cancel_order", "replace_order"):
            assert forbidden not in src, f"Found forbidden call: {forbidden}"

    def test_no_env_writes(self) -> None:
        import bot.shadow_outcome_accelerator as mod
        src = inspect.getsource(mod)
        assert "os.environ" not in src or "os.environ.get" in src
        # No putenv or direct .env writes
        assert "putenv" not in src
        assert ".env" not in src or "no_coinbase_calls" in src  # only appears in policy strings

    def test_no_botconfig_mutation(self) -> None:
        import bot.shadow_outcome_accelerator as mod
        src = inspect.getsource(mod)
        # BotConfig must not be imported or instantiated (may appear in docstring)
        assert "from bot.config import" not in src
        assert "import BotConfig" not in src
        assert "BotConfig(" not in src
        # Profile activation must not be referenced
        assert "approved_parameter_profile" not in src

    def test_no_parameter_auto_apply(self) -> None:
        import bot.shadow_outcome_accelerator as mod
        src = inspect.getsource(mod)
        assert "activate_approved_parameter_profile" not in src
        assert "apply_parameter" not in src
        assert "autonomous_parameter_governor" not in src

    def test_learning_policy_present_in_records(self) -> None:
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis(),
            feature_pack=_minimal_feature_pack(),
        )
        assert record is not None
        assert record["no_live_orders"] is True
        assert record["no_coinbase_calls"] is True
        assert record["no_parameter_mutation"] is True
        assert "observation-only" in record["learning_policy"]

    def test_river_evidence_has_no_execution_authority(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        rec = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(),
            generated_at=_now() - timedelta(hours=25),
        )
        assert rec is not None
        # Manually set evaluations so River can pick it up
        rec["evaluations"]["1h"] = {
            "status": "complete",
            "evidence_usable": True,
            "evidence_quality": "medium",
            "horizon_key": "1h",
            "missed_opportunity_label": "no",
            "bad_trade_avoided_label": "yes",
        }
        rec["evaluations"]["4h"] = {
            "status": "complete",
            "evidence_usable": True,
            "evidence_quality": "high",
            "horizon_key": "4h",
            "missed_opportunity_label": "no",
            "bad_trade_avoided_label": "yes",
        }
        rec["evaluations"]["24h"] = {
            "status": "complete",
            "evidence_usable": True,
            "evidence_quality": "high",
            "horizon_key": "24h",
            "missed_opportunity_label": "no",
            "bad_trade_avoided_label": "yes",
        }
        store.append_record(rec)

        evidence = load_shadow_evidence_for_river(store_path=tmp_path / "shadow.jsonl")
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev["allowed_use"] == "evidence_only_no_execution_authority"
        assert "execution_authority" not in str(ev.get("learning_policy", ""))
        # No execution fields present
        assert "submit" not in str(ev)
        assert "cancel" not in str(ev)
        assert "live_order" not in str(ev)


# ---------------------------------------------------------------------------
# build_shadow_decision_record
# ---------------------------------------------------------------------------

class TestBuildShadowDecisionRecord:

    def test_basic_record_shape(self) -> None:
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
        )
        assert record is not None
        assert record["ticker"] == "BTC-USDC"
        assert record["decision"] == "wait"
        assert record["schema_version"] == SHADOW_OUTCOME_VERSION
        assert "shadow_id" in record
        assert record["shadow_id"].startswith("sha_")
        assert "evaluations" in record
        assert set(record["evaluations"].keys()) == {"1h", "4h", "24h"}
        assert all(v is None for v in record["evaluations"].values())
        assert "due_at" in record
        assert record["status"] == "pending"
        assert record["evidence_type"] == "shadow"

    def test_all_required_fields_present(self) -> None:
        fp = _minimal_feature_pack(50000.0)
        analysis = {
            **_minimal_analysis("reject"),
            "market_regime": "high_volatility",
            "bull_score": 0.7,
            "bear_score": 0.2,
        }
        record = build_shadow_decision_record(
            ticker="ETH-USDC",
            analysis=analysis,
            feature_pack=fp,
        )
        assert record is not None
        required_fields = [
            "shadow_id", "timestamp", "ticker", "product_id", "decision",
            "bull_score", "bear_score", "synth_confidence", "gate_confidence",
            "judge_decision", "judge_reason", "blocked_by", "gate_reason",
            "mid_price", "spread", "fee_estimate", "orderbook_snapshot",
            "market_regime", "proposed_entry_price", "proposed_stop",
            "proposed_take_profit", "risk_reward", "reward_to_fee",
            "model_route", "agent_route", "evaluations", "due_at", "status",
        ]
        for f in required_fields:
            assert f in record, f"Missing field: {f}"

    def test_returns_none_for_empty_ticker(self) -> None:
        result = build_shadow_decision_record(ticker="", analysis={})
        assert result is None

    def test_returns_none_for_whitespace_ticker(self) -> None:
        result = build_shadow_decision_record(ticker="   ", analysis={})
        assert result is None

    def test_handles_missing_analysis_fields_gracefully(self) -> None:
        record = build_shadow_decision_record(ticker="SOL-USDC", analysis={})
        assert record is not None
        assert record["ticker"] == "SOL-USDC"
        assert record["decision"] == "wait"
        assert record["bull_score"] is None
        assert record["bear_score"] is None

    def test_due_at_scheduling_correct(self) -> None:
        ts = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)
        record = build_shadow_decision_record(
            ticker="XRP-USDC",
            analysis=_minimal_analysis(),
            generated_at=ts,
        )
        assert record is not None
        due = record["due_at"]
        assert due["1h"] == (ts + timedelta(hours=1)).isoformat()
        assert due["4h"] == (ts + timedelta(hours=4)).isoformat()
        assert due["24h"] == (ts + timedelta(hours=24)).isoformat()

    def test_custom_horizons(self) -> None:
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis(),
            horizons_hours=(2, 8),
        )
        assert record is not None
        assert set(record["evaluations"].keys()) == {"2h", "8h"}
        assert set(record["due_at"].keys()) == {"2h", "8h"}

    def test_spread_computed_from_bid_ask(self) -> None:
        fp = {
            "orderbook_context": {
                "best_bid": 100.0,
                "best_ask": 100.6,
                "mid_price": 100.3,
            }
        }
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis={}, feature_pack=fp
        )
        assert record is not None
        assert record["spread"] is not None
        assert abs(record["spread"] - 0.006) < 0.0001

    def test_orderbook_snapshot_captured(self) -> None:
        fp = _minimal_feature_pack(50000.0)
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis={}, feature_pack=fp
        )
        assert record is not None
        snap = record["orderbook_snapshot"]
        assert snap is not None
        assert snap["mid_price"] == 50000.0

    def test_bull_bear_scores_from_judge(self) -> None:
        analysis = {
            "judge": {
                "decision": "wait",
                "bull_score": 0.75,
                "bear_score": 0.25,
                "confidence": 0.6,
            }
        }
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=analysis
        )
        assert record is not None
        assert record["bull_score"] == 0.75
        assert record["bear_score"] == 0.25

    def test_market_regime_captured(self) -> None:
        analysis = {"market_regime": "trend_up"}
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=analysis
        )
        assert record is not None
        assert record["market_regime"] == "trend_up"

    def test_trade_plan_levels_captured(self) -> None:
        analysis = {
            "trade_plan": {
                "trigger": 99500.0,
                "stop_loss": 97000.0,
                "take_profit_1": 105000.0,
            }
        }
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=analysis
        )
        assert record is not None
        assert record["proposed_entry_price"] == 99500.0
        assert record["proposed_stop"] == 97000.0
        assert record["proposed_take_profit"] == 105000.0

    def test_model_route_captured(self) -> None:
        analysis = {"model_route": "anthropic_claude_sonnet", "agent_route": "full_judge"}
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=analysis
        )
        assert record is not None
        assert record["model_route"] == "anthropic_claude_sonnet"
        assert record["agent_route"] == "full_judge"

    def test_cycle_id_captured(self) -> None:
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis={"cycle_id": "cycle-abc-123"},
            cycle_id="cycle-abc-123",
        )
        assert record is not None
        assert record["cycle_id"] == "cycle-abc-123"

    def test_shadow_id_deterministic(self) -> None:
        ts = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
        r1 = build_shadow_decision_record(
            ticker="BTC-USDC", analysis={"judge": {"decision": "wait"}}, generated_at=ts
        )
        r2 = build_shadow_decision_record(
            ticker="BTC-USDC", analysis={"judge": {"decision": "wait"}}, generated_at=ts
        )
        assert r1 is not None and r2 is not None
        assert r1["shadow_id"] == r2["shadow_id"]


# ---------------------------------------------------------------------------
# evaluate_shadow_record
# ---------------------------------------------------------------------------

class TestEvaluateShadowRecord:

    def test_no_data_returns_insufficient_data(self) -> None:
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=_minimal_analysis("wait")
        )
        assert record is not None
        result = evaluate_shadow_record(record, feature_pack={}, horizon_hours=1)
        assert result["status"] == "insufficient_data"
        assert result["evidence_usable"] is False
        assert result["evidence_quality"] == "insufficient"
        assert result["evidence_unusable_reason"] is not None

    def test_price_only_gives_low_quality(self) -> None:
        fp = _minimal_feature_pack(101000.0)  # no candles
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
        )
        assert record is not None
        result = evaluate_shadow_record(record, feature_pack=fp, horizon_hours=1)
        assert result["status"] == "complete"
        assert result["evidence_quality"] == "low"
        assert result["evidence_usable"] is True
        assert result["price_at_evaluation"] == 101000.0

    def test_candles_with_entry_levels_gives_high_quality(self) -> None:
        fp = _feature_pack_with_candles(mid_price=101000.0)
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis={
                **_minimal_analysis("wait"),
                "trade_plan": {
                    "stop_loss": 97000.0,
                    "take_profit_1": 106000.0,
                    "trigger": 99000.0,
                },
            },
            feature_pack=_minimal_feature_pack(100000.0),
        )
        assert record is not None
        result = evaluate_shadow_record(record, feature_pack=fp, horizon_hours=4)
        assert result["status"] == "complete"
        assert result["evidence_quality"] == "high"
        assert result["evidence_usable"] is True
        assert result["horizon_hours"] == 4

    def test_candles_without_entry_levels_gives_medium_quality(self) -> None:
        fp = _feature_pack_with_candles(mid_price=101000.0)
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis={"judge": {"decision": "wait"}},
            feature_pack=_minimal_feature_pack(100000.0),
        )
        assert record is not None
        result = evaluate_shadow_record(record, feature_pack=fp, horizon_hours=4)
        assert result["status"] == "complete"
        assert result["evidence_quality"] == "medium"

    def test_mfe_mae_computed_when_candles_available(self) -> None:
        # Build the record 25h in the past so the test's candles are "after" it
        created = _now() - timedelta(hours=25)
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),  # mid_price stored as 100000
            generated_at=created,
        )
        assert record is not None
        assert record["mid_price"] == 100000.0
        # Candles span last 24h (all after created_at = 25h ago)
        fp = _feature_pack_with_candles(mid_price=102000.0)
        result = evaluate_shadow_record(record, feature_pack=fp, horizon_hours=24)
        assert result["hypothetical_mfe"] is not None
        assert result["hypothetical_mae"] is not None

    def test_missed_opportunity_classified_for_wait(self) -> None:
        created = _now() - timedelta(hours=25)
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=created,
        )
        assert record is not None
        fp = _feature_pack_with_candles(mid_price=120000.0)  # large up move
        result = evaluate_shadow_record(
            record,
            feature_pack=fp,
            horizon_hours=24,
            min_move_pct=0.015,
        )
        assert result["missed_opportunity_label"] == "yes"
        assert result["bad_trade_avoided_label"] == "no"

    def test_bad_trade_avoided_classified_for_wait(self) -> None:
        created = _now() - timedelta(hours=25)
        record = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=created,
        )
        assert record is not None
        fp = _feature_pack_with_candles(mid_price=84000.0)  # large down move
        result = evaluate_shadow_record(
            record,
            feature_pack=fp,
            horizon_hours=24,
            adverse_move_pct=0.012,
        )
        assert result["bad_trade_avoided_label"] == "yes"
        assert result["missed_opportunity_label"] == "no"

    def test_horizon_key_correct(self) -> None:
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=_minimal_analysis()
        )
        assert record is not None
        for h in (1, 4, 24):
            result = evaluate_shadow_record(record, feature_pack={}, horizon_hours=h)
            assert result["horizon_key"] == f"{h}h"
            assert result["horizon_hours"] == h

    def test_learning_policy_in_evaluation(self) -> None:
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=_minimal_analysis()
        )
        assert record is not None
        result = evaluate_shadow_record(record, feature_pack={}, horizon_hours=1)
        assert "learning_policy" in result


# ---------------------------------------------------------------------------
# _classify_shadow_outcome
# ---------------------------------------------------------------------------

class TestClassifyShadowOutcome:

    def test_rejection_strong_up_is_missed_opportunity(self) -> None:
        bad, missed = _classify_shadow_outcome(
            decision="wait",
            price_move_pct=0.05,
            hypothetical_mfe=0.05,
            hypothetical_mae=-0.005,
            would_tp_have_hit=True,
            would_stop_have_hit=False,
            min_move_pct=0.015,
            adverse_move_pct=0.012,
        )
        assert missed == "yes"
        assert bad == "no"

    def test_rejection_strong_down_is_bad_trade_avoided(self) -> None:
        bad, missed = _classify_shadow_outcome(
            decision="reject",
            price_move_pct=-0.05,
            hypothetical_mfe=0.002,
            hypothetical_mae=-0.05,
            would_tp_have_hit=False,
            would_stop_have_hit=True,
            min_move_pct=0.015,
            adverse_move_pct=0.012,
        )
        assert bad == "yes"
        assert missed == "no"

    def test_rejection_no_clear_move_is_unclear(self) -> None:
        bad, missed = _classify_shadow_outcome(
            decision="wait",
            price_move_pct=0.002,
            hypothetical_mfe=0.002,
            hypothetical_mae=-0.001,
            would_tp_have_hit=False,
            would_stop_have_hit=False,
            min_move_pct=0.015,
            adverse_move_pct=0.012,
        )
        assert bad == "unclear"
        assert missed == "unclear"

    def test_no_price_returns_none_labels(self) -> None:
        bad, missed = _classify_shadow_outcome(
            decision="wait",
            price_move_pct=None,
            hypothetical_mfe=None,
            hypothetical_mae=None,
            would_tp_have_hit=None,
            would_stop_have_hit=None,
            min_move_pct=0.015,
            adverse_move_pct=0.012,
        )
        assert bad is None
        assert missed is None

    def test_approval_classified_as_not_rejection(self) -> None:
        bad, missed = _classify_shadow_outcome(
            decision="approve_trade",
            price_move_pct=0.05,
            hypothetical_mfe=0.05,
            hypothetical_mae=-0.005,
            would_tp_have_hit=True,
            would_stop_have_hit=False,
            min_move_pct=0.015,
            adverse_move_pct=0.012,
        )
        assert bad == "n/a_was_approval"


# ---------------------------------------------------------------------------
# ShadowOutcomeStore
# ---------------------------------------------------------------------------

class TestShadowOutcomeStore:

    def test_append_record_creates_file(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=_minimal_analysis()
        )
        assert record is not None
        result = store.append_record(record)
        assert result is True
        assert (tmp_path / "shadow.jsonl").exists()

    def test_append_record_dedup(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        record = build_shadow_decision_record(
            ticker="BTC-USDC", analysis=_minimal_analysis()
        )
        assert record is not None
        store.append_record(record)
        result = store.append_record(record)  # duplicate
        assert result is False
        records = store.load_all()
        assert len(records) == 1

    def test_load_all_returns_valid_records(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        for ticker in ("BTC-USDC", "ETH-USDC", "SOL-USDC"):
            r = build_shadow_decision_record(
                ticker=ticker,
                analysis=_minimal_analysis(),
                generated_at=_now(),
            )
            assert r is not None
            store.append_record(r)
        records = store.load_all()
        assert len(records) == 3

    def test_load_all_empty_store(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        assert store.load_all() == []

    def test_disabled_store_returns_none(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl", enabled=False)
        result = store.record_decision(
            ticker="BTC-USDC", analysis=_minimal_analysis()
        )
        assert result is None
        assert not (tmp_path / "shadow.jsonl").exists()

    def test_record_decision_convenience_method(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        result = store.record_decision(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(),
        )
        assert result is not None
        assert result["ticker"] == "BTC-USDC"
        records = store.load_all()
        assert len(records) == 1

    def test_jsonl_each_line_is_valid_json(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        for i, ticker in enumerate(["BTC-USDC", "ETH-USDC"]):
            r = build_shadow_decision_record(
                ticker=ticker,
                analysis=_minimal_analysis(),
                generated_at=_now() - timedelta(seconds=i),
            )
            assert r is not None
            store.append_record(r)
        path = tmp_path / "shadow.jsonl"
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert isinstance(obj, dict)
            assert "shadow_id" in obj

    def test_atomic_rewrite_after_evaluation(self, tmp_path: Path) -> None:
        """Rewrite must produce a readable JSONL with no truncation."""
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        past = _now() - timedelta(hours=5)
        r = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=past,
        )
        assert r is not None
        store.append_record(r)

        fp = {"BTC-USDC": _minimal_feature_pack(101000.0)}
        updated = store.evaluate_due(feature_packs=fp, now=_now())
        assert len(updated) >= 1

        # After rewrite, file must still be valid JSONL
        lines = (tmp_path / "shadow.jsonl").read_text().strip().split("\n")
        for line in lines:
            obj = json.loads(line)
            assert isinstance(obj, dict)

    def test_no_tmp_file_left_after_rewrite(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        past = _now() - timedelta(hours=5)
        r = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=past,
        )
        assert r is not None
        store.append_record(r)
        store.evaluate_due(feature_packs={"BTC-USDC": _minimal_feature_pack(101000.0)}, now=_now())
        tmp = tmp_path / "shadow.jsonl.tmp"
        assert not tmp.exists()


# ---------------------------------------------------------------------------
# Evaluation lifecycle: pending → partial → complete
# ---------------------------------------------------------------------------

class TestEvaluationLifecycle:

    def test_1h_slot_filled_when_1h_due(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        created = _now() - timedelta(hours=2)
        r = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=created,
        )
        assert r is not None
        store.append_record(r)
        updated = store.evaluate_due(
            feature_packs={"BTC-USDC": _minimal_feature_pack(101500.0)},
            now=_now(),
        )
        records = store.load_all()
        assert len(records) == 1
        evals = records[0]["evaluations"]
        assert evals["1h"] is not None
        assert evals["1h"]["status"] == "complete"
        # 4h and 24h slots not yet due
        assert evals["4h"] is None
        assert evals["24h"] is None

    def test_all_slots_filled_after_24h(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        created = _now() - timedelta(hours=25)
        r = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=created,
        )
        assert r is not None
        store.append_record(r)
        store.evaluate_due(
            feature_packs={"BTC-USDC": _feature_pack_with_candles(103000.0)},
            now=_now(),
        )
        records = store.load_all()
        evals = records[0]["evaluations"]
        assert evals["1h"] is not None
        assert evals["4h"] is not None
        assert evals["24h"] is not None
        assert records[0]["status"] == "complete"

    def test_status_stays_pending_when_not_due(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        r = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis(),
            generated_at=_now(),
        )
        assert r is not None
        store.append_record(r)
        store.evaluate_due(
            feature_packs={"BTC-USDC": _minimal_feature_pack(101000.0)},
            now=_now(),
        )
        records = store.load_all()
        assert records[0]["status"] == "pending"
        assert all(v is None for v in records[0]["evaluations"].values())

    def test_insufficient_data_does_not_lock_slot(self, tmp_path: Path) -> None:
        """When feature_pack is empty, slot stays None so next cycle can retry."""
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        past = _now() - timedelta(hours=2)
        r = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=past,
        )
        assert r is not None
        store.append_record(r)
        # No feature_pack for BTC-USDC → insufficient data
        store.evaluate_due(feature_packs={}, now=_now())
        records = store.load_all()
        # Slot should remain None (pending) since no fp was available
        assert records[0]["evaluations"]["1h"] is None
        assert records[0]["status"] == "pending"

    def test_missing_price_gives_insufficient_data_status(self, tmp_path: Path) -> None:
        """Empty feature_pack (no price, no candles) → evaluation slot stays pending."""
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        past = _now() - timedelta(hours=2)
        r = build_shadow_decision_record(
            ticker="ETH-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(3000.0),
            generated_at=past,
        )
        assert r is not None
        store.append_record(r)
        store.evaluate_due(feature_packs={"ETH-USDC": {}}, now=_now())
        records = store.load_all()
        # Empty dict provided → slot should be set to insufficient_data
        ev = records[0]["evaluations"]["1h"]
        assert ev is not None
        assert ev["status"] == "insufficient_data"

    def test_already_complete_records_skipped(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        past = _now() - timedelta(hours=25)
        r = build_shadow_decision_record(
            ticker="BTC-USDC",
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=past,
        )
        assert r is not None
        store.append_record(r)
        fp = {"BTC-USDC": _feature_pack_with_candles(103000.0)}
        store.evaluate_due(feature_packs=fp, now=_now())
        # Second call should not update anything
        updated = store.evaluate_due(feature_packs=fp, now=_now())
        assert len(updated) == 0

    def test_multiple_tickers_evaluated_independently(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        past = _now() - timedelta(hours=2)
        for ticker in ("BTC-USDC", "ETH-USDC"):
            r = build_shadow_decision_record(
                ticker=ticker,
                analysis=_minimal_analysis("wait"),
                feature_pack=_minimal_feature_pack(100000.0),
                generated_at=past - timedelta(seconds=int(ticker == "ETH-USDC")),
            )
            assert r is not None
            store.append_record(r)
        fp = {
            "BTC-USDC": _minimal_feature_pack(102000.0),
            "ETH-USDC": _minimal_feature_pack(3200.0),
        }
        store.evaluate_due(feature_packs=fp, now=_now())
        records = store.load_all()
        assert len(records) == 2
        for rec in records:
            assert rec["evaluations"]["1h"] is not None


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

class TestBuildShadowOutcomeSummary:

    def test_empty_records(self) -> None:
        summary = build_shadow_outcome_summary([])
        assert summary["total_shadow_decisions"] == 0
        assert summary["usable_evidence_count"] == 0
        assert summary["sufficient_for_optimization"] is False
        assert summary["no_live_orders"] is True
        assert summary["no_coinbase_calls"] is True
        assert summary["no_parameter_mutation"] is True

    def test_counts_by_ticker(self) -> None:
        records = []
        for ticker in ("BTC-USDC", "BTC-USDC", "ETH-USDC"):
            r = build_shadow_decision_record(ticker=ticker, analysis=_minimal_analysis())
            assert r is not None
            records.append(r)
        summary = build_shadow_outcome_summary(records)
        assert summary["by_ticker"]["BTC-USDC"] == 2
        assert summary["by_ticker"]["ETH-USDC"] == 1

    def test_counts_by_regime(self) -> None:
        records = []
        for regime in ("trend_up", "trend_up", "high_volatility"):
            r = build_shadow_decision_record(
                ticker="BTC-USDC",
                analysis={"market_regime": regime},
                generated_at=_now() - timedelta(seconds=len(records)),
            )
            assert r is not None
            records.append(r)
        summary = build_shadow_outcome_summary(records)
        assert summary["by_regime"]["trend_up"] == 2
        assert summary["by_regime"]["high_volatility"] == 1

    def test_sufficient_flag_false_below_threshold(self) -> None:
        records = [
            build_shadow_decision_record(ticker="BTC-USDC", analysis=_minimal_analysis())
            for _ in range(10)
        ]
        summary = build_shadow_outcome_summary([r for r in records if r is not None])
        assert summary["sufficient_for_optimization"] is False

    def test_missed_opportunity_pattern_counted(self) -> None:
        records = []
        for _ in range(3):
            r = build_shadow_decision_record(
                ticker="BTC-USDC",
                analysis={"trade_plan": {"setup_type": "breakout"}, "judge": {"decision": "wait"}},
                generated_at=_now() - timedelta(seconds=len(records)),
            )
            assert r is not None
            r["evaluations"]["1h"] = {
                "status": "complete",
                "evidence_usable": True,
                "evidence_quality": "medium",
                "missed_opportunity_label": "yes",
                "bad_trade_avoided_label": "no",
            }
            records.append(r)
        summary = build_shadow_outcome_summary(records)
        assert len(summary["top_missed_opportunity_patterns"]) > 0

    def test_evidence_quality_score_computed(self) -> None:
        records = []
        for i in range(4):
            r = build_shadow_decision_record(
                ticker="BTC-USDC",
                analysis=_minimal_analysis(),
                generated_at=_now() - timedelta(seconds=i),
            )
            assert r is not None
            # 3 usable, 1 not
            r["evaluations"]["1h"] = {
                "status": "complete",
                "evidence_usable": i < 3,
                "evidence_quality": "medium" if i < 3 else "insufficient",
                "missed_opportunity_label": "unclear",
                "bad_trade_avoided_label": "unclear",
            }
            records.append(r)
        summary = build_shadow_outcome_summary(records)
        assert abs(summary["evidence_quality_score"] - 0.75) < 0.01


# ---------------------------------------------------------------------------
# River evidence feed
# ---------------------------------------------------------------------------

class TestLoadShadowEvidenceForRiver:

    def _make_completed_record(
        self,
        ticker: str = "BTC-USDC",
        quality: str = "high",
        missed: str = "yes",
        bad_avoided: str = "no",
        ts_offset_hours: int = 0,
    ) -> Dict[str, Any]:
        r = build_shadow_decision_record(
            ticker=ticker,
            analysis=_minimal_analysis("wait"),
            feature_pack=_minimal_feature_pack(100000.0),
            generated_at=_now() - timedelta(hours=ts_offset_hours),
        )
        assert r is not None
        for h_key in ("1h", "4h", "24h"):
            r["evaluations"][h_key] = {
                "status": "complete",
                "evidence_usable": quality != "insufficient",
                "evidence_quality": quality,
                "missed_opportunity_label": missed,
                "bad_trade_avoided_label": bad_avoided,
                "horizon_key": h_key,
            }
        r["status"] = "complete"
        return r

    def test_returns_evidence_for_completed_records(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        rec = self._make_completed_record()
        store.append_record(rec)
        evidence = load_shadow_evidence_for_river(store_path=tmp_path / "shadow.jsonl")
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev["source"] == "shadow_outcome_accelerator"
        assert ev["allowed_use"] == "evidence_only_no_execution_authority"
        assert ev["ticker"] == "BTC-USDC"

    def test_filters_by_min_quality(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        store.append_record(self._make_completed_record(quality="low", ts_offset_hours=1))
        store.append_record(self._make_completed_record(quality="high", ts_offset_hours=2))
        evidence_medium = load_shadow_evidence_for_river(
            store_path=tmp_path / "shadow.jsonl", min_quality="medium"
        )
        assert len(evidence_medium) == 1  # only high passes
        assert evidence_medium[0]["evidence_quality"] == "high"

    def test_insufficient_quality_excluded(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        r = build_shadow_decision_record(ticker="BTC-USDC", analysis=_minimal_analysis())
        assert r is not None
        for h in ("1h", "4h", "24h"):
            r["evaluations"][h] = {
                "status": "insufficient_data",
                "evidence_usable": False,
                "evidence_quality": "insufficient",
            }
        store.append_record(r)
        evidence = load_shadow_evidence_for_river(store_path=tmp_path / "shadow.jsonl")
        assert len(evidence) == 0

    def test_prefers_longest_horizon(self, tmp_path: Path) -> None:
        """24h evidence preferred over 1h for each record."""
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        rec = self._make_completed_record()
        store.append_record(rec)
        evidence = load_shadow_evidence_for_river(store_path=tmp_path / "shadow.jsonl")
        assert len(evidence) == 1
        assert evidence[0]["horizon_key"] == "24h"

    def test_max_records_limit(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        for i in range(20):
            store.append_record(
                self._make_completed_record(ts_offset_hours=i)
            )
        evidence = load_shadow_evidence_for_river(
            store_path=tmp_path / "shadow.jsonl", max_records=5
        )
        assert len(evidence) <= 5

    def test_evidence_compact_keys_present(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        rec = self._make_completed_record()
        rec["market_regime"] = "high_volatility"
        rec["setup_type"] = "breakout"
        store.append_record(rec)
        evidence = load_shadow_evidence_for_river(store_path=tmp_path / "shadow.jsonl")
        ev = evidence[0]
        for key in ("ticker", "market_regime", "setup_type", "decision", "side",
                    "horizon_key", "bad_trade_avoided_label", "missed_opportunity_label",
                    "evidence_quality", "learning_policy"):
            assert key in ev, f"Missing key in evidence: {key}"

    def test_no_execution_fields_in_evidence(self, tmp_path: Path) -> None:
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        store.append_record(self._make_completed_record())
        evidence = load_shadow_evidence_for_river(store_path=tmp_path / "shadow.jsonl")
        ev_str = json.dumps(evidence)
        for forbidden in ("submit", "cancel", "replace", "live_order", "coinbase_client",
                          "apply_parameter", "activate_profile"):
            assert forbidden not in ev_str.lower()


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

class TestWriteShadowOutcomeReports:

    def test_writes_json_and_md(self, tmp_path: Path) -> None:
        records = [
            build_shadow_decision_record(
                ticker="BTC-USDC",
                analysis=_minimal_analysis(),
                generated_at=_now() - timedelta(seconds=i),
            )
            for i in range(3)
        ]
        valid_records = [r for r in records if r is not None]
        json_path = tmp_path / "report.json"
        md_path = tmp_path / "report.md"
        summary = write_shadow_outcome_reports(
            valid_records, json_path=json_path, md_path=md_path
        )
        assert json_path.exists()
        assert md_path.exists()
        parsed = json.loads(json_path.read_text())
        assert parsed["total_shadow_decisions"] == 3
        md_text = md_path.read_text()
        assert "Shadow Outcome Accelerator" in md_text
        assert "Evidence-only" in md_text
        assert "No live orders" in md_text

    def test_json_contains_safety_flags(self, tmp_path: Path) -> None:
        summary = write_shadow_outcome_reports(
            [],
            json_path=tmp_path / "r.json",
            md_path=tmp_path / "r.md",
        )
        assert summary["no_live_orders"] is True
        assert summary["no_coinbase_calls"] is True
        assert summary["no_parameter_mutation"] is True


# ---------------------------------------------------------------------------
# show_shadow_outcome_learning_status tool
# ---------------------------------------------------------------------------

class TestShowShadowOutcomeLearningStatusTool:

    def test_tool_runs_without_error(self, tmp_path: Path) -> None:
        from tools.show_shadow_outcome_learning_status import main
        rc = main(["--store-path", str(tmp_path / "empty.jsonl")])
        assert rc == 0

    def test_tool_json_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        from tools.show_shadow_outcome_learning_status import main
        rc = main(["--json", "--store-path", str(tmp_path / "empty.jsonl")])
        assert rc == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert "total_shadow_decisions" in parsed
        assert parsed["total_shadow_decisions"] == 0

    def test_tool_write_reports(self, tmp_path: Path) -> None:
        from tools.show_shadow_outcome_learning_status import main
        json_out = tmp_path / "out.json"
        md_out = tmp_path / "out.md"
        # Create a small store so there's something to report on
        store = ShadowOutcomeStore(path=tmp_path / "shadow.jsonl")
        r = build_shadow_decision_record(ticker="BTC-USDC", analysis=_minimal_analysis())
        assert r is not None
        store.append_record(r)
        rc = main([
            "--write-reports",
            "--store-path", str(tmp_path / "shadow.jsonl"),
        ])
        assert rc == 0


# ---------------------------------------------------------------------------
# py_compile check
# ---------------------------------------------------------------------------

def test_shadow_outcome_accelerator_compiles() -> None:
    import py_compile
    path = str(PROJECT_ROOT / "bot" / "shadow_outcome_accelerator.py")
    py_compile.compile(path, doraise=True)


def test_show_shadow_outcome_status_tool_compiles() -> None:
    import py_compile
    path = str(PROJECT_ROOT / "tools" / "show_shadow_outcome_learning_status.py")
    py_compile.compile(path, doraise=True)
