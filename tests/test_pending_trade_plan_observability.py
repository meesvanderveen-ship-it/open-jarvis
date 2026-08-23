import inspect
import json

from bot.pending_trade_plans import PendingTradePlanStore, build_pending_plan_observability


def _plan(ticker="ADA-USDC", status="active", plan_action="prepare_buy"):
    return {
        "plan_id": f"plan-{ticker}-{status}",
        "ticker": ticker,
        "status": status,
        "created_at": "2026-05-13T10:00:00Z",
        "updated_at": "2026-05-13T10:00:00Z",
        "expires_at": "2026-05-14T10:00:00Z",
        "source": "unit_test",
        "reason": "test plan",
        "trade_plan": {
            "plan_action": plan_action,
            "setup_type": "breakout_retest",
            "entry_zone_low": 0.25,
            "entry_zone_high": 0.30,
            "trigger": "price retests entry zone",
            "do_not_chase_above": 0.32,
            "stop_loss": 0.24,
            "take_profit_1": 0.34,
            "take_profit_2": 0.38,
            "invalidation": "close below support",
            "max_size_quote": 25,
            "monitoring_rules": ["require fresh judge check"],
            "confidence": 70,
            "must_not_trade_if": ["spread widens"],
            "reason": "test",
        },
        "evaluation": {
            "status": status,
            "reason": "unit test evaluation",
            "trigger_score": 0,
        },
        "safety_policy": (
            "Monitor only. Do not execute from this pending plan directly; "
            "fresh judge and risk checks are required."
        ),
    }


def _make_store(tmp_path, plans):
    state_path = tmp_path / "pending_trade_plans.json"
    log_path = tmp_path / "pending_trade_plans.jsonl"

    state_path.write_text(json.dumps({"plans": plans}), encoding="utf-8")

    params = inspect.signature(PendingTradePlanStore.__init__).parameters
    kwargs = {}

    if "path" in params:
        kwargs["path"] = state_path
    elif "state_path" in params:
        kwargs["state_path"] = state_path

    if "log_path" in params:
        kwargs["log_path"] = log_path
    if "max_records" in params:
        kwargs["max_records"] = 50
    if "ttl_hours" in params:
        kwargs["ttl_hours"] = 24
    if "min_confidence" in params:
        kwargs["min_confidence"] = 60
    if "trigger_score_threshold" in params:
        kwargs["trigger_score_threshold"] = 88
    if "max_chase_distance_pct" in params:
        kwargs["max_chase_distance_pct"] = 0.02

    return PendingTradePlanStore(**kwargs)


def test_build_pending_plan_observability_counts_statuses():
    plans = [
        _plan("ADA-USDC", "active"),
        _plan("SOL-USDC", "trigger_ready"),
        _plan("ETH-USDC", "expired"),
        _plan("BTC-USDC", "invalidated"),
    ]

    summary = build_pending_plan_observability(plans)

    assert summary["total_plans"] == 4
    assert summary["active_count"] == 1
    assert summary["trigger_ready_count"] == 1
    assert summary["final_count"] == 2
    assert summary["status_counts"]["active"] == 1
    assert summary["status_counts"]["trigger_ready"] == 1
    assert summary["status_counts"]["expired"] == 1
    assert summary["status_counts"]["invalidated"] == 1
    assert summary["actionable_trigger_ready"][0]["ticker"] == "SOL-USDC"


def test_pending_trade_plan_store_observability_summary(tmp_path):
    store = _make_store(
        tmp_path,
        [
            _plan("ADA-USDC", "active"),
            _plan("SOL-USDC", "trigger_ready"),
        ],
    )

    summary = store.observability_summary()

    assert summary["total_plans"] == 2
    assert summary["active_count"] == 1
    assert summary["trigger_ready_count"] == 1
    assert summary["status_counts"]["active"] == 1
    assert summary["status_counts"]["trigger_ready"] == 1


def test_pending_trade_plan_store_active_status_counts(tmp_path):
    store = _make_store(
        tmp_path,
        [
            _plan("ADA-USDC", "active"),
            _plan("SOL-USDC", "waiting"),
            _plan("ETH-USDC", "trigger_ready"),
            _plan("BTC-USDC", "expired"),
        ],
    )

    counts = store.active_status_counts()

    assert counts["active"] == 1
    assert counts["waiting"] == 1
    assert counts["trigger_ready"] == 1
    assert counts.get("expired", 0) == 0
