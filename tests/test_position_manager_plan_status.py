from decimal import Decimal

from bot.position_manager import PositionManager


def _position(**overrides):
    base = dict(
        ticker="SOL-USDC",
        status="open",
        entry_price="80.42",
        position_size_base="0.76349166",
        stop_price="80.3229",
        take_profit_price="81.300",
        trailing_trigger_pct="0.02",
        trailing_distance_pct="0.03",
        invalidation_mode="ema20_break",
        d2_plan_status="pending",
        d3_exit_status="pending",
    )
    base.update(overrides)
    return base


def test_ensure_minimum_risk_plan_advances_dead_pending_status_once_plan_exists():
    pm = PositionManager()
    position = _position()

    updated = pm._ensure_minimum_risk_plan(position, feature_pack={}, current_price=Decimal("80.95"))

    assert updated["d2_plan_status"] == "plan_defined"
    assert updated["d3_exit_status"] == "monitoring_no_trigger_yet"


def test_ensure_minimum_risk_plan_does_not_clobber_a_real_status_transition():
    pm = PositionManager()
    position = _position(d2_plan_status="submitted", d3_exit_status="submitted")

    updated = pm._ensure_minimum_risk_plan(position, feature_pack={}, current_price=Decimal("80.95"))

    assert updated["d2_plan_status"] == "submitted"
    assert updated["d3_exit_status"] == "submitted"


def test_evaluate_position_hold_persists_advanced_plan_status():
    pm = PositionManager()
    position = _position()

    result = pm.evaluate_position("SOL-USDC", position, feature_pack={"market": {"mid_price": "80.95"}})

    assert result["action"] == "hold"
    updated_position = result["metadata"]["updated_position"]
    assert updated_position["d2_plan_status"] == "plan_defined"
    assert updated_position["d3_exit_status"] == "monitoring_no_trigger_yet"
