from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional


@dataclass
class PositionAction:
    action: str
    reason: str
    side: str = "NONE"
    size_base: str = "0"
    size_quote: str = "0"
    stop_price: str = "0"
    take_profit_price: str = "0"
    trailing_active: bool = False
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "side": self.side,
            "size_base": self.size_base,
            "size_quote": self.size_quote,
            "stop_price": self.stop_price,
            "take_profit_price": self.take_profit_price,
            "trailing_active": self.trailing_active,
            "metadata": self.metadata or {},
        }


class PositionManager:
    def __init__(self, cfg: Any = None):
        self.min_position_base = Decimal("0.00000001")
        self.min_reduce_fraction = Decimal("0.50")
        # Generic (no setup-type match) trailing tier only -- the
        # trend/reclaim/mean-reversion tiers below stay independent of cfg.
        # cfg is the single source of truth when available (it already backs
        # the D.2 plan preview's "trailing" field, bot/phase_d2_position_executor.py,
        # so this makes position_manager.py's actual enforcement consistent
        # with what a plan already claims to use, instead of a second,
        # silently different hardcoded value).
        self.default_trailing_trigger_pct = self._to_decimal(
            getattr(cfg, "phase_d2_default_trailing_activation_pct", None), "0.02"
        )
        self.default_trailing_distance_pct = self._to_decimal(
            getattr(cfg, "phase_d2_default_trailing_distance_pct", None), "0.03"
        )
        self.default_take_profit_reduce_fraction = Decimal("0.50")

        # Nieuwe, behoudende setup-aware defaults
        self.trend_trailing_trigger_pct = Decimal("0.025")
        self.trend_trailing_distance_pct = Decimal("0.035")

        self.reclaim_trailing_trigger_pct = Decimal("0.018")
        self.reclaim_trailing_distance_pct = Decimal("0.03")

        self.meanrev_trailing_trigger_pct = Decimal("0.012")
        self.meanrev_trailing_distance_pct = Decimal("0.022")

        self.atr_stop_floor_multiplier = Decimal("1.2")
        self.atr_trailing_distance_multiplier = Decimal("1.0")
        self.urgent_warning_close_threshold = 2
        self.urgent_warning_reduce_threshold = 1
        self.near_stop_close_buffer_pct = Decimal("0.0025")
        self.near_stop_reduce_buffer_pct = Decimal("0.0060")
        self.inventory_sync_near_stop_buffer_pct = Decimal("0.0040")
        self.max_profit_giveback_pct = Decimal("0.025")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_decimal(value: Any, default: str = "0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal(default)

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        return bool(value)

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        ticker = str(ticker or "").upper().strip()
        if not ticker:
            raise ValueError("ticker mag niet leeg zijn")
        return ticker

    def _is_meaningful_position(
        self,
        base_size: Decimal,
        min_size: Optional[Decimal] = None,
    ) -> bool:
        if min_size is None:
            min_size = self.min_position_base
        return base_size > min_size

    def _safe_position_base_size(self, position: Dict[str, Any]) -> Decimal:
        return self._to_decimal(
            position.get("position_size_base", position.get("size_base", "0")),
            "0",
        )

    def _safe_position_quote_size(self, position: Dict[str, Any]) -> Decimal:
        return self._to_decimal(
            position.get("position_size_quote", position.get("size_quote", "0")),
            "0",
        )

    def _get_position_min_meaningful_base(self, position: Dict[str, Any]) -> Decimal:
        threshold = self.min_position_base
        for key in ("effective_min_trade_base", "exchange_base_min_size", "inventory_min_residual_base"):
            value = self._to_decimal(position.get(key), "0")
            if value > threshold:
                threshold = value
        return threshold

    def _clamp_sell_size(
        self,
        requested_size: Decimal,
        available_size: Decimal,
    ) -> Decimal:
        if requested_size <= Decimal("0") or available_size <= Decimal("0"):
            return Decimal("0")
        return min(requested_size, available_size)

    def _compute_reduce_size(
        self,
        position_size_base: Decimal,
        fraction: Optional[Decimal] = None,
    ) -> Decimal:
        if fraction is None or fraction <= Decimal("0") or fraction >= Decimal("1"):
            fraction = self.default_take_profit_reduce_fraction

        reduce_size = position_size_base * fraction

        if reduce_size <= self.min_position_base:
            return Decimal("0")

        remaining = position_size_base - reduce_size

        if remaining <= self.min_position_base:
            return position_size_base

        return reduce_size

    def _build_action(
        self,
        *,
        action: str,
        reason: str,
        ticker: str,
        updated_position: Dict[str, Any],
        current_price: Decimal,
        pnl_pct: Decimal,
        side: str = "NONE",
        size_base: Decimal = Decimal("0"),
        size_quote: Decimal = Decimal("0"),
        stop_price: Decimal = Decimal("0"),
        take_profit_price: Decimal = Decimal("0"),
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = {
            "ticker": ticker,
            "current_price": str(current_price),
            "entry_price": str(self._to_decimal(updated_position.get("entry_price"), "0")),
            "pnl_pct": str(pnl_pct),
            "updated_position": updated_position,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        return PositionAction(
            action=action,
            reason=reason,
            side=side,
            size_base=str(size_base),
            size_quote=str(size_quote),
            stop_price=str(stop_price),
            take_profit_price=str(take_profit_price),
            trailing_active=self._to_bool(updated_position.get("trailing_active"), False),
            metadata=metadata,
        ).to_dict()

    def _get_position_setup_type(self, position: Dict[str, Any]) -> str:
        raw = str(position.get("setup_type", "")).strip().lower()
        aliases = {
            "trend": "trend_continuation",
            "trend_continuation": "trend_continuation",
            "continuation": "trend_continuation",
            "momentum": "trend_continuation",
            "reclaim": "reclaim_reversal",
            "reversal": "reclaim_reversal",
            "reclaim_reversal": "reclaim_reversal",
            "mean_reversion": "mean_reversion",
            "meanrev": "mean_reversion",
            "mean reversion": "mean_reversion",
        }
        return aliases.get(raw, "unclear")

    # state_store.py unconditionally back-fills every position with
    # "trailing_trigger_pct": "0.02" / "trailing_distance_pct": "0.03" at
    # creation and on every defaults-ensure pass (it has no cfg access and
    # never did) -- so those two exact legacy values mean "never actually
    # customized," not "a deliberate per-position override." Treating them
    # as real overrides would make the setup-type tiers below (and the
    # cfg-backed generic default) permanently unreachable for every position,
    # which is what happened before this fix.
    _LEGACY_BACKFILLED_TRIGGER_PCT = Decimal("0.02")
    _LEGACY_BACKFILLED_DISTANCE_PCT = Decimal("0.03")

    def _get_setup_trailing_trigger_pct(self, position: Dict[str, Any]) -> Decimal:
        custom = self._to_decimal(position.get("trailing_trigger_pct"), "0")
        if custom > Decimal("0") and custom != self._LEGACY_BACKFILLED_TRIGGER_PCT:
            return custom

        setup_type = self._get_position_setup_type(position)
        if setup_type == "trend_continuation":
            return self.trend_trailing_trigger_pct
        if setup_type == "reclaim_reversal":
            return self.reclaim_trailing_trigger_pct
        if setup_type == "mean_reversion":
            return self.meanrev_trailing_trigger_pct
        return self.default_trailing_trigger_pct

    def _get_setup_trailing_distance_pct(self, position: Dict[str, Any]) -> Decimal:
        custom = self._to_decimal(position.get("trailing_distance_pct"), "0")
        if custom > Decimal("0") and custom != self._LEGACY_BACKFILLED_DISTANCE_PCT:
            return custom

        setup_type = self._get_position_setup_type(position)
        if setup_type == "trend_continuation":
            return self.trend_trailing_distance_pct
        if setup_type == "reclaim_reversal":
            return self.reclaim_trailing_distance_pct
        if setup_type == "mean_reversion":
            return self.meanrev_trailing_distance_pct
        return self.default_trailing_distance_pct

    def _get_1h_atr(self, feature_pack: Dict[str, Any]) -> Decimal:
        one_h = self._get_1h_indicators(feature_pack)
        for key in ("atr_14", "atr", "atr14"):
            value = self._to_decimal(one_h.get(key), "0")
            if value > Decimal("0"):
                return value
        return Decimal("0")

    def _get_structure_support(self, feature_pack: Dict[str, Any]) -> Decimal:
        structure = self._get_structure(feature_pack)
        candidate_keys = [
            "support_1h",
            "nearest_support",
            "range_low",
            "swing_low_1h",
            "last_higher_low_1h",
        ]
        for key in candidate_keys:
            value = self._to_decimal(structure.get(key), "0")
            if value > Decimal("0"):
                return value
        return Decimal("0")

    def _compute_adaptive_stop_floor(
        self,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
        current_price: Decimal,
    ) -> Decimal:
        """
        Houdt trailing/logische stop boven een te losse default,
        maar respecteert ook structuur + volatiliteit als dat beschikbaar is.
        """
        support = self._get_structure_support(feature_pack)
        atr_1h = self._get_1h_atr(feature_pack)

        candidates = []

        if support > Decimal("0"):
            candidates.append(support)

        if atr_1h > Decimal("0") and current_price > Decimal("0"):
            atr_floor = current_price - (atr_1h * self.atr_stop_floor_multiplier)
            if atr_floor > Decimal("0"):
                candidates.append(atr_floor)

        existing_stop = self._to_decimal(position.get("stop_price"), "0")
        if existing_stop > Decimal("0"):
            candidates.append(existing_stop)

        if not candidates:
            return Decimal("0")

        return max(candidates)

    def _compute_take_profit_reduce_fraction(
        self,
        position: Dict[str, Any],
        pnl_pct: Decimal,
    ) -> Decimal:
        setup_type = self._get_position_setup_type(position)

        if setup_type == "trend_continuation":
            if pnl_pct >= Decimal("0.08"):
                return Decimal("0.35")
            return Decimal("0.40")

        if setup_type == "reclaim_reversal":
            return Decimal("0.50")

        if setup_type == "mean_reversion":
            return Decimal("0.60")

        return self.default_take_profit_reduce_fraction

    def _ensure_minimum_risk_plan(
        self,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
        current_price: Decimal,
    ) -> Dict[str, Any]:
        updated_position = dict(position)
        entry_price = self._to_decimal(updated_position.get("entry_price"), "0")
        if entry_price <= Decimal("0") or current_price <= Decimal("0"):
            return updated_position

        setup_type = self._get_position_setup_type(updated_position)
        one_h = self._get_1h_indicators(feature_pack)
        support = self._get_structure_support(feature_pack)
        atr_1h = self._get_1h_atr(feature_pack)
        ema20_1h = self._to_decimal(one_h.get("ema_20"), "0")
        ema50_1h = self._to_decimal(one_h.get("ema_50"), "0")
        bb_mid_1h = self._to_decimal(one_h.get("bb_mid"), "0")

        if setup_type == "trend_continuation":
            fallback_stop_mult = Decimal("0.97")
            reward_mult = Decimal("2.0")
            invalidation_mode = "ema20_break"
        elif setup_type == "reclaim_reversal":
            fallback_stop_mult = Decimal("0.975")
            reward_mult = Decimal("1.6")
            invalidation_mode = "ema20_break"
        elif setup_type == "mean_reversion":
            fallback_stop_mult = Decimal("0.982")
            reward_mult = Decimal("1.25")
            invalidation_mode = "range_low_break"
        else:
            fallback_stop_mult = Decimal("0.97")
            reward_mult = Decimal("1.5")
            invalidation_mode = "ema20_break"

        existing_stop = self._to_decimal(updated_position.get("stop_price"), "0")
        if existing_stop <= Decimal("0"):
            stop_candidates = [value for value in [support, ema20_1h, ema50_1h] if value > Decimal("0") and value < entry_price]
            if atr_1h > Decimal("0"):
                atr_floor = entry_price - (atr_1h * self.atr_stop_floor_multiplier)
                if atr_floor > Decimal("0") and atr_floor < entry_price:
                    stop_candidates.append(atr_floor)
            stop_candidates.append(entry_price * fallback_stop_mult)
            existing_stop = max(stop_candidates) if stop_candidates else (entry_price * fallback_stop_mult)
            if existing_stop >= entry_price:
                existing_stop = entry_price * fallback_stop_mult
            updated_position["stop_price"] = str(existing_stop)

        existing_tp = self._to_decimal(updated_position.get("take_profit_price"), "0")
        if existing_tp <= Decimal("0"):
            risk_distance = entry_price - existing_stop
            if risk_distance <= Decimal("0"):
                risk_distance = entry_price * (Decimal("1") - fallback_stop_mult)
            take_profit_price = entry_price + (risk_distance * reward_mult)
            if setup_type == "mean_reversion" and bb_mid_1h > entry_price:
                take_profit_price = min(take_profit_price, bb_mid_1h)
            updated_position["take_profit_price"] = str(take_profit_price)

        if self._to_decimal(updated_position.get("trailing_trigger_pct"), "0") <= Decimal("0"):
            updated_position["trailing_trigger_pct"] = str(self._get_setup_trailing_trigger_pct(updated_position))

        if self._to_decimal(updated_position.get("trailing_distance_pct"), "0") <= Decimal("0"):
            updated_position["trailing_distance_pct"] = str(self._get_setup_trailing_distance_pct(updated_position))

        if not str(updated_position.get("invalidation_mode", "")).strip():
            updated_position["invalidation_mode"] = invalidation_mode

        if not updated_position.get("position_plan_status"):
            updated_position["position_plan_status"] = "initialized_in_position_manager"

        # state_store.py backfills these to a literal "pending" once at position
        # creation and nothing else in the codebase ever updates them (confirmed
        # by grep) -- so they sit on "pending" forever even though, by this
        # point, stop/take-profit/trailing/invalidation are all defined and
        # every cycle actively re-evaluates them (see evaluate_position below).
        # An eternal "pending" reads as "no exit plan was ever made" on the
        # dashboard, which is wrong; reflect that a concrete plan exists and is
        # under reactive monitoring. _maybe_route_full_workflow_position_exit_to_d3
        # (strategy_engine.py) advances d3_exit_status further once a real
        # close/reduce is actually submitted.
        if updated_position.get("d2_plan_status") in (None, "", "pending"):
            updated_position["d2_plan_status"] = "plan_defined"
        if updated_position.get("d3_exit_status") in (None, "", "pending"):
            updated_position["d3_exit_status"] = "monitoring_no_trigger_yet"

        return updated_position

    def refresh_position_extremes(
        self,
        position: Dict[str, Any],
        current_price: Decimal,
    ) -> Dict[str, Any]:
        updated = dict(position)

        highest = self._to_decimal(updated.get("highest_price_seen"), "0")
        lowest = self._to_decimal(updated.get("lowest_price_seen"), "0")

        if highest <= Decimal("0") or current_price > highest:
            highest = current_price

        if lowest <= Decimal("0") or current_price < lowest:
            lowest = current_price

        updated["highest_price_seen"] = str(highest)
        updated["lowest_price_seen"] = str(lowest)
        updated["updated_at"] = self._now_iso()

        return updated

    def should_activate_trailing(
        self,
        position: Dict[str, Any],
        current_price: Decimal,
    ) -> bool:
        if self._to_bool(position.get("trailing_active"), False):
            return True

        entry_price = self._to_decimal(position.get("entry_price"), "0")
        if entry_price <= Decimal("0"):
            return False

        trigger_pct = self._get_setup_trailing_trigger_pct(position)
        if trigger_pct <= Decimal("0"):
            trigger_pct = self.default_trailing_trigger_pct

        pnl_pct = (current_price - entry_price) / entry_price
        return pnl_pct >= trigger_pct

    def compute_trailing_stop(
        self,
        position: Dict[str, Any],
        current_price: Decimal,
    ) -> Decimal:
        trailing_active = self._to_bool(position.get("trailing_active"), False)
        if not trailing_active:
            return self._to_decimal(position.get("stop_price"), "0")

        highest = self._to_decimal(position.get("highest_price_seen"), "0")
        if highest <= Decimal("0"):
            highest = current_price

        trailing_distance_pct = self._get_setup_trailing_distance_pct(position)
        if trailing_distance_pct <= Decimal("0"):
            trailing_distance_pct = self.default_trailing_distance_pct

        trailing_stop = highest * (Decimal("1") - trailing_distance_pct)

        existing_stop = self._to_decimal(position.get("stop_price"), "0")
        if existing_stop > Decimal("0"):
            return max(existing_stop, trailing_stop)

        return trailing_stop

    def compute_unrealized_pnl_pct(
        self,
        position: Dict[str, Any],
        current_price: Decimal,
    ) -> Decimal:
        entry_price = self._to_decimal(position.get("entry_price"), "0")
        if entry_price <= Decimal("0"):
            return Decimal("0")
        return (current_price - entry_price) / entry_price

    def _get_current_price(self, feature_pack: Dict[str, Any]) -> Decimal:
        market = feature_pack.get("market", {})
        return self._to_decimal(
            market.get("mid_price") or market.get("best_bid") or market.get("best_ask"),
            "0",
        )

    def _get_1h_indicators(self, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        return feature_pack.get("indicators", {}).get("1h", {})

    def _get_structure(self, feature_pack: Dict[str, Any]) -> Dict[str, Any]:
        return feature_pack.get("structure", {}) or {}

    def _check_stop_loss(
        self,
        ticker: str,
        position: Dict[str, Any],
        current_price: Decimal,
        pnl_pct: Decimal,
    ) -> Optional[Dict[str, Any]]:
        stop_price = self._to_decimal(position.get("stop_price"), "0")
        position_size_base = self._safe_position_base_size(position)

        if stop_price > Decimal("0") and current_price <= stop_price:
            size_base = self._clamp_sell_size(position_size_base, position_size_base)
            if size_base <= Decimal("0"):
                return None

            return self._build_action(
                action="close",
                reason="stop_loss_hit",
                ticker=ticker,
                updated_position=position,
                current_price=current_price,
                pnl_pct=pnl_pct,
                side="SELL",
                size_base=size_base,
                stop_price=stop_price,
            )

        return None

    def _get_heartbeat_warning_count(self, position: Dict[str, Any]) -> int:
        try:
            return int(position.get("heartbeat_warning_count", 0) or 0)
        except Exception:
            return 0

    def _get_position_watch_warning_count(self, position: Dict[str, Any]) -> int:
        try:
            return int(position.get("position_watch_warning_count", 0) or 0)
        except Exception:
            return 0

    def _combined_warning_pressure(self, position: Dict[str, Any]) -> int:
        return max(
            self._get_heartbeat_warning_count(position),
            self._get_position_watch_warning_count(position),
        )

    def _is_inventory_sync_position(self, position: Dict[str, Any]) -> bool:
        entry_reason = str(position.get("entry_reason", "")).strip().lower()
        invalidation_mode = str(position.get("invalidation_mode", "")).strip().lower()
        notes = str(position.get("notes", "")).strip().lower()
        return any(
            token in entry_reason or token in invalidation_mode or token in notes
            for token in ["inventory_sync", "exchange_inventory_sync", "synced_from_live_exchange_inventory"]
        )

    def _get_distance_to_stop_pct(self, current_price: Decimal, stop_price: Decimal) -> Optional[Decimal]:
        if current_price <= Decimal("0") or stop_price <= Decimal("0"):
            return None
        return (current_price - stop_price) / stop_price

    def _get_drawdown_from_peak_pct(
        self,
        position: Dict[str, Any],
        current_price: Decimal,
    ) -> Decimal:
        highest = self._to_decimal(position.get("highest_price_seen"), "0")
        if highest <= Decimal("0") or current_price <= Decimal("0"):
            return Decimal("0")
        return (current_price - highest) / highest

    def _check_urgent_open_position_risk(
        self,
        ticker: str,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
        current_price: Decimal,
        pnl_pct: Decimal,
    ) -> Optional[Dict[str, Any]]:
        stop_price = self._to_decimal(position.get("stop_price"), "0")
        if stop_price <= Decimal("0"):
            return None

        position_size_base = self._safe_position_base_size(position)
        if position_size_base <= Decimal("0"):
            return None

        one_h = self._get_1h_indicators(feature_pack)
        structure = self._get_structure(feature_pack)

        ema20_1h = self._to_decimal(one_h.get("ema_20"), "0")
        ema50_1h = self._to_decimal(one_h.get("ema_50"), "0")
        rsi_1h = self._to_decimal(one_h.get("rsi_14"), "0")

        lower_highs_1h = self._to_bool(structure.get("lower_highs_1h"), False)
        lower_lows_1h = self._to_bool(structure.get("lower_lows_1h"), False)
        higher_lows_1h = self._to_bool(structure.get("higher_lows_1h"), False)

        below_fast_1h = (
            ema20_1h > Decimal("0")
            and ema50_1h > Decimal("0")
            and current_price < ema20_1h
            and current_price < ema50_1h
        )
        adverse_structure = lower_highs_1h and lower_lows_1h and not higher_lows_1h
        warning_pressure = self._combined_warning_pressure(position)
        drawdown_from_peak_pct = self._get_drawdown_from_peak_pct(position, current_price)
        distance_to_stop_pct = self._get_distance_to_stop_pct(current_price, stop_price)
        inventory_sync_position = self._is_inventory_sync_position(position)
        setup_type = self._get_position_setup_type(position)

        close_buffer = self.inventory_sync_near_stop_buffer_pct if inventory_sync_position else self.near_stop_close_buffer_pct
        reduce_buffer = max(close_buffer, self.near_stop_reduce_buffer_pct)

        if distance_to_stop_pct is not None and distance_to_stop_pct <= Decimal("0"):
            return self._build_action(
                action="close",
                reason="urgent_stop_breached",
                ticker=ticker,
                updated_position=position,
                current_price=current_price,
                pnl_pct=pnl_pct,
                side="SELL",
                size_base=position_size_base,
                stop_price=stop_price,
                extra_metadata={
                    "distance_to_stop_pct": str(distance_to_stop_pct),
                    "warning_pressure": warning_pressure,
                    "inventory_sync_position": inventory_sync_position,
                },
            )

        if distance_to_stop_pct is not None and distance_to_stop_pct <= close_buffer and (adverse_structure or below_fast_1h or warning_pressure >= self.urgent_warning_close_threshold):
            return self._build_action(
                action="close",
                reason="near_stop_with_bearish_confirmation",
                ticker=ticker,
                updated_position=position,
                current_price=current_price,
                pnl_pct=pnl_pct,
                side="SELL",
                size_base=position_size_base,
                stop_price=stop_price,
                extra_metadata={
                    "distance_to_stop_pct": str(distance_to_stop_pct),
                    "warning_pressure": warning_pressure,
                    "inventory_sync_position": inventory_sync_position,
                    "adverse_structure": adverse_structure,
                    "below_fast_1h": below_fast_1h,
                },
            )

        if warning_pressure >= self.urgent_warning_close_threshold and adverse_structure and below_fast_1h:
            return self._build_action(
                action="close",
                reason="repeated_warnings_with_structure_breakdown",
                ticker=ticker,
                updated_position=position,
                current_price=current_price,
                pnl_pct=pnl_pct,
                side="SELL",
                size_base=position_size_base,
                extra_metadata={
                    "warning_pressure": warning_pressure,
                    "drawdown_from_peak_pct": str(drawdown_from_peak_pct),
                    "setup_type": setup_type,
                },
            )

        if drawdown_from_peak_pct <= (-self.max_profit_giveback_pct) and (adverse_structure or below_fast_1h):
            if pnl_pct <= Decimal("0") or warning_pressure >= self.urgent_warning_close_threshold:
                return self._build_action(
                    action="close",
                    reason="profit_giveback_with_bearish_followthrough",
                    ticker=ticker,
                    updated_position=position,
                    current_price=current_price,
                    pnl_pct=pnl_pct,
                    side="SELL",
                    size_base=position_size_base,
                    extra_metadata={
                        "warning_pressure": warning_pressure,
                        "drawdown_from_peak_pct": str(drawdown_from_peak_pct),
                        "setup_type": setup_type,
                    },
                )

            reduce_size = self._compute_reduce_size(position_size_base, Decimal("0.50"))
            if reduce_size > Decimal("0"):
                return self._build_action(
                    action="reduce",
                    reason="profit_giveback_reduce_risk",
                    ticker=ticker,
                    updated_position=position,
                    current_price=current_price,
                    pnl_pct=pnl_pct,
                    side="SELL",
                    size_base=reduce_size,
                    extra_metadata={
                        "warning_pressure": warning_pressure,
                        "drawdown_from_peak_pct": str(drawdown_from_peak_pct),
                        "setup_type": setup_type,
                    },
                )

        if distance_to_stop_pct is not None and distance_to_stop_pct <= reduce_buffer and below_fast_1h and (warning_pressure >= self.urgent_warning_reduce_threshold or rsi_1h < Decimal("45")):
            reduce_size = self._compute_reduce_size(position_size_base, Decimal("0.50"))
            if reduce_size > Decimal("0"):
                action = "reduce" if reduce_size < position_size_base else "close"
                return self._build_action(
                    action=action,
                    reason="tighten_risk_near_stop",
                    ticker=ticker,
                    updated_position=position,
                    current_price=current_price,
                    pnl_pct=pnl_pct,
                    side="SELL",
                    size_base=reduce_size,
                    stop_price=stop_price,
                    extra_metadata={
                        "distance_to_stop_pct": str(distance_to_stop_pct),
                        "warning_pressure": warning_pressure,
                        "setup_type": setup_type,
                    },
                )

        return None

    def _check_take_profit(
        self,
        ticker: str,
        position: Dict[str, Any],
        current_price: Decimal,
        pnl_pct: Decimal,
    ) -> Optional[Dict[str, Any]]:
        take_profit_price = self._to_decimal(position.get("take_profit_price"), "0")
        position_size_base = self._safe_position_base_size(position)
        partial_taken = self._to_bool(position.get("partial_take_profit_taken"), False)

        if partial_taken:
            return None

        if take_profit_price > Decimal("0") and current_price >= take_profit_price:
            reduce_fraction = self._compute_take_profit_reduce_fraction(position, pnl_pct)
            reduce_size = self._compute_reduce_size(position_size_base, reduce_fraction)

            if reduce_size <= Decimal("0"):
                return None

            action = "reduce"
            if reduce_size >= position_size_base:
                action = "close"

            updated_position = dict(position)
            updated_position["partial_take_profit_taken"] = True
            updated_position["updated_at"] = self._now_iso()

            return self._build_action(
                action=action,
                reason="take_profit_hit",
                ticker=ticker,
                updated_position=updated_position,
                current_price=current_price,
                pnl_pct=pnl_pct,
                side="SELL",
                size_base=reduce_size,
                take_profit_price=take_profit_price,
                extra_metadata={
                    "reduce_fraction": str(reduce_fraction),
                    "setup_type": self._get_position_setup_type(position),
                },
            )

        return None

    def _check_judge_exit(
        self,
        ticker: str,
        position: Dict[str, Any],
        current_price: Decimal,
        pnl_pct: Decimal,
        judge: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not judge:
            return None

        decision = str(judge.get("decision", "")).lower().strip()
        side = str(judge.get("side", "")).upper().strip()
        strategy = str(judge.get("strategy", "")).lower().strip()
        reasons = judge.get("reasons", [])
        position_size_base = self._safe_position_base_size(position)

        if decision not in {"close_position", "reduce_size"}:
            return None

        if side not in {"SELL", "NONE"}:
            return None

        if decision == "close_position":
            size_base = position_size_base
            action = "close"
        else:
            requested_size_quote = self._to_decimal(judge.get("size_quote"), "0")
            if requested_size_quote > Decimal("0") and current_price > Decimal("0"):
                requested_size_base = requested_size_quote / current_price
                size_base = self._clamp_sell_size(requested_size_base, position_size_base)
            else:
                size_base = self._compute_reduce_size(position_size_base)

            if size_base >= position_size_base:
                action = "close"
            else:
                action = "reduce"

        if size_base <= Decimal("0"):
            return None

        return self._build_action(
            action=action,
            reason=f"judge_{decision}",
            ticker=ticker,
            updated_position=position,
            current_price=current_price,
            pnl_pct=pnl_pct,
            side="SELL",
            size_base=size_base,
            extra_metadata={
                "strategy": strategy,
                "judge_reasons": reasons,
                "judge_confidence": judge.get("confidence"),
                "judge_decision": decision,
            },
        )

    def _check_invalidation(
        self,
        ticker: str,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
        current_price: Decimal,
        pnl_pct: Decimal,
    ) -> Optional[Dict[str, Any]]:
        one_h = self._get_1h_indicators(feature_pack)
        structure = self._get_structure(feature_pack)
        setup_type = self._get_position_setup_type(position)

        ema20_1h = self._to_decimal(one_h.get("ema_20"), "0")
        ema50_1h = self._to_decimal(one_h.get("ema_50"), "0")
        rsi_1h = self._to_decimal(one_h.get("rsi_14"), "0")
        atr_1h = self._get_1h_atr(feature_pack)

        lower_highs_1h = self._to_bool(structure.get("lower_highs_1h"), False)
        lower_lows_1h = self._to_bool(structure.get("lower_lows_1h"), False)

        invalidation_mode = str(position.get("invalidation_mode", "ema20_break")).lower().strip()
        position_size_base = self._safe_position_base_size(position)

        if invalidation_mode == "ema20_break":
            if ema20_1h > Decimal("0") and current_price < ema20_1h and pnl_pct > Decimal("0.01"):
                reduce_fraction = Decimal("0.35") if setup_type == "trend_continuation" else Decimal("0.50")
                reduce_size = self._compute_reduce_size(position_size_base, reduce_fraction)
                if reduce_size <= Decimal("0"):
                    return None

                action = "reduce"
                if reduce_size >= position_size_base:
                    action = "close"

                return self._build_action(
                    action=action,
                    reason="invalidation_ema20_break",
                    ticker=ticker,
                    updated_position=position,
                    current_price=current_price,
                    pnl_pct=pnl_pct,
                    side="SELL",
                    size_base=reduce_size,
                    extra_metadata={
                        "ema20_1h": str(ema20_1h),
                        "setup_type": setup_type,
                    },
                )

        if invalidation_mode == "ema50_break":
            if ema50_1h > Decimal("0") and current_price < ema50_1h and pnl_pct < Decimal("0"):
                return self._build_action(
                    action="close",
                    reason="invalidation_ema50_break",
                    ticker=ticker,
                    updated_position=position,
                    current_price=current_price,
                    pnl_pct=pnl_pct,
                    side="SELL",
                    size_base=position_size_base,
                    extra_metadata={
                        "ema50_1h": str(ema50_1h),
                        "setup_type": setup_type,
                    },
                )

        if lower_highs_1h and lower_lows_1h and pnl_pct < Decimal("0"):
            return self._build_action(
                action="close",
                reason="structure_breakdown_1h",
                ticker=ticker,
                updated_position=position,
                current_price=current_price,
                pnl_pct=pnl_pct,
                side="SELL",
                size_base=position_size_base,
                extra_metadata={
                    "lower_highs_1h": lower_highs_1h,
                    "lower_lows_1h": lower_lows_1h,
                    "setup_type": setup_type,
                },
            )

        if setup_type == "mean_reversion":
            # Mean reversion hoort sneller winst te nemen / sneller af te bouwen bij uitputting
            if rsi_1h >= Decimal("68") and pnl_pct > Decimal("0.01"):
                reduce_size = self._compute_reduce_size(position_size_base, Decimal("0.60"))
                if reduce_size <= Decimal("0"):
                    return None

                action = "reduce"
                if reduce_size >= position_size_base:
                    action = "close"

                return self._build_action(
                    action=action,
                    reason="meanrev_overextended_take_partial",
                    ticker=ticker,
                    updated_position=position,
                    current_price=current_price,
                    pnl_pct=pnl_pct,
                    side="SELL",
                    size_base=reduce_size,
                    extra_metadata={
                        "rsi_1h": str(rsi_1h),
                        "setup_type": setup_type,
                    },
                )

        if rsi_1h >= Decimal("72") and pnl_pct > Decimal("0.02"):
            reduce_fraction = Decimal("0.35") if setup_type == "trend_continuation" else Decimal("0.50")
            reduce_size = self._compute_reduce_size(position_size_base, reduce_fraction)
            if reduce_size <= Decimal("0"):
                return None

            action = "reduce"
            if reduce_size >= position_size_base:
                action = "close"

            return self._build_action(
                action=action,
                reason="rsi_overextended_take_partial",
                ticker=ticker,
                updated_position=position,
                current_price=current_price,
                pnl_pct=pnl_pct,
                side="SELL",
                size_base=reduce_size,
                extra_metadata={
                    "rsi_1h": str(rsi_1h),
                    "atr_1h": str(atr_1h),
                    "setup_type": setup_type,
                },
            )

        return None

    def evaluate_position(
        self,
        ticker: str,
        position: Dict[str, Any],
        feature_pack: Dict[str, Any],
        judge: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        updated_position = dict(position)

        current_price = self._get_current_price(feature_pack)
        if current_price <= Decimal("0"):
            return PositionAction(
                action="hold",
                reason="current_price_unavailable",
                metadata={"ticker": ticker},
            ).to_dict()

        position_size_base = self._safe_position_base_size(updated_position)
        min_meaningful_base = self._get_position_min_meaningful_base(updated_position)

        if not self._is_meaningful_position(position_size_base, min_meaningful_base):
            return PositionAction(
                action="hold",
                reason="no_meaningful_position",
                metadata={
                    "ticker": ticker,
                    "position_size_base": str(position_size_base),
                    "min_meaningful_base": str(min_meaningful_base),
                },
            ).to_dict()

        updated_position = self._ensure_minimum_risk_plan(updated_position, feature_pack, current_price)
        updated_position = self.refresh_position_extremes(updated_position, current_price)

        if self.should_activate_trailing(updated_position, current_price):
            updated_position["trailing_active"] = True

        computed_stop = self.compute_trailing_stop(updated_position, current_price)
        adaptive_floor = self._compute_adaptive_stop_floor(updated_position, feature_pack, current_price)

        existing_stop = self._to_decimal(updated_position.get("stop_price"), "0")
        best_stop = computed_stop

        if adaptive_floor > best_stop:
            best_stop = adaptive_floor
        if existing_stop > best_stop:
            best_stop = existing_stop

        if best_stop > Decimal("0"):
            updated_position["stop_price"] = str(best_stop)

        pnl_pct = self.compute_unrealized_pnl_pct(updated_position, current_price)

        stop_check = self._check_stop_loss(ticker, updated_position, current_price, pnl_pct)
        if stop_check:
            return stop_check

        urgent_risk_check = self._check_urgent_open_position_risk(
            ticker,
            updated_position,
            feature_pack,
            current_price,
            pnl_pct,
        )
        if urgent_risk_check:
            return urgent_risk_check

        take_profit_check = self._check_take_profit(ticker, updated_position, current_price, pnl_pct)
        if take_profit_check:
            return take_profit_check

        judge_check = self._check_judge_exit(ticker, updated_position, current_price, pnl_pct, judge)
        if judge_check:
            return judge_check

        invalidation_check = self._check_invalidation(
            ticker,
            updated_position,
            feature_pack,
            current_price,
            pnl_pct,
        )
        if invalidation_check:
            return invalidation_check

        return self._build_action(
            action="hold",
            reason="position_valid",
            ticker=ticker,
            updated_position=updated_position,
            current_price=current_price,
            pnl_pct=pnl_pct,
            side="NONE",
            size_base=Decimal("0"),
            extra_metadata={
                "setup_type": self._get_position_setup_type(updated_position),
                "adaptive_stop_floor": str(adaptive_floor),
            },
        )