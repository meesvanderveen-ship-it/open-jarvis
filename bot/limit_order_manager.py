from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from bot.execution_outcome_tracker import ExecutionOutcomeTracker
from bot.order_lifecycle import evaluate_paper_order_lifecycle
from bot.order_plan import build_order_intent_from_execution_plan, is_actionable_order_intent, to_decimal
from bot.order_store import OrderStore


ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _max_decimal(*values: Any) -> Decimal:
    best = Decimal("0")
    for value in values:
        dec = to_decimal(value, "0")
        if dec > best:
            best = dec
    return best


class PaperLimitOrderManager:
    """Phase-B paper limit-order manager.

    It can create and lifecycle paper orders in state/open_orders.json. It never
    submits, cancels or replaces live Coinbase orders. Live order flags must be
    false for this class to do anything.

    Phase B.4 adds stricter paper-only simulation of the future live rails:
    reserved balances, duplicate entry/exit checks, open-order caps and per-cycle
    action budgets. These checks are intentionally deterministic and cannot
    place live orders.
    """

    def __init__(
        self,
        *,
        cfg: Any,
        order_store: OrderStore,
        execution_outcome_tracker: Optional[ExecutionOutcomeTracker] = None,
    ) -> None:
        self.cfg = cfg
        self.order_store = order_store
        self.execution_outcome_tracker = execution_outcome_tracker
        self._budget_state: Dict[str, Any] = {}
        self.begin_cycle("initial")

    def begin_cycle(self, cycle_source: str = "strategy_engine") -> Dict[str, Any]:
        """Reset paper order-action counters for a new bot cycle."""
        self._budget_state = {
            "cycle_source": cycle_source,
            "started_at": _now_iso(),
            "order_actions": 0,
            "new_orders": 0,
            "cancels": 0,
            "replaces": 0,
            "skipped_by_budget": 0,
        }
        return self.budget_status()

    def budget_status(self) -> Dict[str, Any]:
        return {
            **self._budget_state,
            "limits": {
                "max_order_actions_per_cycle": int(getattr(self.cfg, "max_order_actions_per_cycle", 5)),
                "max_new_orders_per_cycle": int(getattr(self.cfg, "max_new_orders_per_cycle", 2)),
                "max_cancels_per_cycle": int(getattr(self.cfg, "max_cancels_per_cycle", 3)),
                "max_replaces_per_cycle": int(getattr(self.cfg, "max_replaces_per_cycle", 2)),
            },
        }

    def _budget_allows(self, action_type: str) -> Tuple[bool, Optional[str]]:
        if not bool(getattr(self.cfg, "enable_paper_order_budget_enforcement", True)):
            return True, None
        max_actions = int(getattr(self.cfg, "max_order_actions_per_cycle", 5))
        if max_actions >= 0 and int(self._budget_state.get("order_actions", 0)) >= max_actions:
            return False, "paper_order_action_budget_exhausted"
        if action_type == "new_order":
            max_new = int(getattr(self.cfg, "max_new_orders_per_cycle", 2))
            if max_new >= 0 and int(self._budget_state.get("new_orders", 0)) >= max_new:
                return False, "paper_new_order_budget_exhausted"
        if action_type == "cancel":
            max_cancels = int(getattr(self.cfg, "max_cancels_per_cycle", 3))
            if max_cancels >= 0 and int(self._budget_state.get("cancels", 0)) >= max_cancels:
                return False, "paper_cancel_budget_exhausted"
        if action_type == "replace":
            max_replaces = int(getattr(self.cfg, "max_replaces_per_cycle", 2))
            if max_replaces >= 0 and int(self._budget_state.get("replaces", 0)) >= max_replaces:
                return False, "paper_replace_budget_exhausted"
        return True, None

    def _consume_budget(self, action_type: str) -> None:
        if not bool(getattr(self.cfg, "enable_paper_order_budget_enforcement", True)):
            return
        self._budget_state["order_actions"] = int(self._budget_state.get("order_actions", 0)) + 1
        if action_type == "new_order":
            self._budget_state["new_orders"] = int(self._budget_state.get("new_orders", 0)) + 1
        elif action_type == "cancel":
            self._budget_state["cancels"] = int(self._budget_state.get("cancels", 0)) + 1
        elif action_type == "replace":
            self._budget_state["replaces"] = int(self._budget_state.get("replaces", 0)) + 1

    def _skip_by_budget(self, *, ticker: str, action_type: str, reason: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._budget_state["skipped_by_budget"] = int(self._budget_state.get("skipped_by_budget", 0)) + 1
        payload = {
            "generated_at": _now_iso(),
            "ticker": ticker,
            "mode": "paper",
            "status": "paper_order_budget_skipped",
            "action_type": action_type,
            "reason": reason,
            "intent": intent,
            "paper_budget_status": self.budget_status(),
        }
        self.order_store.append_event("paper_order_budget_skipped", payload)
        return payload

    def enabled(self) -> bool:
        if not bool(getattr(self.cfg, "enable_limit_order_manager", False)):
            return False
        # Phase B is paper-only. If any live flag is on, refuse to act so the bot
        # cannot accidentally place live limit orders before phase C.
        if bool(getattr(self.cfg, "enable_live_limit_orders", False)):
            return False
        if bool(getattr(self.cfg, "enable_live_entry_orders", False)):
            return False
        if bool(getattr(self.cfg, "enable_live_exit_orders", False)):
            return False
        return True

    def review_open_orders(self, feature_packs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        if not self.enabled():
            return {
                "generated_at": _now_iso(),
                "enabled": False,
                "mode": "paper",
                "reviewed": 0,
                "actions": [],
                "reason": "limit_order_manager_disabled_or_live_flags_enabled",
                "paper_budget_status": self.budget_status(),
            }

        actions: List[Dict[str, Any]] = []
        for order in self.order_store.open_orders():
            ticker = str(order.get("ticker", "")).upper().strip()
            feature_pack = feature_packs.get(ticker) or {}
            evaluation = evaluate_paper_order_lifecycle(order, feature_pack)
            action = str(evaluation.get("action", "keep")).lower()
            order_id = str(order.get("client_order_id"))

            if action == "keep":
                self.order_store.update_order(
                    order_id,
                    {
                        "last_reviewed_at": _now_iso(),
                        "last_lifecycle_evaluation": evaluation,
                    },
                    event_type="paper_order_reviewed_keep",
                )
                actions.append({"client_order_id": order_id, "ticker": ticker, "action": "keep", "evaluation": evaluation})
                continue

            allowed, budget_reason = self._budget_allows("order_action")
            if not allowed:
                skip = self._skip_by_budget(ticker=ticker, action_type="order_action", reason=budget_reason or "paper_order_action_budget_exhausted")
                actions.append({"client_order_id": order_id, "ticker": ticker, "action": "budget_skip", "evaluation": evaluation, "budget_skip": skip})
                continue

            if action == "fill":
                fill_price = to_decimal(evaluation.get("fill_price"), str(order.get("limit_price") or "0"))
                size_base = to_decimal(order.get("size_base"), "0")
                size_quote = to_decimal(order.get("size_quote"), "0")
                if size_quote <= Decimal("0") and size_base > Decimal("0") and fill_price > Decimal("0"):
                    size_quote = size_base * fill_price
                updates = {
                    "status": "filled",
                    "filled_at": _now_iso(),
                    "filled_size": str(size_base),
                    "remaining_size": "0",
                    "remaining_quote": "0",
                    "avg_fill_price": str(fill_price) if fill_price > Decimal("0") else order.get("limit_price"),
                    "paper_fill": True,
                    "last_lifecycle_evaluation": evaluation,
                }
                updated_order = self.order_store.update_order(order_id, updates, event_type="paper_order_filled")
                self._consume_budget("order_action")
                outcome = None
                if self.execution_outcome_tracker is not None and updated_order is not None:
                    outcome = self.execution_outcome_tracker.record_paper_order_outcome(updated_order, evaluation)
                actions.append({"client_order_id": order_id, "ticker": ticker, "action": "fill", "evaluation": evaluation, "execution_outcome": outcome})
                continue

            if action in {"expire", "invalidate", "fail"}:
                status = str(evaluation.get("status") or {"expire": "expired", "invalidate": "invalidated", "fail": "failed"}[action])
                updated_order = self.order_store.update_order(
                    order_id,
                    {
                        "status": status,
                        "finalized_at": _now_iso(),
                        "last_lifecycle_evaluation": evaluation,
                    },
                    event_type=f"paper_order_{status}",
                )
                self._consume_budget("order_action")
                outcome = None
                if self.execution_outcome_tracker is not None and updated_order is not None:
                    outcome = self.execution_outcome_tracker.record_paper_order_outcome(updated_order, evaluation)
                actions.append({"client_order_id": order_id, "ticker": ticker, "action": action, "evaluation": evaluation, "execution_outcome": outcome})
                continue

        return {
            "generated_at": _now_iso(),
            "enabled": True,
            "mode": "paper",
            "reviewed": len(actions),
            "actions": actions,
            "store_summary": self.order_store.summary(),
            "paper_budget_status": self.budget_status(),
        }

    def review_no_fill_followups(self, feature_packs: Dict[str, Dict[str, Any]], *, cycle_source: str = "phase_b_no_fill_followup") -> Dict[str, Any]:
        """Review final unfilled paper orders using later market context.

        Phase B.3: this is paper-only execution learning. It never creates,
        cancels, replaces, or submits live Coinbase orders. It records a single
        follow-up outcome per final no-fill order, so repeated hourly reviews do
        not spam learning logs.
        """
        if not self.enabled():
            return {
                "generated_at": _now_iso(),
                "enabled": False,
                "mode": "paper",
                "reviewed": 0,
                "actions": [],
                "reason": "limit_order_manager_disabled_or_live_flags_enabled",
                "paper_budget_status": self.budget_status(),
            }
        if self.execution_outcome_tracker is None:
            return {
                "generated_at": _now_iso(),
                "enabled": True,
                "mode": "paper",
                "reviewed": 0,
                "actions": [],
                "reason": "execution_outcome_tracker_not_configured",
                "paper_budget_status": self.budget_status(),
            }
        if not bool(getattr(self.cfg, "enable_paper_no_fill_followup_analysis", True)):
            return {
                "generated_at": _now_iso(),
                "enabled": True,
                "mode": "paper",
                "reviewed": 0,
                "actions": [],
                "reason": "paper_no_fill_followup_analysis_disabled",
                "paper_budget_status": self.budget_status(),
            }

        min_move_pct = getattr(self.cfg, "paper_no_fill_followup_min_move_pct", Decimal("0.005"))
        actions: List[Dict[str, Any]] = []
        feature_packs = feature_packs if isinstance(feature_packs, dict) else {}
        for order in self.order_store.final_orders():
            status = str(order.get("status") or "").lower().strip()
            if status not in {"expired", "invalidated", "cancelled"}:
                continue
            if to_decimal(order.get("filled_size"), "0") > Decimal("0"):
                continue
            if order.get("paper_no_fill_followup_recorded_at"):
                continue
            ticker = str(order.get("ticker") or "").upper().strip()
            feature_pack = feature_packs.get(ticker)
            if not isinstance(feature_pack, dict) or not feature_pack:
                continue
            outcome = self.execution_outcome_tracker.record_paper_no_fill_followup(
                order,
                feature_pack,
                horizon_label=cycle_source,
                min_move_pct=min_move_pct,
            )
            updated_order = self.order_store.update_order(
                str(order.get("client_order_id")),
                {
                    "paper_no_fill_followup_recorded_at": _now_iso(),
                    "paper_no_fill_followup_status": "recorded",
                    "last_no_fill_followup_outcome": outcome,
                },
                event_type="paper_no_fill_followup_recorded",
            )
            actions.append({
                "client_order_id": order.get("client_order_id"),
                "ticker": ticker,
                "status": status,
                "action": "no_fill_followup_recorded",
                "execution_outcome": outcome,
                "updated": bool(updated_order),
            })

        return {
            "generated_at": _now_iso(),
            "enabled": True,
            "mode": "paper",
            "reviewed": len(actions),
            "actions": actions,
            "store_summary": self.order_store.summary(),
            "paper_budget_status": self.budget_status(),
        }

    def _paper_available_balances(self, *, ticker: str, feature_pack: Dict[str, Any], existing_position: Optional[Dict[str, Any]]) -> Dict[str, str]:
        risk_context = feature_pack.get("risk_context", {}) if isinstance(feature_pack.get("risk_context"), dict) else {}
        total_quote = _max_decimal(risk_context.get("available_quote_balance"), feature_pack.get("available_quote_balance"))
        total_base = _max_decimal(
            risk_context.get("available_base_balance"),
            feature_pack.get("available_base_balance"),
            (existing_position or {}).get("position_size_base"),
            (existing_position or {}).get("size_base"),
        )
        return {
            "available_quote_balance": str(total_quote),
            "available_base_balance": str(total_base),
            "available_quote_after_reserved_orders": self.order_store.available_quote_after_reserved_orders(total_quote),
            "available_base_after_reserved_exit_orders": self.order_store.available_base_after_reserved_exit_orders(ticker=ticker, total_base=total_base),
        }

    def _validate_paper_intent_against_phase_b4_rails(
        self,
        *,
        intent: Dict[str, Any],
        ticker: str,
        feature_pack: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]],
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        reasons: List[str] = []
        side = str(intent.get("side", "")).upper()
        action = str(intent.get("execution_action", "")).lower()
        balances = self._paper_available_balances(ticker=ticker, feature_pack=feature_pack, existing_position=existing_position)
        open_counts = self.order_store.open_order_counts()
        ticker_counts = (open_counts.get("by_ticker") or {}).get(str(ticker).upper(), {"total": 0, "buy": 0, "sell": 0})

        max_total = int(getattr(self.cfg, "max_open_paper_orders_total", 3))
        if max_total >= 0 and int(open_counts.get("total_open_orders", 0)) >= max_total:
            reasons.append("max_open_paper_orders_total_reached")

        if side == "BUY":
            max_entry_per_ticker = int(getattr(self.cfg, "max_open_paper_entry_orders_per_ticker", 1))
            if max_entry_per_ticker >= 0 and int(ticker_counts.get("buy", 0)) >= max_entry_per_ticker:
                reasons.append("max_open_paper_entry_orders_per_ticker_reached")
            if self.order_store.has_duplicate_entry_order(ticker=ticker):
                reasons.append("duplicate_open_paper_entry_order")
            if bool(getattr(self.cfg, "enable_paper_reserved_balance_checks", True)):
                available_after = to_decimal(balances.get("available_quote_after_reserved_orders"), "0")
                requested = to_decimal(intent.get("size_quote"), "0")
                if requested > ZERO and available_after > ZERO and requested > available_after:
                    reasons.append("paper_quote_balance_after_reserved_orders_insufficient")
                intent.setdefault("risk_check_result", {}).setdefault("paper_reserved_balance_check", {})["available_quote_after_reserved_orders"] = str(available_after)

        elif side == "SELL":
            max_exit_per_ticker = int(getattr(self.cfg, "max_open_paper_exit_orders_per_ticker", 2))
            if max_exit_per_ticker >= 0 and int(ticker_counts.get("sell", 0)) >= max_exit_per_ticker:
                reasons.append("max_open_paper_exit_orders_per_ticker_reached")
            if self.order_store.has_duplicate_exit_order(
                ticker=ticker,
                execution_action=action,
                linked_position_id=str(intent.get("linked_position_id") or ""),
            ):
                reasons.append("duplicate_open_paper_exit_order")
            if bool(getattr(self.cfg, "enable_paper_reserved_balance_checks", True)):
                available_after = to_decimal(balances.get("available_base_after_reserved_exit_orders"), "0")
                requested = to_decimal(intent.get("size_base"), "0")
                if requested > ZERO and available_after > ZERO and requested > available_after:
                    reasons.append("paper_base_balance_after_reserved_exit_orders_insufficient")
                intent.setdefault("risk_check_result", {}).setdefault("paper_reserved_balance_check", {})["available_base_after_reserved_exit_orders"] = str(available_after)

        diagnostics = {
            "balances": balances,
            "open_order_counts": open_counts,
            "ticker_open_counts": ticker_counts,
            "limits": {
                "max_open_paper_orders_total": max_total,
                "max_open_paper_entry_orders_per_ticker": int(getattr(self.cfg, "max_open_paper_entry_orders_per_ticker", 1)),
                "max_open_paper_exit_orders_per_ticker": int(getattr(self.cfg, "max_open_paper_exit_orders_per_ticker", 2)),
            },
        }
        return not reasons, reasons, diagnostics

    def maybe_create_order_from_execution_plan(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        execution_plan: Optional[Dict[str, Any]],
        feature_pack: Dict[str, Any],
        existing_position: Optional[Dict[str, Any]] = None,
        position_action: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled():
            return None
        if not isinstance(execution_plan, dict):
            return None

        intent = build_order_intent_from_execution_plan(
            cfg=self.cfg,
            ticker=ticker,
            analysis=analysis,
            execution_plan=execution_plan,
            feature_pack=feature_pack,
            existing_position=existing_position,
            position_action=position_action,
        )

        if not is_actionable_order_intent(intent):
            self.order_store.append_event("paper_order_intent_rejected", {"intent": intent, "paper_budget_status": self.budget_status()})
            return {
                "generated_at": _now_iso(),
                "ticker": ticker,
                "mode": "paper",
                "status": "paper_order_intent_rejected",
                "intent": intent,
                "paper_budget_status": self.budget_status(),
            }

        allowed, budget_reason = self._budget_allows("new_order")
        if not allowed:
            intent.setdefault("risk_check_result", {}).setdefault("reject_reasons", []).append(budget_reason)
            return self._skip_by_budget(ticker=ticker, action_type="new_order", reason=budget_reason or "paper_new_order_budget_exhausted", intent=intent)

        phase_b4_ok, phase_b4_reasons, phase_b4_diagnostics = self._validate_paper_intent_against_phase_b4_rails(
            intent=intent,
            ticker=ticker,
            feature_pack=feature_pack if isinstance(feature_pack, dict) else {},
            existing_position=existing_position,
        )
        intent.setdefault("risk_check_result", {})["phase_b4_paper_rails"] = {
            "accepted": phase_b4_ok,
            "reject_reasons": phase_b4_reasons,
            "diagnostics": phase_b4_diagnostics,
        }
        if not phase_b4_ok:
            intent.setdefault("risk_check_result", {}).setdefault("reject_reasons", []).extend(phase_b4_reasons)
            self.order_store.append_event("paper_order_intent_phase_b4_rejected", {"intent": intent, "paper_budget_status": self.budget_status()})
            return {
                "generated_at": _now_iso(),
                "ticker": ticker,
                "mode": "paper",
                "status": "paper_order_phase_b4_rejected",
                "intent": intent,
                "paper_budget_status": self.budget_status(),
            }

        # Backward-compatible generic duplicate guard remains as a final safety net.
        if self.order_store.has_duplicate_open_order(
            ticker=ticker,
            side=str(intent.get("side")),
            execution_action=str(intent.get("execution_action")),
        ):
            intent.setdefault("risk_check_result", {}).setdefault("reject_reasons", []).append("duplicate_open_paper_order")
            self.order_store.append_event("paper_order_intent_duplicate_skipped", {"intent": intent, "paper_budget_status": self.budget_status()})
            return {
                "generated_at": _now_iso(),
                "ticker": ticker,
                "mode": "paper",
                "status": "paper_order_duplicate_skipped",
                "intent": intent,
                "paper_budget_status": self.budget_status(),
            }

        order = dict(intent)
        order["status"] = "submitted"
        order["submitted_at"] = _now_iso()
        order["paper_submit_reason"] = "phase_b_paper_limit_order_manager_no_live_coinbase_order"
        order["paper_budget_status_at_submit"] = self.budget_status()
        stored = self.order_store.upsert_order(order, event_type="paper_order_submitted")
        self._consume_budget("new_order")
        return {
            "generated_at": _now_iso(),
            "ticker": ticker,
            "mode": "paper",
            "status": "paper_order_submitted",
            "order": stored,
            "paper_budget_status": self.budget_status(),
        }
