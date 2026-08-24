from decimal import Decimal
from types import SimpleNamespace

from bot.position_manager import PositionManager


def _cfg(**overrides):
    base = dict(
        phase_d2_default_trailing_activation_pct="0.0250",
        phase_d2_default_trailing_distance_pct="0.0180",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _position(**overrides):
    base = dict(
        ticker="BTC-USDC",
        status="open",
        entry_price="100",
        # state_store.py backfills every position with these two exact
        # values regardless of setup -- they must not be mistaken for a
        # deliberate per-position override.
        trailing_trigger_pct="0.02",
        trailing_distance_pct="0.03",
    )
    base.update(overrides)
    return base


def test_no_cfg_keeps_historical_hardcoded_defaults():
    pm = PositionManager()
    assert pm.default_trailing_trigger_pct == Decimal("0.02")
    assert pm.default_trailing_distance_pct == Decimal("0.03")


def test_cfg_becomes_the_generic_tier_default():
    pm = PositionManager(cfg=_cfg())
    assert pm.default_trailing_trigger_pct == Decimal("0.0250")
    assert pm.default_trailing_distance_pct == Decimal("0.0180")


def test_legacy_backfilled_position_value_does_not_shadow_cfg_default():
    # Before this fix, every position's own trailing_trigger_pct/_distance_pct
    # (state_store.py always backfills "0.02"/"0.03") would win as a "custom
    # override," making both the setup-type tiers and this cfg-backed default
    # permanently unreachable.
    pm = PositionManager(cfg=_cfg())
    position = _position(setup_type="unclear")
    assert pm._get_setup_trailing_trigger_pct(position) == Decimal("0.0250")
    assert pm._get_setup_trailing_distance_pct(position) == Decimal("0.0180")


def test_genuine_custom_override_still_wins_over_cfg_default():
    pm = PositionManager(cfg=_cfg())
    position = _position(setup_type="unclear", trailing_trigger_pct="0.05", trailing_distance_pct="0.06")
    assert pm._get_setup_trailing_trigger_pct(position) == Decimal("0.05")
    assert pm._get_setup_trailing_distance_pct(position) == Decimal("0.06")


def test_setup_specific_tiers_are_not_affected_by_cfg():
    pm = PositionManager(cfg=_cfg())
    position = _position(setup_type="trend_continuation")
    assert pm._get_setup_trailing_trigger_pct(position) == pm.trend_trailing_trigger_pct
    assert pm._get_setup_trailing_distance_pct(position) == pm.trend_trailing_distance_pct
    assert pm.trend_trailing_trigger_pct == Decimal("0.025")


def test_should_activate_trailing_uses_cfg_backed_generic_trigger():
    pm = PositionManager(cfg=_cfg())
    position = _position(setup_type="unclear", entry_price="100")
    # 2% move: below the cfg-backed 2.5% trigger -- must not activate yet.
    assert pm.should_activate_trailing(position, Decimal("102")) is False
    # 2.6% move: clears the cfg-backed 2.5% trigger.
    assert pm.should_activate_trailing(position, Decimal("102.6")) is True


def test_compute_trailing_stop_uses_cfg_backed_generic_distance():
    pm = PositionManager(cfg=_cfg())
    position = _position(setup_type="unclear", entry_price="100", trailing_active=True, highest_price_seen="110", stop_price="0")
    # cfg-backed distance is 1.8%: 110 * (1 - 0.018) = 108.02
    assert pm.compute_trailing_stop(position, Decimal("109")) == Decimal("110") * (Decimal("1") - Decimal("0.0180"))
