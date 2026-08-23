"""Shadow Outcome Accelerator — evidence-only, no live risk, no Coinbase calls.

Every full-cycle ticker decision (wait/reject/no_plan/blocked/approve_trade/etc.)
is captured as a shadow record with a complete snapshot of available fields.
After 1h, 4h, and 24h the evaluator checks local price/candle data to classify
what *would* have happened, producing learning evidence for GrowBot/River parameter
optimisation without any live orders or Coinbase API calls.

Nothing in this module submits, cancels, replaces or modifies live orders.
Nothing mutates BotConfig, approved profiles, .env or any live parameter.
No Coinbase API calls are made — evaluation uses only local feature_pack data.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bot.decision_outcome_tracker import (
    _json_safe,
    _normalize_ticker,
    _now_iso,
    _now_utc,
    _parse_dt,
    _pct_change,
    _to_float,
    compute_path_metrics,
    extract_candles,
    extract_current_price,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHADOW_OUTCOME_VERSION = "shadow_outcome_accelerator_v1"
SHADOW_HORIZONS_HOURS: Tuple[int, ...] = (1, 4, 24)
SHADOW_STORE_PATH = Path("state/shadow_decision_outcomes.jsonl")
REPORT_JSON_PATH = Path("reports/parameter_optimization/shadow-outcome-accelerator-latest.json")
REPORT_MD_PATH = Path("reports/parameter_optimization/shadow-outcome-accelerator-latest.md")

LEARNING_POLICY = (
    "Shadow evidence is observation-only. No live execution authority. "
    "No parameter auto-apply outside the approved-profile/governor route."
)

_DEFAULT_MIN_MOVE_PCT = 0.015    # 1.5% — classifies as meaningful upside
_DEFAULT_ADVERSE_MOVE_PCT = 0.012  # 1.2% — classifies as meaningful downside

_QUALITY_RANK: Dict[str, int] = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _shadow_id(ticker: str, ts: str, decision: str) -> str:
    raw = f"shadow|{ticker}|{ts}|{decision}"
    return "sha_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    node = d
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node is not None else default


def _float_or_none(value: Any) -> Optional[float]:
    return _to_float(value)


def _str_or_none(value: Any, max_len: int = 256) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s[:max_len] if s else None


# ---------------------------------------------------------------------------
# Shadow Record Builder
# ---------------------------------------------------------------------------

def build_shadow_decision_record(
    *,
    ticker: str,
    analysis: Dict[str, Any],
    cycle_result: Optional[Dict[str, Any]] = None,
    feature_pack: Optional[Dict[str, Any]] = None,
    cycle_id: Optional[str] = None,
    generated_at: Any = None,
    horizons_hours: Tuple[int, ...] = SHADOW_HORIZONS_HOURS,
) -> Optional[Dict[str, Any]]:
    """Build a shadow decision record for any full-cycle ticker decision.

    Returns None if ticker is empty or cannot be determined. Never raises.
    No Coinbase calls. No live orders. No parameter mutation.
    """
    ticker = _normalize_ticker(ticker or (analysis.get("ticker") if isinstance(analysis, dict) else ""))
    if not ticker:
        return None

    if not isinstance(analysis, dict):
        analysis = {}
    feature_pack = feature_pack or analysis.get("feature_pack") or {}
    if not isinstance(feature_pack, dict):
        feature_pack = {}
    cycle_result = cycle_result or {}
    if not isinstance(cycle_result, dict):
        cycle_result = {}

    now_dt = (
        _parse_dt(generated_at)
        or _parse_dt(analysis.get("generated_at"))
        or _parse_dt(cycle_result.get("generated_at"))
        or _now_utc()
    )
    ts = now_dt.isoformat()

    # Core nested dicts
    judge = analysis.get("judge") or {}
    if not isinstance(judge, dict):
        judge = {}
    # Fallback: _analysis_to_cycle_result stores the judge dict under result["analysis"].
    # When a cycle_result is passed and analysis has no "judge" key, extract from there.
    if not judge and isinstance(cycle_result, dict):
        judge_candidate = cycle_result.get("analysis")
        if isinstance(judge_candidate, dict):
            judge = judge_candidate
    entry_gate = analysis.get("entry_gate") or cycle_result.get("entry_gate") or {}
    if not isinstance(entry_gate, dict):
        entry_gate = {}
    trade_plan = analysis.get("trade_plan") or {}
    if not isinstance(trade_plan, dict):
        trade_plan = {}
    market = _safe_get(feature_pack, "market") or {}
    if not isinstance(market, dict):
        market = {}
    orderbook = _safe_get(feature_pack, "orderbook_context") or {}
    if not isinstance(orderbook, dict):
        orderbook = {}

    # Decision
    decision = _str_or_none(
        judge.get("decision")
        or cycle_result.get("decision")
        or analysis.get("decision")
        or "wait"
    ) or "wait"

    side = _str_or_none(
        judge.get("side") or trade_plan.get("side") or analysis.get("side")
    )
    setup_type = _str_or_none(
        entry_gate.get("setup_type") or trade_plan.get("setup_type") or analysis.get("setup_type")
    )

    # Scores / confidence
    bull_score = _float_or_none(
        judge.get("bull_score")
        or analysis.get("bull_score")
        or _safe_get(analysis, "scores", "bull")
    )
    bear_score = _float_or_none(
        judge.get("bear_score")
        or analysis.get("bear_score")
        or _safe_get(analysis, "scores", "bear")
    )
    synth_confidence = _float_or_none(
        judge.get("synth_confidence")
        or judge.get("confidence")
        or analysis.get("synth_confidence")
        or analysis.get("confidence")
    )
    gate_confidence = _float_or_none(
        entry_gate.get("confidence") or analysis.get("gate_confidence")
    )

    # Judge / gate metadata
    judge_decision = _str_or_none(judge.get("decision"))
    judge_reason = _str_or_none(judge.get("reason") or judge.get("rationale"), max_len=512)
    blocked_by = _str_or_none(
        cycle_result.get("blocked_by")
        or analysis.get("blocked_by")
        or judge.get("blocked_by")
    )
    gate_reason = _str_or_none(
        entry_gate.get("reason")
        or entry_gate.get("rationale")
        or analysis.get("gate_reason"),
        max_len=512,
    )

    # Market microstructure
    mid_price = _float_or_none(
        orderbook.get("mid_price")
        or market.get("mid_price")
        or market.get("price")
        or extract_current_price(feature_pack)
    )
    best_bid = _float_or_none(orderbook.get("best_bid") or market.get("best_bid"))
    best_ask = _float_or_none(orderbook.get("best_ask") or market.get("best_ask"))

    spread: Optional[float] = None
    if best_bid and best_ask and best_bid > 0:
        spread = round((best_ask - best_bid) / best_bid, 6)
    elif _float_or_none(orderbook.get("spread_pct")) is not None:
        spread = _float_or_none(orderbook.get("spread_pct"))

    fee_estimate = _float_or_none(
        trade_plan.get("estimated_fee_pct")
        or analysis.get("fee_estimate")
        or analysis.get("estimated_fee_pct")
    )

    orderbook_snapshot: Optional[Dict[str, Any]] = None
    if best_bid is not None or best_ask is not None:
        orderbook_snapshot = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid_price,
            "spread_pct": spread,
            "imbalance": _float_or_none(
                orderbook.get("imbalance") or orderbook.get("orderbook_imbalance")
            ),
        }

    # Market regime
    market_regime = _str_or_none(
        analysis.get("market_regime")
        or _safe_get(feature_pack, "market_regime")
        or _safe_get(feature_pack, "regime", "market_regime")
        or _safe_get(feature_pack, "market", "regime")
    )

    # Trade plan levels
    proposed_entry = _float_or_none(
        trade_plan.get("trigger")
        or trade_plan.get("entry_price")
        or trade_plan.get("entry_zone_high")
        or trade_plan.get("entry_zone_low")
    )
    proposed_stop = _float_or_none(
        trade_plan.get("stop_loss") or trade_plan.get("invalidation_price")
    )
    proposed_tp = _float_or_none(
        trade_plan.get("take_profit_1") or trade_plan.get("take_profit")
    )

    # Risk / reward
    risk_reward = _float_or_none(
        trade_plan.get("risk_reward_ratio")
        or trade_plan.get("reward_to_risk")
        or analysis.get("risk_reward_ratio")
    )
    reward_to_fee = _float_or_none(
        trade_plan.get("reward_to_fee")
        or analysis.get("reward_to_fee")
        or trade_plan.get("net_edge_pct")
    )

    # Model / agent routing
    model_route = _str_or_none(
        analysis.get("model_route")
        or analysis.get("model")
        or judge.get("model")
        or cycle_result.get("model_route")
    )
    agent_route = _str_or_none(
        analysis.get("agent_route")
        or cycle_result.get("agent_route")
        or analysis.get("agent")
        or judge.get("agent")
    )

    # Evaluation slots — filled later by evaluate_due()
    evaluations: Dict[str, Any] = {}
    due_at: Dict[str, str] = {}
    for h in horizons_hours:
        key = f"{h}h"
        evaluations[key] = None
        due_at[key] = (now_dt + timedelta(hours=h)).isoformat()

    shadow_id = _shadow_id(ticker, ts, decision)

    return {
        "shadow_id": shadow_id,
        "schema_version": SHADOW_OUTCOME_VERSION,
        "timestamp": ts,
        "ticker": ticker,
        "product_id": ticker,
        "cycle_id": _str_or_none(
            cycle_id or cycle_result.get("cycle_id") or analysis.get("cycle_id")
        ),
        "decision": decision,
        "side": side,
        "setup_type": setup_type,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "synth_confidence": synth_confidence,
        "gate_confidence": gate_confidence,
        "judge_decision": judge_decision,
        "judge_reason": judge_reason,
        "blocked_by": blocked_by,
        "gate_reason": gate_reason,
        "mid_price": mid_price,
        "spread": spread,
        "fee_estimate": fee_estimate,
        "orderbook_snapshot": orderbook_snapshot,
        "market_regime": market_regime,
        "proposed_entry_price": proposed_entry,
        "proposed_stop": proposed_stop,
        "proposed_take_profit": proposed_tp,
        "risk_reward": risk_reward,
        "reward_to_fee": reward_to_fee,
        "model_route": model_route,
        "agent_route": agent_route,
        "evaluations": evaluations,
        "due_at": due_at,
        "status": "pending",
        "evidence_type": "shadow",
        "learning_policy": LEARNING_POLICY,
        "no_live_orders": True,
        "no_coinbase_calls": True,
        "no_parameter_mutation": True,
    }


# ---------------------------------------------------------------------------
# Evaluation logic
# ---------------------------------------------------------------------------

def _classify_shadow_outcome(
    *,
    decision: str,
    price_move_pct: Optional[float],
    hypothetical_mfe: Optional[float],
    hypothetical_mae: Optional[float],
    would_tp_have_hit: Optional[bool],
    would_stop_have_hit: Optional[bool],
    min_move_pct: float,
    adverse_move_pct: float,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (bad_trade_avoided_label, missed_opportunity_label)."""
    if price_move_pct is None and hypothetical_mfe is None:
        return None, None

    d = str(decision or "").lower()
    is_rejection = d in {
        "wait", "reject", "no_plan", "blocked", "skip", "watch", "hold",
        "entry_gate_skip", "entry_gate_watch", "no_trade", "no_trade_no_plan",
    }

    mfe = hypothetical_mfe if hypothetical_mfe is not None else 0.0
    mae = hypothetical_mae if hypothetical_mae is not None else 0.0
    move = price_move_pct if price_move_pct is not None else 0.0

    strong_up = (
        move >= min_move_pct
        or (would_tp_have_hit is True)
        or mfe >= min_move_pct
    )
    strong_down = (
        move <= -adverse_move_pct
        or (would_stop_have_hit is True)
        or mae <= -adverse_move_pct
    )

    if is_rejection:
        if strong_down:
            return "yes", "no"     # correctly avoided a bad trade
        if strong_up:
            return "no", "yes"     # missed a good trade
        return "unclear", "unclear"
    else:
        # Approval or entry decision — report what would have happened
        if strong_up and not strong_down:
            return "n/a_was_approval", "no"
        if strong_down:
            return "n/a_was_approval", "n/a_was_approval"
        return "n/a_was_approval", "unclear"


