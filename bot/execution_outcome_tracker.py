from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.decision_outcome_tracker import extract_candles
from bot.growbot_river_learning_contract import build_learning_context_snapshot


EXECUTION_OUTCOME_LABELS = {
    "good_limit_execution",
    "bad_limit_execution",
    "limit_better_than_market",
    "market_would_have_been_better",
    "missed_fill_opportunity",
    "correct_no_fill",
    "avoided_bad_entry",
    "bad_fill_after_breakdown",
    "good_cancel",
    "bad_cancel",
    "good_replace",
    "bad_replace",
    "partial_fill_good",
    "partial_fill_problem",
    "expired_correctly",
    "expired_too_early",
    "expired_too_late",
    "paper_lifecycle_failed",
}


ZERO = Decimal("0")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _pct_diff(reference: Decimal, actual: Decimal) -> Optional[str]:
    if reference <= ZERO or actual <= ZERO:
        return None
    return str((actual - reference) / reference)


def _market_snapshot(evaluation: Dict[str, Any]) -> Dict[str, Decimal]:
    snapshot = evaluation.get("market_snapshot") if isinstance(evaluation, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    return {
        "best_bid": _to_decimal(snapshot.get("best_bid"), "0"),
        "best_ask": _to_decimal(snapshot.get("best_ask"), "0"),
        "mid_price": _to_decimal(snapshot.get("mid_price"), "0"),
    }


def build_paper_execution_outcome(order: Dict[str, Any], evaluation: Dict[str, Any]) -> Dict[str, Any]:
    """Build a conservative execution-outcome record for a phase-B paper order.

    This intentionally evaluates only the execution thesis, not the trade thesis.
    It does not change risk rules and is safe context-only learning data.
    """
    order = order if isinstance(order, dict) else {}
    evaluation = evaluation if isinstance(evaluation, dict) else {}

    side = str(order.get("side") or "").upper().strip()
    ticker = str(order.get("ticker") or "").upper().strip()
    action = str(evaluation.get("action") or "").lower().strip()
    status = str(evaluation.get("status") or order.get("status") or "unknown").lower().strip()
    limit_price = _to_decimal(order.get("limit_price"), "0")
    fill_price = _to_decimal(evaluation.get("fill_price") or order.get("avg_fill_price"), "0")
    ctx = _market_snapshot(evaluation)
    execution_feature_pack = _as_dict(evaluation.get("feature_pack")) or _as_dict(order.get("feature_pack"))
    learning_context = build_learning_context_snapshot(
        execution_feature_pack,
        {**order, **evaluation, "ticker": ticker, "order_status": status, "lifecycle_action": action},
        candles=extract_candles(execution_feature_pack),
    )

    labels: List[str] = []
    confidence = Decimal("0.35")
    reason = str(evaluation.get("reason") or "paper_order_lifecycle_event")
    estimated_market_reference: Optional[Decimal] = None
    limit_vs_market_pct: Optional[str] = None

    if action == "fill" or status == "filled":
        if side == "BUY":
            estimated_market_reference = ctx.get("best_ask") or ZERO
            # For buys: lower fill than immediate ask is better; equality is still a good simulated fill.
            if estimated_market_reference > ZERO and fill_price > ZERO:
                limit_vs_market_pct = _pct_diff(estimated_market_reference, fill_price)
                labels.append("limit_better_than_market" if fill_price < estimated_market_reference else "good_limit_execution")
            else:
                labels.append("good_limit_execution")
        elif side == "SELL":
            estimated_market_reference = ctx.get("best_bid") or ZERO
            # For sells: higher fill than immediate bid is better; equality is still a good simulated fill.
            if estimated_market_reference > ZERO and fill_price > ZERO:
                limit_vs_market_pct = _pct_diff(estimated_market_reference, fill_price)
                labels.append("limit_better_than_market" if fill_price > estimated_market_reference else "good_limit_execution")
            else:
                labels.append("good_limit_execution")
        else:
            labels.append("good_limit_execution")
        confidence = Decimal("0.45")

    elif action == "invalidate" or status == "invalidated":
        labels.append("avoided_bad_entry")
        confidence = Decimal("0.55")
        reason = "paper_order_invalidated_before_fill_avoided_bad_entry_candidate"

    elif action == "expire" or status == "expired":
        labels.append("expired_correctly")
        labels.append("correct_no_fill")
        confidence = Decimal("0.35")
        reason = "paper_order_expired_without_fill_preliminary_correct_no_fill"

    elif action == "fail" or status == "failed":
        labels.append("paper_lifecycle_failed")
        confidence = Decimal("0.25")

    else:
        labels.append("correct_no_fill")
        confidence = Decimal("0.25")

    labels = [label for label in labels if label in EXECUTION_OUTCOME_LABELS]
    if not labels:
        labels = ["correct_no_fill"]

    return {
        "generated_at": _now_iso(),
        "source": "phase_b_paper_limit_order_manager",
        "mode": "paper",
        "paper_only": True,
        "trade_thesis_evaluated": False,
        "execution_thesis_evaluated": True,
        "ticker": ticker,
        "client_order_id": order.get("client_order_id"),
        "linked_trade_plan_id": order.get("linked_trade_plan_id"),
        "linked_position_id": order.get("linked_position_id"),
        "side": side,
        "execution_action": order.get("execution_action"),
        "order_status": status,
        "lifecycle_action": action,
        "limit_price": str(limit_price) if limit_price > ZERO else None,
        "fill_price": str(fill_price) if fill_price > ZERO else None,
        "estimated_market_reference_price": str(estimated_market_reference) if estimated_market_reference and estimated_market_reference > ZERO else None,
        "limit_vs_market_pct": limit_vs_market_pct,
        "labels": labels,
        "primary_label": labels[0],
        "confidence": str(confidence),
        "sample_size": 1,
        "recency": "fresh",
        "setup_type": order.get("setup_type") or (order.get("gpt_output") or {}).get("setup_type"),
        "market_regime": order.get("market_regime"),
        "timeframe": order.get("timeframe") or "phase_b_paper_lifecycle",
        "btc_eth_context": order.get("btc_eth_context"),
        "overfit_warning": "single_paper_sample_do_not_change_hard_rules",
        "allowed_use": "soft_context_only",
        "reason": reason,
        "paper_order_reason": order.get("reason"),
        "market_snapshot": {k: str(v) for k, v in ctx.items() if v > ZERO},
        "raw_lifecycle_evaluation": evaluation,
        "growbot_river_learning_context": learning_context,
    }


def _feature_pack_market_snapshot(feature_pack: Dict[str, Any]) -> Dict[str, Decimal]:
    feature_pack = feature_pack if isinstance(feature_pack, dict) else {}
    market = feature_pack.get("market", {}) if isinstance(feature_pack.get("market"), dict) else {}
    orderbook_context = feature_pack.get("orderbook_context", {}) if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    best_bid = _to_decimal(orderbook_context.get("best_bid") or market.get("best_bid"), "0")
    best_ask = _to_decimal(orderbook_context.get("best_ask") or market.get("best_ask"), "0")
    mid_price = _to_decimal(
        orderbook_context.get("mid_price")
        or market.get("mid_price")
        or market.get("price")
        or market.get("last_price"),
        "0",
    )
    if mid_price <= ZERO and best_bid > ZERO and best_ask > ZERO:
        mid_price = (best_bid + best_ask) / Decimal("2")
    return {"best_bid": best_bid, "best_ask": best_ask, "mid_price": mid_price}


def build_paper_no_fill_followup_outcome(
    order: Dict[str, Any],
    feature_pack: Dict[str, Any],
    *,
    horizon_label: str = "phase_b_followup",
    min_move_pct: Decimal | str = Decimal("0.005"),
) -> Dict[str, Any]:
    """Classify paper no-fill outcomes using a later market snapshot.

    This is deliberately conservative and paper-only. It helps distinguish a
    correct no-fill from a missed fill opportunity after an order expired or was
    invalidated. It never changes thresholds, sizing, or risk rules.
    """
    order = order if isinstance(order, dict) else {}
    side = str(order.get("side") or "").upper().strip()
    ticker = str(order.get("ticker") or "").upper().strip()
    status = str(order.get("status") or "unknown").lower().strip()
    limit_price = _to_decimal(order.get("limit_price"), "0")
    invalidation_price = _to_decimal(order.get("invalidation_price"), "0")
    filled_size = _to_decimal(order.get("filled_size"), "0")
    ctx = _feature_pack_market_snapshot(feature_pack)
    learning_context = build_learning_context_snapshot(
        feature_pack,
        {**order, "ticker": ticker, "order_status": status},
        candles=extract_candles(feature_pack),
    )
    best_bid = ctx.get("best_bid", ZERO)
    best_ask = ctx.get("best_ask", ZERO)
    mid_price = ctx.get("mid_price", ZERO)
    min_move = _to_decimal(min_move_pct, "0.005")
    if min_move < ZERO:
        min_move = Decimal("0.005")

    labels: List[str] = []
    confidence = Decimal("0.35")
    reason = "paper_no_fill_followup_insufficient_context"
    reference_price: Optional[Decimal] = None
    post_move_pct: Optional[str] = None

    if filled_size > ZERO or status == "filled":
        labels = ["good_limit_execution"]
        confidence = Decimal("0.25")
        reason = "paper_followup_skipped_order_already_filled"
    elif limit_price <= ZERO:
        labels = ["correct_no_fill"]
        confidence = Decimal("0.20")
        reason = "paper_no_fill_followup_missing_limit_price"
    elif side == "BUY":
        reference_price = best_ask if best_ask > ZERO else mid_price
        post_move_pct = _pct_diff(limit_price, reference_price) if reference_price and reference_price > ZERO else None
        if status == "invalidated" or (invalidation_price > ZERO and mid_price > ZERO and mid_price <= invalidation_price):
            labels = ["avoided_bad_entry", "correct_no_fill"]
            confidence = Decimal("0.55")
            reason = "paper_buy_no_fill_followup_price_breached_invalidation_or_order_invalidated"
        elif best_ask > ZERO and best_ask <= limit_price:
            labels = ["missed_fill_opportunity", "expired_too_early"]
            confidence = Decimal("0.50")
            reason = "paper_buy_no_fill_followup_later_best_ask_reached_limit"
        elif reference_price > limit_price * (Decimal("1") + min_move):
            labels = ["missed_fill_opportunity", "market_would_have_been_better"]
            confidence = Decimal("0.45")
            reason = "paper_buy_no_fill_followup_market_moved_up_without_fill"
        else:
            labels = ["correct_no_fill"]
            confidence = Decimal("0.35")
            reason = "paper_buy_no_fill_followup_no_clear_missed_fill"
    elif side == "SELL":
        reference_price = best_bid if best_bid > ZERO else mid_price
        post_move_pct = _pct_diff(limit_price, reference_price) if reference_price and reference_price > ZERO else None
        if best_bid > ZERO and best_bid >= limit_price:
            labels = ["missed_fill_opportunity", "expired_too_early"]
            confidence = Decimal("0.50")
            reason = "paper_sell_no_fill_followup_later_best_bid_reached_limit"
        elif reference_price > ZERO and reference_price < limit_price * (Decimal("1") - min_move):
            labels = ["missed_fill_opportunity", "market_would_have_been_better"]
            confidence = Decimal("0.45")
            reason = "paper_sell_no_fill_followup_market_fell_after_unfilled_exit"
        else:
            labels = ["correct_no_fill"]
            confidence = Decimal("0.35")
            reason = "paper_sell_no_fill_followup_no_clear_missed_exit"
    else:
        labels = ["correct_no_fill"]
        confidence = Decimal("0.20")
        reason = "paper_no_fill_followup_unknown_side"

    labels = [label for label in labels if label in EXECUTION_OUTCOME_LABELS]
    if not labels:
        labels = ["correct_no_fill"]

    return {
        "generated_at": _now_iso(),
        "source": "phase_b_paper_no_fill_followup",
        "mode": "paper",
        "paper_only": True,
        "trade_thesis_evaluated": False,
        "execution_thesis_evaluated": True,
        "ticker": ticker,
        "client_order_id": order.get("client_order_id"),
        "linked_trade_plan_id": order.get("linked_trade_plan_id"),
        "linked_position_id": order.get("linked_position_id"),
        "side": side,
        "execution_action": order.get("execution_action"),
        "order_status": status,
        "lifecycle_action": "no_fill_followup",
        "horizon_label": horizon_label,
        "limit_price": str(limit_price) if limit_price > ZERO else None,
        "invalidation_price": str(invalidation_price) if invalidation_price > ZERO else None,
        "followup_reference_price": str(reference_price) if reference_price and reference_price > ZERO else None,
        "post_move_pct_vs_limit": post_move_pct,
        "labels": labels,
        "primary_label": labels[0],
        "confidence": str(confidence),
        "sample_size": 1,
        "recency": "fresh",
        "setup_type": order.get("setup_type") or (order.get("gpt_output") or {}).get("setup_type"),
        "market_regime": order.get("market_regime"),
        "timeframe": order.get("timeframe") or "phase_b_paper_no_fill_followup",
        "btc_eth_context": order.get("btc_eth_context"),
        "overfit_warning": "single_paper_followup_sample_do_not_change_hard_rules",
        "allowed_use": "soft_context_only",
        "reason": reason,
        "paper_order_reason": order.get("reason"),
        "market_snapshot": {k: str(v) for k, v in ctx.items() if v > ZERO},
        "raw_lifecycle_evaluation": order.get("last_lifecycle_evaluation"),
        "growbot_river_learning_context": learning_context,
    }


class ExecutionOutcomeTracker:
    """Append-only execution outcome logger.

    Phase B only records paper execution outcomes. These records are deliberately
    soft context and must never modify deterministic risk rails automatically.
    """

    def __init__(self, log_path: str | Path = "logs/execution_outcomes.jsonl", enabled: bool = True) -> None:
        self.log_path = Path(log_path)
        self.enabled = bool(enabled)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, outcome: Dict[str, Any]) -> Dict[str, Any]:
        safe = _json_safe(outcome if isinstance(outcome, dict) else {})
        if self.enabled:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(safe, ensure_ascii=False) + "\n")
        return safe

    def record_paper_order_outcome(self, order: Dict[str, Any], evaluation: Dict[str, Any]) -> Dict[str, Any]:
        outcome = build_paper_execution_outcome(order, evaluation)
        return self.append(outcome)


    def record_paper_no_fill_followup(
        self,
        order: Dict[str, Any],
        feature_pack: Dict[str, Any],
        *,
        horizon_label: str = "phase_b_followup",
        min_move_pct: Decimal | str = Decimal("0.005"),
    ) -> Dict[str, Any]:
        outcome = build_paper_no_fill_followup_outcome(
            order,
            feature_pack,
            horizon_label=horizon_label,
            min_move_pct=min_move_pct,
        )
        return self.append(outcome)

    def load_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.log_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        try:
            with self.log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
        except Exception:
            return []
        return rows[-max(1, int(limit)):]

    def summary(self, limit: int = 500) -> Dict[str, Any]:
        rows = self.load_recent(limit=limit)
        by_label: Dict[str, int] = {}
        by_ticker: Dict[str, int] = {}
        for row in rows:
            label = str(row.get("primary_label") or "unknown")
            ticker = str(row.get("ticker") or "UNKNOWN")
            by_label[label] = by_label.get(label, 0) + 1
            by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
        return {
            "generated_at": _now_iso(),
            "count": len(rows),
            "by_label": by_label,
            "by_ticker": by_ticker,
            "allowed_use": "soft_context_only",
            "overfit_warning": "summary_is_based_on_recent_paper_records_only",
        }
