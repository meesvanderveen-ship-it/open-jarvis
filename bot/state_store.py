from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from bot.atomic_io import atomic_write_json
from bot.phase_d3_open_exit_position_guard import (
    build_open_d3_exit_position_guard_report,
    logical_position_id_candidates,
)

STATE_DIR = Path("state")


class StateStore:
    def __init__(self):
        self.cooldowns_file = STATE_DIR / "cooldowns.json"
        self.daily_file = STATE_DIR / "daily_pnl.json"
        self.positions_file = STATE_DIR / "positions.json"

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """
        Maak payloads veilig voor json.dumps().
        Belangrijkste fix: Decimal -> string.
        """
        if isinstance(value, Decimal):
            return str(value)

        if isinstance(value, Path):
            return str(value)

        if isinstance(value, datetime):
            return value.isoformat()

        if isinstance(value, dict):
            sanitized: Dict[str, Any] = {}
            for k, v in value.items():
                sanitized[str(k)] = StateStore._json_safe(v)
            return sanitized

        if isinstance(value, (list, tuple, set)):
            return [StateStore._json_safe(v) for v in value]

        return value

    def _load_json(self, path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            return default

        try:
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                return default
            data = json.loads(raw)
            if not isinstance(data, dict):
                return default
            return data
        except Exception:
            return default

    def _save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        safe_payload = self._json_safe(payload)
        atomic_write_json(path, safe_payload, sort_keys=False)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        ticker = str(ticker).upper().strip()
        if not ticker:
            raise ValueError("ticker mag niet leeg zijn")
        return ticker

    @staticmethod
    def _first_linked_position_id(position: Dict[str, Any]) -> str:
        for candidate in logical_position_id_candidates(position):
            text = str(candidate or "").strip()
            if text:
                return text
        return ""

    def _preserve_open_position_due_to_open_d3_exit(
        self,
        *,
        ticker: str,
        current: Dict[str, Any],
        merged: Dict[str, Any],
        guard_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        preserved = dict(merged)
        preserved["status"] = "open"
        preserved["position_size_base"] = str(current.get("position_size_base") or preserved.get("position_size_base") or "0")
        preserved["position_size_quote"] = str(current.get("position_size_quote") or preserved.get("position_size_quote") or "0")
        preserved["bot_managed_base"] = str(current.get("bot_managed_base") or preserved.get("bot_managed_base") or preserved["position_size_base"])
        if "reserved_base_open_exit_orders" in current or "reserved_base_open_exit_orders" in preserved:
            preserved["reserved_base_open_exit_orders"] = str(
                current.get("reserved_base_open_exit_orders")
                or preserved.get("reserved_base_open_exit_orders")
                or "0"
            )
        preserved["monitoring_enabled"] = True
        preserved["close_time"] = current.get("close_time")
        preserved["closed_at"] = current.get("closed_at")
        preserved["close_reason"] = str(current.get("close_reason") or "")
        preserved["synthetic_closed_at"] = current.get("synthetic_closed_at")
        preserved["synthetic_close_reason"] = str(current.get("synthetic_close_reason") or "")
        preserved["last_heartbeat_status"] = "open"
        preserved["last_heartbeat_reason"] = "guarded_open_d3_exit_reservation"
        preserved["last_position_close_guard_status"] = str(guard_report.get("guard_status") or "")
        preserved["last_position_close_guard_reason"] = str(guard_report.get("reason") or "")
        preserved["last_guard_version"] = str(guard_report.get("guard_version") or "")
        preserved["last_guard_checked_at"] = str(guard_report.get("generated_at") or self._now_iso())
        preserved["last_guard_match_strategy"] = str(guard_report.get("last_guard_match_strategy") or "")
        preserved["last_guard_matching_order_ids"] = list(guard_report.get("last_guard_matching_order_ids") or [])
        preserved["last_guard_total_reserved_open_exit_base"] = str(guard_report.get("total_reserved_open_exit_base") or "0")
        preserved["last_guard_attempted_new_status"] = str(guard_report.get("attempted_new_status") or "")
        preserved["last_guard_attempted_position_size_base"] = str(guard_report.get("attempted_new_position_size_base") or "0")
        preserved["last_guard_attempted_bot_managed_base"] = str(guard_report.get("attempted_new_bot_managed_base") or "0")
        preserved["last_guard_caller_reason"] = str(guard_report.get("caller_reason") or "")
        notes = str(preserved.get("notes") or current.get("notes") or "")
        marker = "guarded_open_d3_exit_reservation"
        if marker not in notes:
            notes = (notes + f" | {marker}").strip(" |")
        preserved["notes"] = notes
        preserved["updated_at"] = self._now_iso()
        return preserved

    def _apply_open_d3_exit_close_guard(
        self,
        *,
        ticker: str,
        current: Dict[str, Any],
        merged: Dict[str, Any],
        caller_reason: str = "",
        evidence_status: str = "",
    ) -> Dict[str, Any]:
        guard_report = build_open_d3_exit_position_guard_report(
            ticker=ticker,
            current_position=current,
            proposed_position=merged,
            linked_position_id=self._first_linked_position_id(merged or current),
            caller_reason=caller_reason,
            evidence_status=evidence_status,
        )
        if not guard_report.get("should_block_close"):
            return merged
        return self._preserve_open_position_due_to_open_d3_exit(
            ticker=ticker,
            current=current,
            merged=merged,
            guard_report=guard_report,
        )

    @staticmethod
    def _normalize_side(side: str) -> str:
        side = str(side or "").upper().strip()
        if side not in {"BUY", "SELL", "NONE"}:
            return "NONE"
        return side

    @staticmethod
    def _to_decimal(value: Any, default: str = "0") -> Decimal:
        try:
            if value is None or value == "":
                return Decimal(default)
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    def _build_synthetic_open_risk_defaults(self, position: Dict[str, Any]) -> Dict[str, Any]:
        if str(position.get("status", "open")).lower().strip() != "open":
            return {}

        entry_price = self._to_decimal(position.get("entry_price"), "0")
        if entry_price <= Decimal("0"):
            return {}

        raw_setup = str(position.get("setup_type", "")).strip().lower()
        setup_aliases = {
            "trend": "trend_continuation",
            "continuation": "trend_continuation",
            "trend_continuation": "trend_continuation",
            "reclaim": "reclaim_reversal",
            "reversal": "reclaim_reversal",
            "reclaim_reversal": "reclaim_reversal",
            "meanrev": "mean_reversion",
            "mean reversion": "mean_reversion",
            "mean_reversion": "mean_reversion",
        }
        setup_type = setup_aliases.get(raw_setup, "trend_continuation")

        if setup_type == "trend_continuation":
            stop_mult = Decimal("0.97")
            reward_mult = Decimal("2.0")
            trailing_trigger = "0.025"
            trailing_distance = "0.035"
            invalidation_mode = "ema20_break"
        elif setup_type == "reclaim_reversal":
            stop_mult = Decimal("0.975")
            reward_mult = Decimal("1.6")
            trailing_trigger = "0.018"
            trailing_distance = "0.03"
            invalidation_mode = "ema20_break"
        else:
            stop_mult = Decimal("0.982")
            reward_mult = Decimal("1.25")
            trailing_trigger = "0.012"
            trailing_distance = "0.022"
            invalidation_mode = "range_low_break"

        existing_stop = self._to_decimal(position.get("stop_price"), "0")
        stop_price = existing_stop if existing_stop > Decimal("0") else (entry_price * stop_mult)
        if stop_price >= entry_price:
            stop_price = entry_price * stop_mult

        existing_tp = self._to_decimal(position.get("take_profit_price"), "0")
        if existing_tp > Decimal("0"):
            take_profit_price = existing_tp
        else:
            risk_distance = entry_price - stop_price
            if risk_distance <= Decimal("0"):
                risk_distance = entry_price * (Decimal("1") - stop_mult)
            take_profit_price = entry_price + (risk_distance * reward_mult)

        return {
            "stop_price": str(stop_price),
            "take_profit_price": str(take_profit_price),
            "trailing_trigger_pct": str(position.get("trailing_trigger_pct") or trailing_trigger),
            "trailing_distance_pct": str(position.get("trailing_distance_pct") or trailing_distance),
            "invalidation_mode": str(position.get("invalidation_mode") or invalidation_mode),
            "position_plan_status": str(position.get("position_plan_status") or "synthetic_default"),
            "position_plan_version": int(position.get("position_plan_version", 1) or 1),
        }

    def _ensure_position_defaults(self, ticker: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = self._now_iso()
        position = dict(self._json_safe(payload or {}))

        position["ticker"] = self._normalize_ticker(ticker)
        position["status"] = str(position.get("status", "open")).lower().strip() or "open"
        position["last_side"] = self._normalize_side(position.get("last_side"))
        position["updated_at"] = position.get("updated_at", now)

        if "entry_time" not in position:
            position["entry_time"] = now

        if "entry_price" not in position:
            position["entry_price"] = "0"

        if "entry_reason" not in position:
            position["entry_reason"] = ""

        if "position_size_base" not in position:
            position["position_size_base"] = "0"

        if "position_size_quote" not in position:
            position["position_size_quote"] = "0"

        if "stop_price" not in position:
            position["stop_price"] = "0"

        if "invalidation_price" not in position:
            position["invalidation_price"] = str(position.get("stop_price") or "0")

        if "take_profit_price" not in position:
            position["take_profit_price"] = "0"

        if "highest_price_seen" not in position:
            position["highest_price_seen"] = str(position.get("entry_price", "0"))

        if "lowest_price_seen" not in position:
            position["lowest_price_seen"] = str(position.get("entry_price", "0"))

        if "trailing_active" not in position:
            position["trailing_active"] = False

        if "trailing_distance_pct" not in position:
            position["trailing_distance_pct"] = "0.03"

        if "trailing_trigger_pct" not in position:
            position["trailing_trigger_pct"] = "0.02"

        if "invalidation_mode" not in position:
            position["invalidation_mode"] = "ema20_break"

        if "notes" not in position:
            position["notes"] = ""

        if "monitoring_enabled" not in position:
            position["monitoring_enabled"] = True

        if "opened_via_strategy" not in position:
            position["opened_via_strategy"] = True

        if "last_heartbeat_at" not in position:
            position["last_heartbeat_at"] = None

        if "last_heartbeat_status" not in position:
            position["last_heartbeat_status"] = "unknown"

        if "heartbeat_warning_count" not in position:
            position["heartbeat_warning_count"] = 0

        if "last_heartbeat_reason" not in position:
            position["last_heartbeat_reason"] = ""

        if "last_position_watch_at" not in position:
            position["last_position_watch_at"] = None

        if "last_position_watch_decision" not in position:
            position["last_position_watch_decision"] = "unknown"

        if "last_position_watch_reason" not in position:
            position["last_position_watch_reason"] = ""

        if "position_watch_warning_count" not in position:
            position["position_watch_warning_count"] = 0

        if "last_position_risk_state" not in position:
            position["last_position_risk_state"] = "unknown"

        if "last_stop_breach_at" not in position:
            position["last_stop_breach_at"] = None

        if "last_stop_breach_reason" not in position:
            position["last_stop_breach_reason"] = ""

        if "last_deepseek_position_check_at" not in position:
            position["last_deepseek_position_check_at"] = None

        if "last_deepseek_position_result" not in position:
            position["last_deepseek_position_result"] = "unknown"

        if "last_full_position_review_at" not in position:
            position["last_full_position_review_at"] = None

        if "last_full_position_review_result" not in position:
            position["last_full_position_review_result"] = "unknown"

        if "heartbeat_pause_until" not in position:
            position["heartbeat_pause_until"] = None

        # Inventory-aware velden
        if "baseline_inventory_base" not in position:
            position["baseline_inventory_base"] = "0"

        if "bot_managed_base" not in position:
            position["bot_managed_base"] = str(position.get("position_size_base", "0"))

        if "legacy_inventory_base" not in position:
            position["legacy_inventory_base"] = "0"

        if "inventory_sell_enabled" not in position:
            position["inventory_sell_enabled"] = False

        if "inventory_sell_mode" not in position:
            position["inventory_sell_mode"] = "bot_only"

        if "inventory_max_extra_sell_fraction" not in position:
            position["inventory_max_extra_sell_fraction"] = "0"

        if "inventory_severe_risk_only" not in position:
            position["inventory_severe_risk_only"] = True

        if "inventory_min_residual_base" not in position:
            position["inventory_min_residual_base"] = "0"

        if "inventory_last_sell_scope" not in position:
            position["inventory_last_sell_scope"] = "bot_only"

        if "inventory_last_extra_sell_base" not in position:
            position["inventory_last_extra_sell_base"] = "0"

        if "inventory_policy_snapshot" not in position:
            position["inventory_policy_snapshot"] = {}

        if "exchange_base_increment" not in position:
            position["exchange_base_increment"] = "0"

        if "exchange_base_min_size" not in position:
            position["exchange_base_min_size"] = "0"

        if "effective_min_trade_base" not in position:
            position["effective_min_trade_base"] = "0"

        if "dust_residual_base" not in position:
            position["dust_residual_base"] = "0"

        if "dust_residual_quote" not in position:
            position["dust_residual_quote"] = "0"

        if "dust_cleanup_note" not in position:
            position["dust_cleanup_note"] = ""

        if "synthetic_closed_at" not in position:
            position["synthetic_closed_at"] = None

        if "synthetic_close_reason" not in position:
            position["synthetic_close_reason"] = ""

        explicit_stop = self._to_decimal(position.get("stop_price"), "0")
        explicit_invalidation = self._to_decimal(position.get("invalidation_price"), "0")
        risk_incomplete = (
            position["status"] in {"open", "active"}
            and (explicit_stop <= Decimal("0") or explicit_invalidation <= Decimal("0"))
        )
        if "protective_stop_status" not in position:
            position["protective_stop_status"] = "position_risk_incomplete" if risk_incomplete else "protective_stop_state_complete"
        if "d2_plan_status" not in position:
            position["d2_plan_status"] = "pending"
        if "d3_exit_status" not in position:
            position["d3_exit_status"] = "pending"
        if "last_risk_check_at" not in position:
            position["last_risk_check_at"] = None
        if "source_trade_plan_id" not in position:
            position["source_trade_plan_id"] = str(position.get("trade_plan_id") or "")
        if "source_setup_type" not in position:
            position["source_setup_type"] = str(position.get("setup_type") or "")
        if "source_entry_order_id" not in position:
            position["source_entry_order_id"] = str(position.get("phase_c43_exchange_order_id") or position.get("order_id") or "")
        if "position_risk_incomplete" not in position:
            position["position_risk_incomplete"] = risk_incomplete
        if risk_incomplete:
            position["new_entries_blocked_reason"] = "position_risk_incomplete"

        if position["status"] == "closed":
            position["position_size_base"] = "0"
            position["position_size_quote"] = "0"
            position["bot_managed_base"] = "0"
            position["monitoring_enabled"] = False
            position["last_heartbeat_status"] = str(position.get("last_heartbeat_status") or "closed")
        else:
            synthetic_defaults = self._build_synthetic_open_risk_defaults(position)
            for key, value in synthetic_defaults.items():
                current_value = position.get(key)
                if current_value in {None, "", "0", "0.0"} or key in {"position_plan_status", "position_plan_version"}:
                    position[key] = value
            if risk_incomplete:
                position["synthetic_protective_levels_preview_only"] = True

        return position

    def get_cooldowns(self) -> Dict[str, Any]:
        return self._load_json(self.cooldowns_file, {})

    def prune_cooldowns(self) -> Dict[str, Any]:
        data = self.get_cooldowns()
        now = datetime.now(timezone.utc)

        pruned: Dict[str, Any] = {}
        for ticker, expiry in data.items():
            try:
                expiry_dt = datetime.fromisoformat(expiry)
                if now < expiry_dt:
                    pruned[ticker] = expiry
            except Exception:
                continue

        self._save_json(self.cooldowns_file, pruned)
        return pruned

    def set_cooldown(self, ticker: str, minutes: int) -> None:
        ticker = self._normalize_ticker(ticker)
        data = self.prune_cooldowns()
        expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        data[ticker] = expires.isoformat()
        self._save_json(self.cooldowns_file, data)

    def clear_cooldown(self, ticker: str) -> None:
        ticker = self._normalize_ticker(ticker)
        data = self.get_cooldowns()
        if ticker in data:
            del data[ticker]
            self._save_json(self.cooldowns_file, data)

    def cooldown_active(self, ticker: str) -> bool:
        ticker = self._normalize_ticker(ticker)
        # A status check is read-only. Explicit maintenance/set operations own
        # cooldown pruning persistence.
        data = self.get_cooldowns()
        expiry = data.get(ticker)
        if not expiry:
            return False
        try:
            expiry_dt = datetime.fromisoformat(expiry)
            return datetime.now(timezone.utc) < expiry_dt
        except Exception:
            return False

    def get_daily_pnl(self) -> Dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        data = self._load_json(
            self.daily_file,
            {
                "date": today,
                "realized_pnl": 0.0,
                "updated_at": self._now_iso(),
            },
        )

        if data.get("date") != today:
            return {
                "date": today,
                "realized_pnl": 0.0,
                "updated_at": self._now_iso(),
            }

        if "realized_pnl" not in data:
            data["realized_pnl"] = 0.0

        if "updated_at" not in data:
            data["updated_at"] = self._now_iso()

        return data

    def add_realized_pnl(self, delta: float) -> Dict[str, Any]:
        data = self.get_daily_pnl()
        data["realized_pnl"] = float(data.get("realized_pnl", 0.0)) + float(delta)
        data["updated_at"] = self._now_iso()
        self._save_json(self.daily_file, data)
        return data

    def get_positions(self) -> Dict[str, Any]:
        raw = self._load_json(self.positions_file, {})
        normalized: Dict[str, Any] = {}

        for ticker, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            try:
                normalized_ticker = self._normalize_ticker(ticker)
            except ValueError:
                continue

            normalized[normalized_ticker] = self._ensure_position_defaults(
                normalized_ticker,
                payload,
            )

        # Reading state must not silently repair or rewrite it. Normalization is
        # applied in memory; an explicit transition (upsert/close/reconcile) is
        # required to persist any repair so read-only tooling remains truthful.
        return normalized

    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        return self.get_positions().get(self._normalize_ticker(ticker))

    def upsert_position(
        self,
        ticker: str,
        payload: Dict[str, Any],
        *,
        caller_reason: str = "",
        evidence_status: str = "",
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        data = self.get_positions()

        current = data.get(ticker, {})
        safe_payload = self._json_safe(payload)
        merged = {**current, **safe_payload}
        merged["updated_at"] = self._now_iso()
        merged = self._apply_open_d3_exit_close_guard(
            ticker=ticker,
            current=current,
            merged=merged,
            caller_reason=caller_reason,
            evidence_status=evidence_status,
        )

        merged = self._ensure_position_defaults(ticker, merged)

        data[ticker] = merged
        self._save_json(self.positions_file, data)
        return merged

    def create_position(
        self,
        ticker: str,
        side: str,
        order_id: str,
        entry_price: str,
        position_size_base: str,
        position_size_quote: str,
        entry_reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = self._now_iso()
        payload = {
            "ticker": self._normalize_ticker(ticker),
            "status": "open",
            "last_side": self._normalize_side(side),
            "entry_time": now,
            "updated_at": now,
            "order_id": order_id,
            "entry_price": str(entry_price),
            "entry_reason": str(entry_reason),
            "position_size_base": str(position_size_base),
            "position_size_quote": str(position_size_quote),
            "stop_price": "0",
            "take_profit_price": "0",
            "highest_price_seen": str(entry_price),
            "lowest_price_seen": str(entry_price),
            "trailing_active": False,
            "trailing_distance_pct": "0.03",
            "trailing_trigger_pct": "0.02",
            "invalidation_mode": "ema20_break",
            "notes": "",
            "monitoring_enabled": True,
            "opened_via_strategy": True,
            "last_heartbeat_at": None,
            "last_heartbeat_status": "unknown",
            "heartbeat_warning_count": 0,
            "last_heartbeat_reason": "",
            "last_deepseek_position_check_at": None,
            "last_deepseek_position_result": "unknown",
            "last_full_position_review_at": None,
            "last_full_position_review_result": "unknown",
            "heartbeat_pause_until": None,
            "baseline_inventory_base": "0",
            "bot_managed_base": str(position_size_base),
            "legacy_inventory_base": "0",
            "inventory_sell_enabled": False,
            "inventory_sell_mode": "bot_only",
            "inventory_max_extra_sell_fraction": "0",
            "inventory_severe_risk_only": True,
            "inventory_min_residual_base": "0",
            "inventory_last_sell_scope": "bot_only",
            "inventory_last_extra_sell_base": "0",
            "inventory_policy_snapshot": {},
            "exchange_base_increment": "0",
            "exchange_base_min_size": "0",
            "effective_min_trade_base": "0",
            "dust_residual_base": "0",
            "dust_residual_quote": "0",
            "dust_cleanup_note": "",
            "synthetic_closed_at": None,
            "synthetic_close_reason": "",
        }
        if extra:
            payload.update(self._json_safe(extra))
        return self.upsert_position(ticker, payload)

    def sync_live_inventory_position(
        self,
        ticker: str,
        live_base_size: str,
        reference_price: str,
        entry_reason: str = "inventory_sync",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Maak of herstel een lokale open positie op basis van een echte exchange-holding.
        Dit wordt gebruikt wanneer er wel base asset op Coinbase staat, maar geen
        bruikbare open positie meer in de lokale state aanwezig is.
        """
        ticker = self._normalize_ticker(ticker)
        now = self._now_iso()
        current = self.get_position(ticker) or {}

        entry_price = str(current.get("entry_price") or reference_price or "0")
        if entry_price in {"", "0", "0.0"}:
            entry_price = str(reference_price or "0")

        payload: Dict[str, Any] = {
            "ticker": ticker,
            "status": "open",
            "last_side": "BUY",
            "entry_time": current.get("entry_time") or now,
            "updated_at": now,
            "order_id": str(current.get("order_id") or f"inventory-sync:{ticker}:{now}"),
            "entry_price": entry_price,
            "entry_reason": str(current.get("entry_reason") or entry_reason),
            "position_size_base": str(live_base_size),
            "position_size_quote": str(live_base_size),
            "stop_price": str(current.get("stop_price") or "0"),
            "take_profit_price": str(current.get("take_profit_price") or "0"),
            "highest_price_seen": str(current.get("highest_price_seen") or entry_price),
            "lowest_price_seen": str(current.get("lowest_price_seen") or entry_price),
            "trailing_active": bool(current.get("trailing_active", False)),
            "trailing_distance_pct": str(current.get("trailing_distance_pct") or "0.03"),
            "trailing_trigger_pct": str(current.get("trailing_trigger_pct") or "0.02"),
            "invalidation_mode": str(current.get("invalidation_mode") or "exchange_inventory_sync"),
            "notes": str(current.get("notes") or "synced_from_live_exchange_inventory"),
            "monitoring_enabled": True,
            "opened_via_strategy": bool(current.get("opened_via_strategy", False)),
            "synced_from_exchange": True,
            "last_heartbeat_status": str(current.get("last_heartbeat_status") or "unknown"),
            "last_heartbeat_reason": str(current.get("last_heartbeat_reason") or ""),
            "bot_managed_base": str(live_base_size),
            "baseline_inventory_base": str(current.get("baseline_inventory_base") or "0"),
            "legacy_inventory_base": str(current.get("legacy_inventory_base") or "0"),
            "dust_residual_base": "0",
            "dust_residual_quote": "0",
            "dust_cleanup_note": "",
            "synthetic_closed_at": None,
            "synthetic_close_reason": "",
        }

        if extra:
            payload.update(self._json_safe(extra))

        try:
            payload["position_size_quote"] = str(float(live_base_size) * float(reference_price))
        except Exception:
            payload["position_size_quote"] = str(current.get("position_size_quote") or "0")

        return self.upsert_position(ticker, payload)

    def update_position(
        self,
        ticker: str,
        side: str,
        size_quote: str,
        order_id: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ticker": self._normalize_ticker(ticker),
            "last_side": self._normalize_side(side),
            "position_size_quote": str(size_quote),
            "order_id": order_id,
            "updated_at": self._now_iso(),
        }
        if extra:
            payload.update(self._json_safe(extra))
        return self.upsert_position(ticker, payload)

    def mark_position_closed(
        self,
        ticker: str,
        close_reason: str = "",
        close_price: str = "0",
        realized_pnl: Optional[float] = None,
        *,
        caller_reason: str = "",
        evidence_status: str = "",
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        data = self.get_positions()
        position = data.get(ticker)
        if not position:
            return {}

        now = self._now_iso()

        proposed = dict(position)
        proposed.update({
            "status": "closed",
            "close_time": now,
            "close_reason": str(close_reason),
            "close_price": str(close_price),
            "updated_at": now,
            "position_size_base": "0",
            "position_size_quote": "0",
            "bot_managed_base": "0",
            "legacy_inventory_base": "0",
            "monitoring_enabled": False,
            "last_heartbeat_status": "closed",
            "last_heartbeat_at": now,
            "last_heartbeat_reason": str(close_reason),
        })
        if realized_pnl is not None:
            proposed["realized_pnl"] = float(realized_pnl)

        guarded = self._apply_open_d3_exit_close_guard(
            ticker=ticker,
            current=position,
            merged=proposed,
            caller_reason=caller_reason,
            evidence_status=evidence_status,
        )
        data[ticker] = self._ensure_position_defaults(ticker, guarded)
        self._save_json(self.positions_file, data)
        return data[ticker]

    def mark_position_closed_tiny_residual(
        self,
        ticker: str,
        close_reason: str = "",
        close_price: str = "0",
        residual_base: str = "0",
        residual_quote: str = "0",
        effective_min_trade_base: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        *,
        caller_reason: str = "",
        evidence_status: str = "",
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        data = self.get_positions()
        position = data.get(ticker) or {"ticker": ticker}
        now = self._now_iso()

        proposed = dict(position)
        proposed.update({
            "status": "closed",
            "close_time": now,
            "close_reason": str(close_reason),
            "close_price": str(close_price),
            "updated_at": now,
            "position_size_base": "0",
            "position_size_quote": "0",
            "bot_managed_base": "0",
            "legacy_inventory_base": "0",
            "baseline_inventory_base": "0",
            "monitoring_enabled": False,
            "last_heartbeat_status": "closed_tiny_residual",
            "last_heartbeat_at": now,
            "last_heartbeat_reason": str(close_reason),
            "dust_residual_base": str(residual_base),
            "dust_residual_quote": str(residual_quote),
            "dust_cleanup_note": str(close_reason),
            "synthetic_closed_at": now,
            "synthetic_close_reason": str(close_reason),
        })

        if effective_min_trade_base is not None:
            proposed["effective_min_trade_base"] = str(effective_min_trade_base)

        if extra:
            proposed.update(self._json_safe(extra))

        guarded = self._apply_open_d3_exit_close_guard(
            ticker=ticker,
            current=position,
            merged=proposed,
            caller_reason=caller_reason,
            evidence_status=evidence_status,
        )
        data[ticker] = self._ensure_position_defaults(ticker, guarded)
        self._save_json(self.positions_file, data)
        return data[ticker]

    def remove_position(self, ticker: str) -> None:
        ticker = self._normalize_ticker(ticker)
        data = self.get_positions()
        if ticker in data:
            del data[ticker]
            self._save_json(self.positions_file, data)

    def force_sync_position_base(
        self,
        ticker: str,
        actual_base_size: str,
        current_price: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Handige repair helper als lokale state ooit uit sync is geraakt.
        """
        ticker = self._normalize_ticker(ticker)
        data = self.get_positions()
        position = data.get(ticker)
        if not position:
            raise ValueError(f"Geen positie gevonden voor {ticker}")

        position["position_size_base"] = str(actual_base_size)

        if current_price is not None:
            try:
                quote_val = float(actual_base_size) * float(current_price)
                position["position_size_quote"] = str(quote_val)
            except Exception:
                pass

        position["updated_at"] = self._now_iso()
        data[ticker] = self._ensure_position_defaults(ticker, position)
        self._save_json(self.positions_file, data)
        return data[ticker]

    def set_inventory_tracking(
        self,
        ticker: str,
        baseline_inventory_base: str,
        bot_managed_base: str,
        legacy_inventory_base: str,
        inventory_sell_enabled: bool,
        inventory_sell_mode: str,
        inventory_max_extra_sell_fraction: str,
        inventory_severe_risk_only: bool,
        inventory_min_residual_base: str,
        inventory_policy_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        payload: Dict[str, Any] = {
            "baseline_inventory_base": str(baseline_inventory_base),
            "bot_managed_base": str(bot_managed_base),
            "legacy_inventory_base": str(legacy_inventory_base),
            "inventory_sell_enabled": bool(inventory_sell_enabled),
            "inventory_sell_mode": str(inventory_sell_mode),
            "inventory_max_extra_sell_fraction": str(inventory_max_extra_sell_fraction),
            "inventory_severe_risk_only": bool(inventory_severe_risk_only),
            "inventory_min_residual_base": str(inventory_min_residual_base),
            "inventory_policy_snapshot": dict(self._json_safe(inventory_policy_snapshot or {})),
            "updated_at": self._now_iso(),
        }
        return self.upsert_position(ticker, payload)

    def sync_inventory_after_sell(
        self,
        ticker: str,
        remaining_total_base: str,
        remaining_bot_managed_base: str,
        remaining_legacy_inventory_base: str,
        last_sell_scope: str,
        last_extra_sell_base: str,
        current_price: Optional[str] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)

        payload: Dict[str, Any] = {
            "position_size_base": str(remaining_total_base),
            "bot_managed_base": str(remaining_bot_managed_base),
            "legacy_inventory_base": str(remaining_legacy_inventory_base),
            "inventory_last_sell_scope": str(last_sell_scope),
            "inventory_last_extra_sell_base": str(last_extra_sell_base),
            "updated_at": self._now_iso(),
        }

        if current_price is not None:
            try:
                payload["position_size_quote"] = str(float(remaining_total_base) * float(current_price))
            except Exception:
                pass

        return self.upsert_position(ticker, payload)

    def position_heartbeat_paused(self, ticker: str) -> bool:
        ticker = self._normalize_ticker(ticker)
        position = self.get_position(ticker)
        if not position:
            return False

        pause_until = position.get("heartbeat_pause_until")
        if not pause_until:
            return False

        try:
            pause_until_dt = datetime.fromisoformat(str(pause_until))
            return datetime.now(timezone.utc) < pause_until_dt
        except Exception:
            return False

    def set_position_heartbeat_pause(self, ticker: str, minutes: int) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        pause_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        return self.upsert_position(
            ticker,
            {
                "heartbeat_pause_until": pause_until.isoformat(),
                "updated_at": self._now_iso(),
            },
        )

    def clear_position_heartbeat_pause(self, ticker: str) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        return self.upsert_position(
            ticker,
            {
                "heartbeat_pause_until": None,
                "updated_at": self._now_iso(),
            },
        )

    def mark_position_heartbeat_ok(
        self,
        ticker: str,
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        payload: Dict[str, Any] = {
            "last_heartbeat_at": self._now_iso(),
            "last_heartbeat_status": "ok",
            "heartbeat_warning_count": 0,
            "position_watch_warning_count": 0,
            "last_heartbeat_reason": str(reason),
            "last_position_risk_state": "ok",
            "updated_at": self._now_iso(),
        }
        if extra:
            payload.update(self._json_safe(extra))
        return self.upsert_position(ticker, payload)

    def mark_position_heartbeat_warning(
        self,
        ticker: str,
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        current = self.get_position(ticker) or {}
        current_count = int(current.get("heartbeat_warning_count", 0) or 0)

        payload: Dict[str, Any] = {
            "last_heartbeat_at": self._now_iso(),
            "last_heartbeat_status": "warning",
            "heartbeat_warning_count": current_count + 1,
            "last_heartbeat_reason": str(reason),
            "last_position_risk_state": "warning",
            "updated_at": self._now_iso(),
        }
        if extra:
            payload.update(self._json_safe(extra))
        return self.upsert_position(ticker, payload)

    def mark_position_watch_decision(
        self,
        ticker: str,
        decision: str = "hold_ok",
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        current = self.get_position(ticker) or {}
        current_count = int(current.get("position_watch_warning_count", 0) or 0)
        normalized_decision = str(decision or "hold_ok").strip().lower()
        warning_decisions = {"watch_closer", "tighten_risk", "escalate_full_review"}
        next_count = 0 if normalized_decision == "hold_ok" else (current_count + 1 if normalized_decision in warning_decisions else current_count)

        payload: Dict[str, Any] = {
            "last_position_watch_at": self._now_iso(),
            "last_position_watch_decision": normalized_decision,
            "last_position_watch_reason": str(reason),
            "position_watch_warning_count": next_count,
            "last_position_risk_state": normalized_decision,
            "updated_at": self._now_iso(),
        }
        if normalized_decision == "hold_ok":
            payload["heartbeat_warning_count"] = 0
        if extra:
            payload.update(self._json_safe(extra))
        return self.upsert_position(ticker, payload)

    def mark_position_stop_breach(
        self,
        ticker: str,
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        payload: Dict[str, Any] = {
            "last_stop_breach_at": self._now_iso(),
            "last_stop_breach_reason": str(reason),
            "last_position_risk_state": "stop_breached",
            "updated_at": self._now_iso(),
        }
        if extra:
            payload.update(self._json_safe(extra))
        return self.upsert_position(ticker, payload)

    def mark_position_deepseek_review(
        self,
        ticker: str,
        result: str = "unknown",
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        payload: Dict[str, Any] = {
            "last_deepseek_position_check_at": self._now_iso(),
            "last_deepseek_position_result": str(result),
            "updated_at": self._now_iso(),
        }

        if reason:
            payload["last_heartbeat_reason"] = str(reason)

        if result == "hold_ok":
            payload["last_heartbeat_status"] = "ok"
            payload["heartbeat_warning_count"] = 0
            payload["position_watch_warning_count"] = 0
            payload["last_position_risk_state"] = "ok"
        else:
            payload["last_position_risk_state"] = str(result)

        if extra:
            payload.update(self._json_safe(extra))

        return self.upsert_position(ticker, payload)

    def mark_position_full_review(
        self,
        ticker: str,
        result: str = "unknown",
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ticker = self._normalize_ticker(ticker)
        now = self._now_iso()

        payload: Dict[str, Any] = {
            "last_full_position_review_at": now,
            "last_full_position_review_result": str(result),
            "updated_at": now,
        }

        if reason:
            payload["last_heartbeat_reason"] = str(reason)

        if result == "hold_ok":
            payload["last_heartbeat_status"] = "ok"
            payload["heartbeat_warning_count"] = 0
            payload["position_watch_warning_count"] = 0
            payload["last_position_risk_state"] = "ok"
            payload["last_heartbeat_at"] = now
        elif result == "escalate_full_review":
            current = self.get_position(ticker) or {}
            current_count = int(current.get("heartbeat_warning_count", 0) or 0)
            payload["last_heartbeat_status"] = "escalated_full_review"
            payload["heartbeat_warning_count"] = max(current_count, 1)
            payload["last_position_risk_state"] = "escalated_full_review"
            payload["last_heartbeat_at"] = now
        else:
            payload["last_position_risk_state"] = str(result)

        if extra:
            payload.update(self._json_safe(extra))

        return self.upsert_position(ticker, payload)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "cooldowns": self.prune_cooldowns(),
            "daily_pnl": self.get_daily_pnl(),
            "positions": self.get_positions(),
            "generated_at": self._now_iso(),
        }