def _evidence_quality(
    *,
    has_price: bool,
    has_candles: bool,
    has_entry_levels: bool,
    price_move_pct: Optional[float],
) -> Tuple[str, bool, Optional[str]]:
    """Return (quality_label, is_usable, unusable_reason)."""
    if not has_price and not has_candles:
        return "insufficient", False, "no_local_price_or_candle_data"
    if not has_price:
        return "insufficient", False, "no_price_at_evaluation"
    if not has_candles:
        if price_move_pct is not None:
            return "low", True, None
        return "insufficient", False, "no_candles_and_no_price_move"
    if has_entry_levels:
        return "high", True, None
    return "medium", True, None


def evaluate_shadow_record(
    record: Dict[str, Any],
    *,
    feature_pack: Optional[Dict[str, Any]] = None,
    now_dt: Optional[datetime] = None,
    horizon_hours: int = 1,
    min_move_pct: float = _DEFAULT_MIN_MOVE_PCT,
    adverse_move_pct: float = _DEFAULT_ADVERSE_MOVE_PCT,
) -> Dict[str, Any]:
    """Evaluate a single shadow record at a given horizon.

    Uses only local feature_pack price/candle data. Returns an evaluation dict.
    No Coinbase API calls. No live orders. No parameter mutation.

    If insufficient local data is available, degrades to status=insufficient_data.
    """
    if not isinstance(feature_pack, dict):
        feature_pack = {}
    if now_dt is None:
        now_dt = _now_utc()
    if not isinstance(record, dict):
        record = {}

    horizon_key = f"{horizon_hours}h"
    start_price = record.get("mid_price")
    stop_loss = record.get("proposed_stop")
    take_profit = record.get("proposed_take_profit")
    entry_price = record.get("proposed_entry_price") or start_price
    created_at = record.get("timestamp")
    decision = str(record.get("decision") or "wait")
    side = str(record.get("side") or "BUY").upper()

    current_price = extract_current_price(feature_pack)
    candles = extract_candles(feature_pack, preferred_timeframes=("1h", "4h", "15m", "1d"))
    has_price = current_price is not None and current_price > 0
    has_candles = len(candles) > 0
    has_entry_levels = (stop_loss is not None) or (take_profit is not None)

    if not has_price and not has_candles:
        return {
            "horizon_hours": horizon_hours,
            "horizon_key": horizon_key,
            "status": "insufficient_data",
            "evaluated_at": now_dt.isoformat(),
            "data_source": "none",
            "price_at_evaluation": None,
            "price_move_pct": None,
            "hypothetical_mfe": None,
            "hypothetical_mae": None,
            "would_entry_have_filled": None,
            "would_tp_have_hit": None,
            "would_stop_have_hit": None,
            "bad_trade_avoided_label": None,
            "missed_opportunity_label": None,
            "reward_estimate": None,
            "evidence_usable": False,
            "evidence_quality": "insufficient",
            "evidence_unusable_reason": "no_local_price_or_candle_data",
            "learning_policy": LEARNING_POLICY,
        }

    # Path metrics from candles (read-only analytics only)
    path = compute_path_metrics(
        start_price=start_price,
        candles=candles,
        start_time=created_at,
        stop_loss=stop_loss,
        take_profit_1=take_profit,
        take_profit_2=None,
    )

    price_move_pct = (
        _pct_change(start_price, current_price)
        if (has_price and start_price is not None and start_price > 0)
        else None
    )
    path_ok = path.get("available", False)
    hyp_mfe = _float_or_none(path.get("max_favorable_pct")) if path_ok else None
    hyp_mae = _float_or_none(path.get("max_adverse_pct")) if path_ok else None
    would_tp = path.get("tp1_touched") if path_ok else None
    would_stop = path.get("stop_touched") if path_ok else None

    # Would a limit entry have filled? Conservative proxy: entry <= ask at decision time
    would_entry_filled: Optional[bool] = None
    if entry_price is not None and start_price is not None and start_price > 0:
        if side == "BUY":
            would_entry_filled = float(entry_price) >= float(start_price) * 0.998
        else:
            would_entry_filled = float(entry_price) <= float(start_price) * 1.002

    bad_avoided, missed = _classify_shadow_outcome(
        decision=decision,
        price_move_pct=price_move_pct,
        hypothetical_mfe=hyp_mfe,
        hypothetical_mae=hyp_mae,
        would_tp_have_hit=would_tp,
        would_stop_have_hit=would_stop,
        min_move_pct=min_move_pct,
        adverse_move_pct=adverse_move_pct,
    )

    quality, usable, unusable_reason = _evidence_quality(
        has_price=has_price,
        has_candles=has_candles,
        has_entry_levels=has_entry_levels,
        price_move_pct=price_move_pct,
    )

    # Reward estimate: directional value of the outcome
    reward_estimate: Optional[float] = None
    if hyp_mfe is not None or hyp_mae is not None:
        if missed == "yes":
            reward_estimate = round(abs(hyp_mfe or 0.0), 5)
        elif bad_avoided == "yes":
            reward_estimate = round(abs(hyp_mae or 0.0), 5)
        elif hyp_mfe is not None:
            reward_estimate = round(hyp_mfe, 5)
    elif price_move_pct is not None:
        reward_estimate = round(price_move_pct, 5)

    data_source = "local_candles" if has_candles else ("price_only" if has_price else "none")

    return {
        "horizon_hours": horizon_hours,
        "horizon_key": horizon_key,
        "status": "complete",
        "evaluated_at": now_dt.isoformat(),
        "data_source": data_source,
        "price_at_evaluation": current_price,
        "price_move_pct": round(price_move_pct, 6) if price_move_pct is not None else None,
        "hypothetical_mfe": round(hyp_mfe, 6) if hyp_mfe is not None else None,
        "hypothetical_mae": round(hyp_mae, 6) if hyp_mae is not None else None,
        "would_entry_have_filled": would_entry_filled,
        "would_tp_have_hit": would_tp,
        "would_stop_have_hit": would_stop,
        "bad_trade_avoided_label": bad_avoided,
        "missed_opportunity_label": missed,
        "reward_estimate": reward_estimate,
        "evidence_usable": usable,
        "evidence_quality": quality,
        "evidence_unusable_reason": unusable_reason,
        "learning_policy": LEARNING_POLICY,
    }


