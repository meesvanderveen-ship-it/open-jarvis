from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bot.full_bot_real_fresh_review_runner import build_real_fresh_review_report


NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


class FakeJudge:
    def __init__(self, decision: str = "approve_trade"):
        self.decision = decision
        self.calls = []

    def json_response(self, system_prompt, payload, model=None, max_retries=1, **kwargs):
        self.calls.append({"system_prompt": system_prompt, "payload": payload, "kwargs": kwargs})
        return {
            "decision": self.decision,
            "side": "BUY" if self.decision == "approve_trade" else "NONE",
            "approved": self.decision == "approve_trade",
            "confidence": 82,
            "rationale": "fresh structured review accepted" if self.decision == "approve_trade" else "wait",
            "blockers": [] if self.decision == "approve_trade" else ["insufficient_edge"],
        }


def _write_root(root: Path) -> None:
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state/open_orders.json").write_text("{}\n", encoding="utf-8")
    (root / "state/positions.json").write_text("{}\n", encoding="utf-8")
    (root / ".env").write_text("", encoding="utf-8")


def _intent(ticker: str = "XRP-USDC") -> dict:
    return {
        "ticker": ticker,
        "side": "BUY",
        "status": "near_miss_intent",
        "setup_family": "reclaim_reversal",
        "preferred_order_type": "limit_maker",
        "proposed_size_quote": "20",
        "proposed_price": "0.6535",
        "target_reference": "0.6711",
        "invalidation_reference": "0.6410",
        "expires_at": "2026-06-10T12:30:00Z",
        "intent_id": f"intent-{ticker}",
        "soft_blockers": [],
        "orderbook_score": "95",
        "liquidity_score": "90",
    }


def _selected(ticker: str = "XRP-USDC") -> dict:
    intent = _intent(ticker)
    action = {
        "ticker": ticker,
        "side": "BUY",
        "action_class": "near_miss_maker_buy",
        "classification": "preview_only",
        "details": {"intent": intent},
    }
    return {
        "ticker": ticker,
        "action_class": "near_miss_maker_buy",
        "classification": "preview_only",
        "side": "BUY",
        "quote_size": "20",
        "limit_price": intent["proposed_price"],
        "source_action": action,
    }


def _reports() -> dict:
    selected = [_selected("XRP-USDC")]
    return {
        "d6_report": {"near_miss_intents": [_intent("XRP-USDC")]},
        "workflow_audit_report": {"readiness_verdict": "blocked_by_missing_fresh_judge_and_risk"},
        "failure_matrix_report": {
            "summary": {"all_p1_items": ["XRP-USDC"], "any_ticker_phase_c_ready_now": False},
            "matrix": [
                {
                    "ticker": "XRP-USDC",
                    "priority": "P1",
                    "root_cause_category": "needs_fresh_judge_review",
                    "phase_c_guard_blockers": [],
                }
            ],
        },
        "adapter_report": {
            "phase": "full_bot_maker_buy_live_adapter_v1",
            "selected_entry_candidates": selected,
            "rejected_entry_candidates": [],
            "reservation_summary": {"open_order_count": 0},
        },
        "near_miss_review_report": {"fresh_review_results": [{"ticker": "XRP-USDC"}]},
        "orchestrator_report": {"entry_action_candidates": [selected[0]["source_action"]]},
    }


def _report(tmp_path: Path, **kwargs) -> dict:
    _write_root(tmp_path)
    params = _reports()
    params.update(kwargs)
    return build_real_fresh_review_report(root=tmp_path, generated_at=NOW, **params)


def test_no_llm_mode_does_not_fabricate_approval(tmp_path: Path) -> None:
    report = _report(tmp_path, call_llm_judge=False)
    assert report["live_order_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["judge_approvals"] == []
    assert report["deterministic_live_risk_approvals"] == []
    assert "real_llm_judge_not_called" in report["blockers"]


def test_real_judge_approval_can_feed_deterministic_risk_and_phase_c_preview(tmp_path: Path) -> None:
    judge = FakeJudge("approve_trade")
    report = _report(tmp_path, judge_client=judge, call_llm_judge=True)
    assert judge.calls
    assert report["judge_approvals"] == ["XRP-USDC"]
    assert report["deterministic_live_risk_approvals"] == ["XRP-USDC"]
    assert report["phase_c_ready_candidates"] == ["XRP-USDC"]
    assert report["actual_submit_allowed_now"] is False


def test_wait_judge_blocks_risk_and_phase_c(tmp_path: Path) -> None:
    report = _report(tmp_path, judge_client=FakeJudge("wait"), call_llm_judge=True)
    assert report["judge_approvals"] == []
    assert report["deterministic_live_risk_approvals"] == []
    assert report["phase_c_ready_candidates"] == []


def test_judge_exception_is_honest_wait(tmp_path: Path) -> None:
    class BrokenJudge:
        def json_response(self, *args, **kwargs):
            raise RuntimeError("provider down")

    report = _report(tmp_path, judge_client=BrokenJudge(), call_llm_judge=True)
    evidence = report["by_ticker"]["XRP-USDC"]
    assert evidence["judge"]["decision"] == "wait"
    assert evidence["judge"]["approved"] is False
    assert evidence["judge"]["error"] == "provider down"


def test_judge_network_exception_is_classified_as_provider_blocker(tmp_path: Path) -> None:
    class BrokenJudge:
        def json_response(self, *args, **kwargs):
            raise RuntimeError("OpenAI json_response mislukt: Connection error.")

    report = _report(tmp_path, judge_client=BrokenJudge(), call_llm_judge=True)
    evidence = report["by_ticker"]["XRP-USDC"]
    assert evidence["judge"]["decision"] == "wait"
    assert evidence["judge"]["provider_error_type"] == "provider_network_or_connection_error"
    assert report["judge_provider_error_types"] == ["provider_network_or_connection_error"]
    assert "fresh_judge_provider_error:provider_network_or_connection_error" in report["blockers"]
