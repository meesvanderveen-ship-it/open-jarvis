"""Tests verifying that strategy_engine properly wires Shadow Outcome Accelerator.

What is tested:
- _record_shadow_decision delegates to shadow_outcome_store.record_decision
- Decision record contains correct ticker / analysis / cycle_result / feature_pack
- Errors inside shadow_outcome_store.record_decision never propagate to callers
- Error is logged to errors.jsonl, not raised
- enable_shadow_outcome_accelerator=False → record_decision never called
- No live orders, no Coinbase calls, no parameter mutation originate from the hook
"""
from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide minimal stubs for optional heavyweight dependencies that strategy_engine
# imports at module-level. These stubs are inert — they only prevent ImportError.
for _mod, _attrs in [
    ("openai", {"OpenAI": type("OpenAI", (), {"__init__": lambda s, *a, **k: None})}),
    ("anthropic", {"Anthropic": type("Anthropic", (), {"__init__": lambda s, *a, **k: None})}),
    ("pandas", {"DataFrame": object, "Series": object,
                "concat": lambda *a, **k: [], "isna": lambda v: v is None}),
    ("numpy", {"nan": float("nan"), "arange": lambda *a, **k: [],
               "polyfit": lambda *a, **k: [0]}),
]:
    if _mod not in sys.modules:
        stub = types.ModuleType(_mod)
        for k, v in _attrs.items():
            setattr(stub, k, v)
        sys.modules[_mod] = stub

from bot.strategy_engine import StrategyEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _CapturingShadowStore:
    """Minimal stand-in for ShadowOutcomeStore that records calls."""

    def __init__(self, *, raise_on_record: bool = False):
        self.calls: List[Dict[str, Any]] = []
        self._raise = raise_on_record

    def record_decision(
        self,
        *,
        ticker: str,
        analysis: Dict,
        cycle_result: Dict,
        feature_pack: Dict,
    ) -> Optional[object]:
        if self._raise:
            raise RuntimeError("simulated shadow store failure")
        self.calls.append({
            "ticker": ticker,
            "analysis": analysis,
            "cycle_result": cycle_result,
            "feature_pack": feature_pack,
        })
        return None


def _make_engine(*, shadow_store: _CapturingShadowStore, enabled: bool = True) -> StrategyEngine:
    e = StrategyEngine.__new__(StrategyEngine)
    e.cfg = SimpleNamespace(enable_shadow_outcome_accelerator=enabled)
    e.shadow_outcome_store = shadow_store
    e._logged: List[tuple] = []
    e._write_jsonl = lambda name, payload: e._logged.append((name, payload))
    e._now_iso = StrategyEngine._now_iso
    return e


def _analysis(decision: str = "wait") -> Dict[str, Any]:
    return {
        "judge": {"decision": decision, "confidence": 0.7,
                  "bull_score": 0.5, "bear_score": 0.3},
        "entry_gate": {"decision": "skip"},
    }


def _feature_pack() -> Dict[str, Any]:
    return {"orderbook_context": {"mid_price": 100000.0}}


def _cycle_result(decision: str = "wait") -> Dict[str, Any]:
    return {"decision": decision, "ticker": "BTC-USDC"}


# ---------------------------------------------------------------------------
# Basic delegation tests
# ---------------------------------------------------------------------------

class TestRecordShadowDecisionDelegation:

    def test_record_shadow_decision_calls_store(self) -> None:
        store = _CapturingShadowStore()
        e = _make_engine(shadow_store=store)
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis("wait"),
            cycle_result=_cycle_result("wait"),
            feature_pack=_feature_pack(),
        )
        assert len(store.calls) == 1

    def test_record_shadow_decision_passes_ticker(self) -> None:
        store = _CapturingShadowStore()
        e = _make_engine(shadow_store=store)
        e._record_shadow_decision(
            ticker="ETH-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=_feature_pack(),
        )
        assert store.calls[0]["ticker"] == "ETH-USDC"

    def test_record_shadow_decision_passes_analysis(self) -> None:
        store = _CapturingShadowStore()
        e = _make_engine(shadow_store=store)
        ana = _analysis("approve_trade")
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=ana,
            cycle_result=_cycle_result("approve_trade"),
            feature_pack=_feature_pack(),
        )
        assert store.calls[0]["analysis"] is ana

    def test_record_shadow_decision_passes_cycle_result(self) -> None:
        store = _CapturingShadowStore()
        e = _make_engine(shadow_store=store)
        cr = _cycle_result("reject")
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis("reject"),
            cycle_result=cr,
            feature_pack=_feature_pack(),
        )
        assert store.calls[0]["cycle_result"] is cr

    def test_record_shadow_decision_passes_feature_pack(self) -> None:
        store = _CapturingShadowStore()
        e = _make_engine(shadow_store=store)
        fp = _feature_pack()
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=fp,
        )
        assert store.calls[0]["feature_pack"] is fp


# ---------------------------------------------------------------------------
# Fail-open: errors in shadow logging never break trading flow
# ---------------------------------------------------------------------------