# ---------------------------------------------------------------------------
# Append-only JSONL store
# ---------------------------------------------------------------------------

class ShadowOutcomeStore:
    """Append-only JSONL store for shadow decision records.

    New records are appended. Evaluation results cause an atomic rewrite so
    that each record's evaluation slots stay coherent.

    Thread-safety: single-process only (no cross-process locking).
    No Coinbase API calls. No live orders. No parameter mutation.
    """

    def __init__(
        self,
        path: Path | str = SHADOW_STORE_PATH,
        *,
        enabled: bool = True,
        min_move_pct: float = _DEFAULT_MIN_MOVE_PCT,
        adverse_move_pct: float = _DEFAULT_ADVERSE_MOVE_PCT,
    ) -> None:
        self.path = Path(path)
        self.enabled = bool(enabled)
        self.min_move_pct = min_move_pct
        self.adverse_move_pct = adverse_move_pct
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # --- I/O ---

    def _append_line(self, record: Dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_json_safe(record), ensure_ascii=False) + "\n")

    def _atomic_rewrite(self, records: List[Dict[str, Any]]) -> None:
        """Atomically rewrite the entire JSONL with updated records."""
        tmp = self.path.with_suffix(".jsonl.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(_json_safe(r), ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def load_all(self) -> List[Dict[str, Any]]:
        """Load all shadow records from the JSONL store."""
        if not self.path.exists():
            return []
        records: List[Dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        if isinstance(row, dict):
                            records.append(row)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            return []
        return records

    # --- Public API ---

    def append_record(self, record: Dict[str, Any]) -> bool:
        """Append a shadow record. Returns True if stored, False if skipped (dedup)."""
        if not self.enabled or not isinstance(record, dict):
            return False
        shadow_id = record.get("shadow_id")
        if not shadow_id:
            return False
        existing = self.load_all()
        if any(r.get("shadow_id") == shadow_id for r in existing):
            return False
        self._append_line(record)
        return True

    def record_decision(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        cycle_result: Optional[Dict[str, Any]] = None,
        feature_pack: Optional[Dict[str, Any]] = None,
        cycle_id: Optional[str] = None,
        generated_at: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Build and store a shadow record for a full-cycle ticker decision.

        Returns the stored record, or None if disabled / ticker missing / dedup.
        No Coinbase calls. No live orders. No parameter mutation.
        """
        if not self.enabled:
            return None
        record = build_shadow_decision_record(
            ticker=ticker,
            analysis=analysis,
            cycle_result=cycle_result,
            feature_pack=feature_pack,
            cycle_id=cycle_id,
            generated_at=generated_at,
        )
        if record is None:
            return None
        stored = self.append_record(record)
        return record if stored else None

    def evaluate_due(
        self,
        *,
        feature_packs: Dict[str, Dict[str, Any]],
        now: Any = None,
    ) -> List[Dict[str, Any]]:
        """Fill in evaluation slots for all pending horizons that are now due.

        Uses only local feature_pack data. No Coinbase calls.
        If no local data is available for a slot, the slot stays None (pending).
        Returns the list of records that were updated.
        """
        if not self.enabled:
            return []
        now_dt = _parse_dt(now) or _now_utc()
        records = self.load_all()
        updated: List[Dict[str, Any]] = []
        changed = False

        for rec in records:
            if rec.get("status") == "complete":
                continue
            ticker = _normalize_ticker(rec.get("ticker") or "")
            fp: Dict[str, Any] = feature_packs.get(ticker) or {}
            evaluations: Dict[str, Any] = rec.get("evaluations") or {}
            due_at: Dict[str, str] = rec.get("due_at") or {}
            rec_changed = False

            for horizon_key, due_str in list(due_at.items()):
                if evaluations.get(horizon_key) is not None:
                    continue  # already evaluated
                due = _parse_dt(due_str)
                if due is None or due > now_dt:
                    continue  # not yet due
                try:
                    h = int(horizon_key.replace("h", ""))
                except ValueError:
                    continue

                eval_result = evaluate_shadow_record(
                    rec,
                    feature_pack=fp,
                    now_dt=now_dt,
                    horizon_hours=h,
                    min_move_pct=self.min_move_pct,
                    adverse_move_pct=self.adverse_move_pct,
                )
                # If the ticker was not supplied in feature_packs at all, leave
                # the slot as None so it can be retried on the next cycle.
                # If the ticker IS in feature_packs but has no usable price/candle
                # data, store the insufficient_data result so the slot is marked.
                if eval_result.get("status") == "insufficient_data" and ticker not in feature_packs:
                    continue

                evaluations[horizon_key] = eval_result
                rec["evaluations"] = evaluations
                rec_changed = True
                changed = True

            if rec_changed:
                # Recompute overall status
                all_slots = list(due_at.keys())
                none_slots = [k for k in all_slots if evaluations.get(k) is None]
                due_slots = [
                    k for k in all_slots
                    if (_parse_dt(due_at.get(k)) or now_dt) <= now_dt
                ]
                if not none_slots:
                    rec["status"] = "complete"
                elif all(k not in none_slots for k in due_slots):
                    rec["status"] = "partial"
                updated.append(rec)

        if changed:
            self._atomic_rewrite(records)

        return updated

    def pending_for_ticker(self, ticker: str) -> List[Dict[str, Any]]:
        ticker = _normalize_ticker(ticker)
        return [
            r for r in self.load_all()
            if _normalize_ticker(r.get("ticker") or "") == ticker
            and r.get("status") != "complete"
        ]

    def summary(self) -> Dict[str, Any]:
        return build_shadow_outcome_summary(self.load_all())


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_shadow_outcome_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a reporting summary from a list of shadow records. Read-only."""
    total = len(records)
    status_counts: Dict[str, int] = {}
    eval_counts: Dict[str, Dict[str, int]] = {
        "1h": {"pending": 0, "complete": 0, "insufficient_data": 0},
        "4h": {"pending": 0, "complete": 0, "insufficient_data": 0},
        "24h": {"pending": 0, "complete": 0, "insufficient_data": 0},
    }
    usable_count = 0
    by_ticker: Dict[str, int] = {}
    by_regime: Dict[str, int] = {}
    missed_patterns: Dict[str, int] = {}
    bad_avoided_patterns: Dict[str, int] = {}
    quality_counts: Dict[str, int] = {}

    for rec in records:
        status = str(rec.get("status") or "pending")
        status_counts[status] = status_counts.get(status, 0) + 1

        ticker = str(rec.get("ticker") or "UNKNOWN")
        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1

        regime = str(rec.get("market_regime") or "unknown")
        by_regime[regime] = by_regime.get(regime, 0) + 1

        evals = rec.get("evaluations") or {}
        for h_key in ("1h", "4h", "24h"):
            ev = evals.get(h_key)
            bucket = eval_counts.setdefault(h_key, {"pending": 0, "complete": 0, "insufficient_data": 0})
            if ev is None:
                bucket["pending"] = bucket.get("pending", 0) + 1
            elif ev.get("status") == "insufficient_data":
                bucket["insufficient_data"] = bucket.get("insufficient_data", 0) + 1
            else:
                bucket["complete"] = bucket.get("complete", 0) + 1
                if ev.get("evidence_usable"):
                    usable_count += 1
                q = str(ev.get("evidence_quality") or "unknown")
                quality_counts[q] = quality_counts.get(q, 0) + 1
                if ev.get("missed_opportunity_label") == "yes":
                    key = str(rec.get("setup_type") or "unknown")
                    missed_patterns[key] = missed_patterns.get(key, 0) + 1
                if ev.get("bad_trade_avoided_label") == "yes":
                    key = str(rec.get("decision") or "unknown")
                    bad_avoided_patterns[key] = bad_avoided_patterns.get(key, 0) + 1

    top_missed = sorted(missed_patterns.items(), key=lambda x: -x[1])[:5]
    top_avoided = sorted(bad_avoided_patterns.items(), key=lambda x: -x[1])[:5]

    total_complete = sum(
        eval_counts.get(h, {}).get("complete", 0) for h in ("1h", "4h", "24h")
    )
    evidence_quality_score = round(usable_count / max(1, total_complete), 3)

    sufficient = total >= 50 and usable_count >= 20
    sufficiency_note = (
        "Sufficient for qualitative review (>=50 records, >=20 usable evaluations)"
        if sufficient
        else (
            f"Not yet sufficient: {total} shadow records, {usable_count} usable evaluations "
            "(need >=50 records, >=20 usable)"
        )
    )

    return {
        "generated_at": _now_iso(),
        "schema_version": SHADOW_OUTCOME_VERSION,
        "total_shadow_decisions": total,
        "status_counts": status_counts,
        "evaluations_by_horizon": eval_counts,
        "usable_evidence_count": usable_count,
        "evidence_quality_score": evidence_quality_score,
        "by_ticker": by_ticker,
        "by_regime": by_regime,
        "top_missed_opportunity_patterns": [
            {"setup_type": k, "count": v} for k, v in top_missed
        ],
        "top_bad_trade_avoided_patterns": [
            {"decision": k, "count": v} for k, v in top_avoided
        ],
        "quality_distribution": quality_counts,
        "sufficient_for_optimization": sufficient,
        "sufficiency_note": sufficiency_note,
        "learning_policy": LEARNING_POLICY,
        "no_live_orders": True,
        "no_coinbase_calls": True,
        "no_parameter_mutation": True,
    }


# ---------------------------------------------------------------------------
# River integration — read-only evidence feed
# ---------------------------------------------------------------------------

def load_shadow_evidence_for_river(
    store_path: Path | str = SHADOW_STORE_PATH,
    *,
    min_quality: str = "medium",
    max_records: int = 500,
) -> List[Dict[str, Any]]:
    """Return completed shadow evaluations as read-only GrowBot/River evidence.

    Callers (River/GrowBot adapter) MUST treat these as observation-only.
    No execution authority. No parameter auto-apply outside the
    approved-profile/governor route.
    """
    min_rank = _QUALITY_RANK.get(min_quality, 1)
    store = ShadowOutcomeStore(path=store_path, enabled=True)
    records = store.load_all()
    evidence: List[Dict[str, Any]] = []

    for rec in records:
        evals = rec.get("evaluations") or {}
        # Prefer longer horizons (more informative)
        for h_key in ("24h", "4h", "1h"):
            ev = evals.get(h_key)
            if not isinstance(ev, dict):
                continue
            if not ev.get("evidence_usable"):
                continue
            quality = str(ev.get("evidence_quality") or "insufficient")
            if _QUALITY_RANK.get(quality, 0) < min_rank:
                continue
            evidence.append({
                "source": "shadow_outcome_accelerator",
                "allowed_use": "evidence_only_no_execution_authority",
                "shadow_id": rec.get("shadow_id"),
                "ticker": rec.get("ticker"),
                "market_regime": rec.get("market_regime"),
                "setup_type": rec.get("setup_type"),
                "decision": rec.get("decision"),
                "side": rec.get("side"),
                "horizon_key": h_key,
                "price_move_pct": ev.get("price_move_pct"),
                "hypothetical_mfe": ev.get("hypothetical_mfe"),
                "hypothetical_mae": ev.get("hypothetical_mae"),
                "bad_trade_avoided_label": ev.get("bad_trade_avoided_label"),
                "missed_opportunity_label": ev.get("missed_opportunity_label"),
                "reward_estimate": ev.get("reward_estimate"),
                "evidence_quality": quality,
                "bull_score": rec.get("bull_score"),
                "bear_score": rec.get("bear_score"),
                "synth_confidence": rec.get("synth_confidence"),
                "gate_confidence": rec.get("gate_confidence"),
                "spread": rec.get("spread"),
                "risk_reward": rec.get("risk_reward"),
                "reward_to_fee": rec.get("reward_to_fee"),
                "learning_policy": LEARNING_POLICY,
            })
            break  # one evidence entry per record (longest available horizon)

    return evidence[-max_records:]


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_shadow_outcome_reports(
    records: List[Dict[str, Any]],
    *,
    json_path: Path | str = REPORT_JSON_PATH,
    md_path: Path | str = REPORT_MD_PATH,
) -> Dict[str, Any]:
    """Write JSON + Markdown reports to reports/parameter_optimization/.

    Read-only analytics — no Coinbase calls, no live orders, no parameter mutation.
    """
    summary = build_shadow_outcome_summary(records)

    json_out = Path(json_path)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md_out = Path(md_path)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(_render_shadow_md(summary), encoding="utf-8")

    return summary


def _render_shadow_md(summary: Dict[str, Any]) -> str:
    lines: List[str] = [
        "# Shadow Outcome Accelerator — Learning Report",
        "",
        f"Generated: `{summary.get('generated_at')}`",
        "",
        "> **Evidence-only.** No live orders. No Coinbase API calls. No parameter mutation.",
        "> No execution authority. All output is shadow/reporting only.",
        "",
        "## Summary",
        "",
        f"- **Total shadow decisions:** {summary.get('total_shadow_decisions', 0)}",
        f"- **Usable evidence count:** {summary.get('usable_evidence_count', 0)}",
        f"- **Evidence quality score:** {summary.get('evidence_quality_score', 0.0):.1%}",
        f"- **Sufficient for optimization:** {summary.get('sufficient_for_optimization', False)}",
        f"- **Note:** {summary.get('sufficiency_note', '')}",
        "",
        "## Status Breakdown",
        "",
        "| Status | Count |",
        "|--------|-------|",
    ]
    for k, v in sorted((summary.get("status_counts") or {}).items()):
        lines.append(f"| {k} | {v} |")

    lines += [
        "",
        "## Evaluations by Horizon",
        "",
        "| Horizon | Pending | Complete | Insufficient Data |",
        "|---------|---------|----------|------------------|",
    ]
    for h in ("1h", "4h", "24h"):
        ev_c = (summary.get("evaluations_by_horizon") or {}).get(h) or {}
        lines.append(
            f"| {h} | {ev_c.get('pending', 0)} | {ev_c.get('complete', 0)} "
            f"| {ev_c.get('insufficient_data', 0)} |"
        )

    lines += [
        "",
        "## Per-Ticker Coverage",
        "",
        "| Ticker | Records |",
        "|--------|---------|",
    ]
    for ticker, count in sorted((summary.get("by_ticker") or {}).items()):
        lines.append(f"| {ticker} | {count} |")

    lines += [
        "",
        "## Per-Regime Coverage",
        "",
        "| Regime | Records |",
        "|--------|---------|",
    ]
    for regime, count in sorted(
        (summary.get("by_regime") or {}).items(), key=lambda x: -x[1]
    ):
        lines.append(f"| {regime} | {count} |")

    missed = summary.get("top_missed_opportunity_patterns") or []
    if missed:
        lines += [
            "",
            "## Top Missed Opportunity Patterns",
            "",
            "| Setup Type | Count |",
            "|-----------|-------|",
        ]
        for p in missed:
            lines.append(f"| {p.get('setup_type')} | {p.get('count')} |")

    avoided = summary.get("top_bad_trade_avoided_patterns") or []
    if avoided:
        lines += [
            "",
            "## Top Bad Trade Avoided Patterns",
            "",
            "| Decision | Count |",
            "|---------|-------|",
        ]
        for p in avoided:
            lines.append(f"| {p.get('decision')} | {p.get('count')} |")

    lines += [
        "",
        "## Evidence Quality Distribution",
        "",
        "| Quality | Count |",
        "|---------|-------|",
    ]
    for q, c in sorted((summary.get("quality_distribution") or {}).items()):
        lines.append(f"| {q} | {c} |")

    lines += [
        "",
        "## Learning Policy",
        "",
        f"> {LEARNING_POLICY}",
        "",
        "- No live Coinbase actions.",
        "- No parameter changes.",
        "- No `.env` writes.",
        "- No service restart.",
        "- River/GrowBot consumes shadow records as read-only evidence only.",
        "- No parameter auto-apply outside existing governor/approved-profile route.",
    ]
    return "\n".join(lines) + "\n"