class TestShadowDecisionFailOpen:

    def test_store_exception_does_not_propagate(self) -> None:
        store = _CapturingShadowStore(raise_on_record=True)
        e = _make_engine(shadow_store=store)
        # Must not raise
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=_feature_pack(),
        )

    def test_store_exception_logged_to_errors_jsonl(self) -> None:
        store = _CapturingShadowStore(raise_on_record=True)
        e = _make_engine(shadow_store=store)
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=_feature_pack(),
        )
        assert any(name == "errors.jsonl" for name, _ in e._logged)

    def test_store_exception_log_contains_module_key(self) -> None:
        store = _CapturingShadowStore(raise_on_record=True)
        e = _make_engine(shadow_store=store)
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=_feature_pack(),
        )
        error_payloads = [p for name, p in e._logged if name == "errors.jsonl"]
        assert len(error_payloads) == 1
        assert error_payloads[0].get("module") == "shadow_outcome_accelerator"

    def test_store_exception_log_contains_error_type(self) -> None:
        store = _CapturingShadowStore(raise_on_record=True)
        e = _make_engine(shadow_store=store)
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=_feature_pack(),
        )
        error_payloads = [p for name, p in e._logged if name == "errors.jsonl"]
        assert error_payloads[0].get("error_type") == "shadow_decision_record_failed"

    def test_store_exception_log_contains_error_message(self) -> None:
        store = _CapturingShadowStore(raise_on_record=True)
        e = _make_engine(shadow_store=store)
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=_feature_pack(),
        )
        error_payloads = [p for name, p in e._logged if name == "errors.jsonl"]
        assert "simulated shadow store failure" in error_payloads[0].get("error", "")


# ---------------------------------------------------------------------------
# Flag-off: disabled → nothing written
# ---------------------------------------------------------------------------

class TestShadowDecisionFlagOff:

    def test_disabled_flag_skips_record(self) -> None:
        store = _CapturingShadowStore()
        e = _make_engine(shadow_store=store, enabled=False)
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=_feature_pack(),
        )
        assert len(store.calls) == 0

    def test_disabled_flag_no_errors_logged(self) -> None:
        store = _CapturingShadowStore()
        e = _make_engine(shadow_store=store, enabled=False)
        e._record_shadow_decision(
            ticker="BTC-USDC",
            analysis=_analysis(),
            cycle_result=_cycle_result(),
            feature_pack=_feature_pack(),
        )
        assert len(e._logged) == 0


# ---------------------------------------------------------------------------
# Safety: no Coinbase, no live orders from the wiring code itself
# ---------------------------------------------------------------------------

class TestShadowDecisionSafety:

    def test_record_shadow_decision_no_coinbase_call(self) -> None:
        src = inspect.getsource(StrategyEngine._record_shadow_decision)
        assert "coinbase_client" not in src.lower()
        assert "submit_order" not in src
        assert "place_order" not in src
        assert "cancel_order" not in src

    def test_evaluate_due_shadow_outcomes_no_coinbase_call(self) -> None:
        src = inspect.getsource(StrategyEngine._evaluate_due_shadow_outcomes)
        assert "coinbase_client" not in src.lower()
        assert "submit_order" not in src

    def test_shadow_outcome_store_is_separate_from_order_submission(self) -> None:
        src = inspect.getsource(StrategyEngine._record_shadow_decision)
        assert "order_store" not in src
        assert "submit" not in src


# ---------------------------------------------------------------------------
# evaluate_due wiring: fail-open
# ---------------------------------------------------------------------------

class _CapturingEvalStore(_CapturingShadowStore):
    def evaluate_due(self, *, feature_packs, now=None):
        if self._raise:
            raise RuntimeError("eval failure")
        self.calls.append({"action": "evaluate_due", "feature_packs": feature_packs})


class TestEvaluateDueShadowOutcomes:

    def test_evaluate_due_calls_store(self) -> None:
        store = _CapturingEvalStore()
        e = _make_engine(shadow_store=store)
        e._evaluate_due_shadow_outcomes({"BTC-USDC": _feature_pack()})
        assert any(c.get("action") == "evaluate_due" for c in store.calls)

    def test_evaluate_due_exception_does_not_propagate(self) -> None:
        store = _CapturingEvalStore(raise_on_record=True)
        e = _make_engine(shadow_store=store)
        e._evaluate_due_shadow_outcomes({"BTC-USDC": _feature_pack()})

    def test_evaluate_due_exception_logged_to_errors_jsonl(self) -> None:
        store = _CapturingEvalStore(raise_on_record=True)
        e = _make_engine(shadow_store=store)
        e._evaluate_due_shadow_outcomes({"BTC-USDC": _feature_pack()})
        assert any(name == "errors.jsonl" for name, _ in e._logged)

    def test_evaluate_due_disabled_skips_store(self) -> None:
        store = _CapturingEvalStore()
        e = _make_engine(shadow_store=store, enabled=False)
        e._evaluate_due_shadow_outcomes({"BTC-USDC": _feature_pack()})
        assert len(store.calls) == 0


# ---------------------------------------------------------------------------
# py_compile check
# ---------------------------------------------------------------------------

def test_strategy_engine_still_compiles() -> None:
    import py_compile
    py_compile.compile(str(PROJECT_ROOT / "bot" / "strategy_engine.py"), doraise=True)
